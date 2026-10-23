package httpapi

import (
	"context"
	"crypto/subtle"
	"log/slog"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/UmitVice/candela/services/gateway/api"
	"github.com/UmitVice/candela/services/gateway/internal/chat"
	"github.com/UmitVice/candela/services/gateway/internal/config"
	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/market"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
	"github.com/UmitVice/candela/services/gateway/internal/ratelimit"
	"github.com/UmitVice/candela/services/gateway/internal/store"
	"github.com/UmitVice/candela/services/gateway/internal/tools"
	"github.com/UmitVice/candela/services/gateway/internal/workerhub"
)

type Deps struct {
	Config       *config.Config
	Log          *slog.Logger
	Metrics      *observability.Metrics
	Store        *store.Store
	Market       *market.Service
	Tools        *tools.Registry
	Orchestrator *chat.Orchestrator
	Hub          *workerhub.Hub
	Fallback     *chat.Fallback
	Version      string
	Commit       string
}

type Server struct {
	Deps
	cfg      *config.Config
	log      *slog.Logger
	metrics  *observability.Metrics
	chatRL   *ratelimit.Limiter
	marketRL *ratelimit.Limiter
	feedRL   *ratelimit.Limiter
	draining atomic.Bool
	hardStop context.Context
}

func New(d Deps, hardStop context.Context) *Server {
	c := d.Config
	return &Server{Deps: d, cfg: c, log: d.Log, metrics: d.Metrics, hardStop: hardStop,
		chatRL:   ratelimit.New("chat", c.ChatRatePerMin, c.ChatBurst, 8192),
		marketRL: ratelimit.New("market", c.MarketRatePerMin, c.MarketBurst, 8192),
		feedRL:   ratelimit.New("feedback", c.FeedbackRatePerMin, c.FeedbackBurst, 8192),
	}
}

func (s *Server) SetDraining() { s.draining.Store(true) }

func (s *Server) common(r chi.Router, listener string) {
	r.Use(withRequestID, withClientIP(ipResolver{mode: s.cfg.TrustedProxy, prefixes: s.cfg.ProxyPrefixes()}),
		withAccessLog(listener, s.log, s.metrics), withRecover(s.log), withSecurityHeaders)
	r.NotFound(func(w http.ResponseWriter, r *http.Request) {
		writeError(w, r, http.StatusNotFound, "not_found", "no such route", 0)
	})
	r.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		writeError(w, r, http.StatusMethodNotAllowed, "invalid_request", "method not allowed", 0)
	})
	r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	r.Get("/readyz", s.readyz)
}

func (s *Server) Public() http.Handler {
	r := chi.NewRouter()
	s.common(r, "public")
	r.Use(withCORS(s.cfg.AllowedOrigins))
	r.Route("/api/v1", func(r chi.Router) {
		r.Group(func(r chi.Router) {
			r.Use(withDeadline(10*time.Second), middleware.Compress(5, "application/json"))
			r.Get("/status", s.status)
			r.Get("/models", s.models)
			r.Get("/openapi.yaml", func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/yaml; charset=utf-8")
				w.Header().Set("Cache-Control", "public, max-age=3600")
				_, _ = w.Write(api.OpenAPI)
			})
			r.Route("/market", func(r chi.Router) {
				r.Use(s.limit(s.marketRL))
				r.Get("/search", s.marketSearch)
				r.Get("/{symbol}/quote", s.marketQuote)
				r.Get("/{symbol}/history", s.marketHistory)
				r.Get("/{symbol}/indicators", s.marketIndicators)
				r.Get("/{symbol}/fundamentals", s.marketFundamentals)
				r.Get("/{symbol}/forecast", s.marketForecast)
			})
			r.With(s.limit(s.feedRL), withBodyLimit(32<<10)).Post("/feedback", s.feedback)
		})
		r.With(s.limit(s.chatRL), withBodyLimit(64<<10)).Post("/chat/stream", s.chatStream)
		r.With(s.limit(s.chatRL)).Get("/chat/ws", s.chatWS)
		if s.cfg.WorkerOnPublic {
			r.Get("/worker/connect", s.Hub.ServeHTTP)
		}
	})
	return r
}

func (s *Server) Internal() http.Handler {
	r := chi.NewRouter()
	s.common(r, "internal")
	r.Get("/metrics", s.metricsHandler())
	if !s.cfg.WorkerOnPublic {
		r.Get("/api/v1/worker/connect", s.Hub.ServeHTTP)
	}
	r.Route("/internal/v1", func(r chi.Router) {
		r.Use(withBodyLimit(64 << 10))
		r.With(withDeadline(15*time.Second)).Post("/tools/execute", s.toolsExecute)
		r.Get("/tools", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(s.Tools.Definitions())
		})
		r.Get("/system-prompt", s.systemPrompt)
	})
	return r
}

func (s *Server) metricsHandler() http.HandlerFunc {
	h := promhttp.HandlerFor(s.metrics.Registry, promhttp.HandlerOpts{})
	return func(w http.ResponseWriter, r *http.Request) {
		token := []byte(s.cfg.MetricsToken)
		got, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
		if len(token) == 0 || !ok || subtle.ConstantTimeCompare([]byte(got), token) != 1 {
			w.Header().Set("WWW-Authenticate", `Bearer realm="metrics"`)
			writeError(w, r, http.StatusUnauthorized, "unauthorized", "metrics require a bearer token", 0)
			return
		}
		h.ServeHTTP(w, r)
	}
}

type modelEntry struct {
	llm.ModelInfo
	Available bool `json:"available"`
}

func (s *Server) modelList() []modelEntry {
	avail := s.Orchestrator.Scheduler().Models()
	seen := map[string]bool{}
	var out []modelEntry
	for _, m := range avail {
		seen[m.ID] = true
		out = append(out, modelEntry{ModelInfo: m, Available: true})
	}
	if s.Fallback != nil && !seen[s.Fallback.Model.ID] {
		out = append(out, modelEntry{ModelInfo: s.Fallback.Model, Available: false})
	}
	return out
}

func (s *Server) models(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{"models": s.modelList()})
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	sched := s.Orchestrator.Scheduler()
	route := sched.Route()
	if s.draining.Load() {
		route = "unavailable"
	}
	status := "ok"
	providers := s.Market.Providers()
	if route == "unavailable" || !s.Market.Ready() {
		status = "degraded"
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{
		"status": status, "version": s.Version, "commit": s.Commit, "route": route,
		"models": s.modelList(), "workers": s.Hub.Status(),
		"queue":         map[string]int{"depth": sched.QueueDepth(), "maxDepth": sched.MaxDepth()},
		"dataProviders": providers,
		"time":          time.Now().UTC().Format(time.RFC3339),
	})
}

func (s *Server) readyz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	checks := map[string]bool{
		"storage":  s.Store.Ping(ctx) == nil,
		"snapshot": s.Market.Ready(),
		"model":    s.Orchestrator.Scheduler().Route() != "unavailable",
		"serving":  !s.draining.Load(),
	}
	code, status := http.StatusOK, "ready"
	if !checks["storage"] || !checks["model"] || !checks["serving"] {
		code, status = http.StatusServiceUnavailable, "not_ready"
	}
	writeJSON(w, code, map[string]any{"status": status, "checks": checks})
}
