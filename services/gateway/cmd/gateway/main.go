package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"runtime/debug"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/chat"
	"github.com/UmitVice/candela/services/gateway/internal/config"
	"github.com/UmitVice/candela/services/gateway/internal/egress"
	"github.com/UmitVice/candela/services/gateway/internal/httpapi"
	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/llm/openai"
	"github.com/UmitVice/candela/services/gateway/internal/market"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
	"github.com/UmitVice/candela/services/gateway/internal/store"
	"github.com/UmitVice/candela/services/gateway/internal/tools"
	"github.com/UmitVice/candela/services/gateway/internal/workerhub"
)

var (
	version = "0.1.0-dev"
	commit  = "unknown"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "gateway:", err)
		os.Exit(1)
	}
}

func defaultFallbackModel(id string) llm.ModelInfo {
	return llm.ModelInfo{
		ID: id, DisplayName: "Qwen3 1.7B base (dev fallback)", Tier: "lite", Version: "base", BaseModel: "Qwen/Qwen3-1.7B",
		Runtime: "llama.cpp", Host: "cloud-cpu", Quantization: "Q4_K_M", ContextLength: 32768,
		SupportsReasoning: true, SupportsTools: true, SupportsTelemetry: false,
		Architecture: &llm.ModelArchitecture{Layers: 28, HiddenSize: 2048, AttentionHeads: 16, KVHeads: 8, VocabSize: 151936, Parameters: "1.7B"},
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	log := observability.NewLogger(cfg.LogLevel)
	slog.SetDefault(log)
	log.Info("starting gateway", "version", version, "commit", commit, "config", cfg)

	if n := cfg.MemoryLimitBytes(); n > 0 && os.Getenv("GOMEMLIMIT") == "" {
		debug.SetMemoryLimit(n)
	}
	metrics := observability.NewMetrics()
	egressClient := egress.NewClient(cfg.EgressAllow, 10*time.Minute)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	st, err := store.Open(ctx, cfg.DBPath, log)
	if err != nil {
		return err
	}
	defer st.Close()

	if err := market.EnsureSnapshot(ctx, egressClient, cfg.SnapshotPath, cfg.SnapshotURL, log); err != nil {
		log.Error("snapshot download failed", "err", err)
	}
	snap, err := market.OpenSnapshot(ctx, cfg.SnapshotPath)
	if err != nil {
		log.Warn("market snapshot unavailable; price tools will report data_unavailable", "err", err)
		snap = nil
	} else {
		m := snap.Meta()
		log.Info("market snapshot loaded", "asOf", m.AsOf, "source", m.Source, "symbols", len(snap.Symbols()), "fundamentals", snap.HasFundamentals())
		defer snap.Close()
	}
	dir := market.NewDirectory(st, snap, cfg.SymbolsBaseURL, egress.NewClient(cfg.EgressAllow, 60*time.Second), log)
	if err := dir.Load(ctx); err != nil {
		return err
	}
	svc := market.NewService(market.Options{Snapshot: snap, Directory: dir, Store: st, CacheTTL: cfg.MarketCacheTTL,
		LiveAPIKey: cfg.LiveAPIKey, VanirasURL: cfg.VanirasURL, Log: log})
	registry, err := tools.NewRegistry(svc)
	if err != nil {
		return err
	}

	fbModel := defaultFallbackModel(cfg.FallbackModelID)
	if cfg.FallbackModelJSON != "" {
		if err := json.Unmarshal([]byte(cfg.FallbackModelJSON), &fbModel); err != nil {
			return fmt.Errorf("CANDELA_FALLBACK_MODEL_INFO: %w", err)
		}
	}
	fbClient := openai.New(cfg.FallbackURL, cfg.FallbackAPIKey, cfg.FallbackModel, cfg.FallbackTimeout)
	var fbHealthy atomic.Bool
	hub := workerhub.New(cfg.WorkerToken, log, metrics)
	fbConcurrency := cfg.FallbackConcurrency
	if !cfg.FallbackOn() {
		fbConcurrency = 0
	}
	fallback := &chat.Fallback{Model: fbModel, Upstream: fbClient, Concurrency: fbConcurrency, Healthy: fbHealthy.Load}
	sched := chat.NewScheduler(hub, fallback, cfg.MaxConcurrentGenerations, cfg.QueueMaxDepth, metrics)

	var rec *chat.Recorder
	if cfg.RecordSessions {
		if rec, err = chat.NewRecorder(cfg.RecordingsDir); err != nil {
			return err
		}
	}
	orch := chat.NewOrchestrator(sched, registry, metrics, log, chat.Limits{MaxInputChars: cfg.MaxInputChars,
		MaxContextChars: cfg.MaxContextChars, MaxOutputTokens: cfg.MaxOutputTokens, ToolTimeout: cfg.ToolTimeout}, rec)

	bg, cancelBG := context.WithCancel(context.Background())
	defer cancelBG()
	go probeFallback(bg, fbClient, &fbHealthy, fbConcurrency > 0, sched.Refresh, log)
	if !cfg.DisableSymbolFetch {
		go dir.RefreshLoop(bg, cfg.SymbolsRefresh)
	}
	go purgeCache(bg, st, log)

	hardStop, forceStop := context.WithCancel(context.Background())
	defer forceStop()
	srv := httpapi.New(httpapi.Deps{Config: cfg, Log: log, Metrics: metrics, Store: st, Market: svc, Tools: registry,
		Orchestrator: orch, Hub: hub, Fallback: fallback, Version: version, Commit: commit}, hardStop)

	public := &http.Server{Addr: cfg.Addr, Handler: srv.Public(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 120 * time.Second,
		MaxHeaderBytes: 32 << 10, ErrorLog: slog.NewLogLogger(log.Handler(), slog.LevelWarn)}
	internal := &http.Server{Addr: cfg.InternalAddr, Handler: srv.Internal(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 120 * time.Second,
		MaxHeaderBytes: 32 << 10, ErrorLog: slog.NewLogLogger(log.Handler(), slog.LevelWarn)}

	errc := make(chan error, 2)
	for _, s := range []struct {
		name string
		srv  *http.Server
	}{{"public", public}, {"internal", internal}} {
		ln, err := (&net.ListenConfig{}).Listen(ctx, "tcp", s.srv.Addr)
		if err != nil {
			return fmt.Errorf("%s listener: %w", s.name, err)
		}
		log.Info("listening", "listener", s.name, "addr", ln.Addr().String())
		go func() {
			if err := s.srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
				errc <- fmt.Errorf("%s: %w", s.name, err)
			}
		}()
	}

	select {
	case <-ctx.Done():
		log.Info("shutdown requested; draining")
	case err := <-errc:
		log.Error("listener failed", "err", err)
	}

	srv.SetDraining()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	hub.Drain(shutdownCtx)
	done := make(chan struct{})
	go func() { orch.Wait(); close(done) }()
	select {
	case <-done:
		log.Info("active chats drained")
	case <-shutdownCtx.Done():
		log.Warn("drain timeout; cancelling remaining chats")
		forceStop()
		<-done
	}
	_ = public.Shutdown(shutdownCtx)
	_ = internal.Shutdown(shutdownCtx)
	hub.Close()
	cancelBG()
	log.Info("gateway stopped")
	return nil
}

func probeFallback(ctx context.Context, c *openai.Client, healthy *atomic.Bool, enabled bool, onChange func(), log *slog.Logger) {
	if !enabled {
		return
	}
	check := func() {
		err := c.Ping(ctx)
		was := healthy.Swap(err == nil)
		if was != (err == nil) {
			if err != nil {
				log.Warn("fallback upstream unhealthy", "err", err)
			} else {
				log.Info("fallback upstream healthy")
			}
			onChange()
		}
	}
	check()
	t := time.NewTicker(10 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			check()
		}
	}
}

func purgeCache(ctx context.Context, st *store.Store, log *slog.Logger) {
	t := time.NewTicker(30 * time.Minute)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if n, err := st.Q.PurgeCache(ctx, time.Now().Unix()); err != nil {
				log.Warn("cache purge failed", "err", err)
			} else if n > 0 {
				log.Debug("cache purged", "rows", n)
			}
		}
	}
}
