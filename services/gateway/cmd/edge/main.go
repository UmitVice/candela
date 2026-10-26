// Command edge makes Candela live from the owner's Mac: it supervises the gateway, the
// MLX worker and a Cloudflare quick tunnel, each under its Seatbelt profile, publishes
// the endpoint document to the discovery Gist and closes the tunnel on sustained abuse.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

func main() {
	cmd := "run"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	var err error
	switch cmd {
	case "run":
		err = run()
	case "init":
		var cfg *config
		if cfg, err = loadConfig(); err == nil {
			err = createGist(context.Background(), cfg)
		}
	case "status":
		err = status()
	default:
		err = fmt.Errorf("usage: edge [run|init|status]")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "edge:", err)
		os.Exit(1)
	}
}

type state struct {
	State      string         `json:"state"`
	GatewayURL string         `json:"gatewayUrl,omitempty"`
	Since      string         `json:"since"`
	Supervisor int            `json:"supervisorPid"`
	Pids       map[string]int `json:"pids"`
	Trips      int            `json:"killSwitchTrips"`
	Reason     string         `json:"reason,omitempty"`
	Until      string         `json:"until,omitempty"`
}

type edge struct {
	cfg     *config
	log     *slog.Logger
	pub     *publisher
	gateway *child
	worker  *child
	tunnel  *child
	kill    *killSwitch
	http    *http.Client

	mu    sync.Mutex
	st    state
	trips []time.Time
}

func run() error {
	cfg, err := loadConfig()
	if err != nil {
		return err
	}
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	for _, d := range []string{cfg.LogDir, cfg.StateDir, cfg.liveDir(), filepath.Join(cfg.StateDir, "tmp", "worker"),
		filepath.Join(cfg.StateDir, "cloudflared-home"), cfg.LeaseDir} {
		if err := os.MkdirAll(d, 0o700); err != nil {
			return err
		}
	}
	unlock, err := lockInstance(filepath.Join(cfg.StateDir, "edge.lock"))
	if err != nil {
		return err
	}
	defer unlock()

	e := &edge{cfg: cfg, log: log, kill: newKillSwitch(cfg), http: &http.Client{Timeout: 10 * time.Second},
		st: state{Supervisor: os.Getpid(), Pids: map[string]int{}}}
	e.pub = &publisher{gh: cfg.GH, home: cfg.home, enabled: cfg.Publish && cfg.Tunnel}
	if e.pub.enabled {
		if e.pub.conf, err = readEndpointConfig(cfg.EndpointConf); err != nil {
			return fmt.Errorf("%w (run make live-init)", err)
		}
	}
	if err := e.buildChildren(); err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	e.setState("starting", "", "")
	log.Info("edge starting", "sandbox", cfg.Sandbox, "tunnel", cfg.Tunnel, "publish", e.pub.enabled, "worker", cfg.Worker)

	svcCtx, stopSvc := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	wg.Go(func() { e.gateway.supervise(svcCtx) })
	if cfg.Worker {
		wg.Go(func() { e.worker.supervise(svcCtx) })
	}
	go e.trackPids(svcCtx)

	if err := e.waitLocal(ctx, "/healthz", 30*time.Second); err != nil {
		log.Error("gateway did not become healthy", "err", err)
	} else if err := e.waitLocal(ctx, "/readyz", 60*time.Second); err != nil {
		log.Warn("gateway not ready yet (no model route); continuing", "err", err)
	}
	if cfg.Tunnel && ctx.Err() == nil {
		e.tunnelLoop(ctx)
	} else {
		e.setState("local", "", "")
		<-ctx.Done()
	}

	log.Info("shutdown requested")
	e.setState("stopping", "", "")
	if e.pub.enabled {
		pctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		if err := e.pub.publishRetry(pctx, newDocument("", time.Now(), time.Time{}), 25*time.Second); err != nil {
			log.Error("publishing offline failed", "err", err)
		} else {
			log.Info("published offline")
		}
		cancel()
	}
	stopSvc()
	wg.Wait()
	e.setState("stopped", "", "")
	log.Info("edge stopped")
	return nil
}

func lockInstance(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600) //nolint:gosec // supervisor state directory
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		return nil, errors.New("another edge supervisor is running")
	}
	return func() { _ = f.Close() }, nil
}

func (e *edge) setState(s, url, reason string) {
	e.mu.Lock()
	e.st.State, e.st.GatewayURL, e.st.Reason = s, url, reason
	e.st.Since = time.Now().UTC().Format(time.RFC3339)
	if s != "cooldown" {
		e.st.Until = ""
	}
	e.mu.Unlock()
	e.writeState()
}

func (e *edge) writeState() {
	e.mu.Lock()
	e.st.Pids = map[string]int{"gateway": e.gateway.pid(), "worker": e.worker.pid(), "cloudflared": e.tunnel.pid()}
	b, _ := json.MarshalIndent(e.st, "", "  ")
	e.mu.Unlock()
	path := filepath.Join(e.cfg.StateDir, "state.json")
	if err := os.WriteFile(path+".tmp", append(b, '\n'), 0o600); err == nil {
		_ = os.Rename(path+".tmp", path)
	}
}

func (e *edge) trackPids(ctx context.Context) {
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			e.writeState()
		}
	}
}

func (e *edge) get(ctx context.Context, url string) (int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := e.http.Do(req)
	if err != nil {
		return 0, err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	_ = resp.Body.Close()
	return resp.StatusCode, nil
}

func (e *edge) waitURL(ctx context.Context, url string, within time.Duration) error {
	deadline := time.Now().Add(within)
	var last error
	for time.Now().Before(deadline) {
		code, err := e.get(ctx, url)
		if err == nil && code == http.StatusOK {
			return nil
		}
		last = err
		if err == nil {
			last = fmt.Errorf("HTTP %d", code)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	return fmt.Errorf("%s not ready: %w", url, last)
}

func (e *edge) waitLocal(ctx context.Context, path string, within time.Duration) error {
	return e.waitURL(ctx, "http://"+publicAddr+path, within)
}

func (e *edge) quickTunnelHost(ctx context.Context) (string, error) {
	deadline := time.Now().Add(45 * time.Second)
	for time.Now().Before(deadline) {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+tunnelMetrics+"/quicktunnel", nil)
		if resp, err := e.http.Do(req); err == nil {
			var body struct {
				Hostname string `json:"hostname"`
			}
			err = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&body)
			_ = resp.Body.Close()
			if err == nil && tunnelHostRE.MatchString(body.Hostname) {
				return body.Hostname, nil
			}
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(time.Second):
		}
	}
	return "", errors.New("no quick-tunnel hostname")
}

type tunnelEnd int

const (
	endShutdown tunnelEnd = iota
	endRestart
	endKill
)

// tunnelLoop owns the public exposure: one cloudflared session at a time, each with a new
// hostname, published only after /readyz answers through the tunnel.
func (e *edge) tunnelLoop(ctx context.Context) {
	backoff := 5 * time.Second
	for ctx.Err() == nil {
		began := time.Now()
		end, reason := e.tunnelSession(ctx)
		switch end {
		case endShutdown:
			return
		case endKill:
			if !e.cooldown(ctx, reason) {
				return
			}
			backoff = 5 * time.Second
			continue
		}
		if time.Since(began) > stableAfter {
			backoff = 5 * time.Second
		}
		e.log.Warn("tunnel session ended; reconnecting", "reason", reason, "in", backoff.String())
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, 2*time.Minute)
	}
}

func (e *edge) tunnelSession(ctx context.Context) (tunnelEnd, string) {
	tctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var exitErr error
	exited := make(chan struct{})
	go func() { exitErr = e.tunnel.run(tctx); close(exited) }()
	defer func() { cancel(); <-exited }()

	host, err := e.quickTunnelHost(tctx)
	if err != nil {
		return e.ended(ctx, endRestart, err.Error())
	}
	url := "https://" + host
	e.setState("connecting", url, "")
	if err := e.waitURL(tctx, url+"/readyz", 2*time.Minute); err != nil {
		return e.ended(ctx, endRestart, "tunnel readiness: "+err.Error())
	}
	if err := e.pub.publishRetry(tctx, newDocument(host, time.Now(), time.Now()), 2*time.Minute); err != nil {
		return e.ended(ctx, endRestart, "publish online: "+err.Error())
	}
	e.setState("online", url, "")
	e.log.Info("online", "gatewayUrl", url, "published", e.pub.enabled)
	e.kill.reset()

	heartbeat := time.NewTicker(e.cfg.Heartbeat)
	defer heartbeat.Stop()
	probe := time.NewTicker(time.Minute)
	defer probe.Stop()
	scrape := time.NewTicker(scrapeEvery)
	defer scrape.Stop()
	failures := 0
	for {
		select {
		case <-ctx.Done():
			return endShutdown, "shutdown"
		case <-exited:
			return e.ended(ctx, endRestart, "cloudflared exited: "+errString(exitErr))
		case <-heartbeat.C:
			if err := e.pub.publishRetry(tctx, newDocument(host, time.Now(), time.Now()), time.Minute); err != nil {
				e.log.Warn("heartbeat publish failed", "err", err)
			}
		case <-probe.C:
			if code, err := e.get(tctx, url+"/healthz"); err != nil || code != http.StatusOK {
				failures++
				e.log.Warn("tunnel probe failed", "failures", failures, "code", code, "err", errString(err))
				if failures >= 3 {
					return e.ended(ctx, endRestart, "tunnel unreachable")
				}
			} else {
				failures = 0
			}
		case <-scrape.C:
			counts, err := e.kill.scrape(tctx)
			if err != nil {
				e.log.Warn("abuse metrics unavailable", "err", err)
				continue
			}
			if kind, n := e.kill.observe(time.Now(), counts); kind != "" {
				e.log.Error("kill switch tripped; closing the tunnel", "kind", kind, "count", n, "window", e.cfg.KillWindow.String())
				return e.ended(ctx, endKill, fmt.Sprintf("%s: %.0f in %s", kind, n, e.cfg.KillWindow))
			}
		}
	}
}

// ended publishes offline before the tunnel closes, so visitors switch to replay at once.
func (e *edge) ended(ctx context.Context, end tunnelEnd, reason string) (tunnelEnd, string) {
	if ctx.Err() != nil {
		return endShutdown, "shutdown"
	}
	e.setState("offline", "", reason)
	if err := e.pub.publishRetry(ctx, newDocument("", time.Now(), time.Time{}), time.Minute); err != nil {
		e.log.Error("publishing offline failed", "err", err)
	}
	return end, reason
}

// cooldown keeps the tunnel closed after a kill-switch trip. After too many trips in six
// hours the edge stays offline until the operator restarts it.
func (e *edge) cooldown(ctx context.Context, reason string) bool {
	now := time.Now()
	e.mu.Lock()
	kept := e.trips[:0]
	for _, t := range e.trips {
		if now.Sub(t) < 6*time.Hour {
			kept = append(kept, t)
		}
	}
	e.trips = append(kept, now)
	e.st.Trips++
	tooMany := len(e.trips) >= e.cfg.KillMaxTrips
	e.mu.Unlock()
	if tooMany {
		e.setState("halted", "", "kill switch tripped "+fmt.Sprint(e.cfg.KillMaxTrips)+" times in 6h ("+reason+"); restart with make live-down && make live-up")
		e.log.Error("kill switch halted the public edge until a manual restart")
		<-ctx.Done()
		return false
	}
	until := now.Add(e.cfg.KillCooldown)
	e.setState("cooldown", "", reason)
	e.mu.Lock()
	e.st.Until = until.UTC().Format(time.RFC3339)
	e.mu.Unlock()
	e.writeState()
	e.log.Warn("tunnel closed by the kill switch", "until", e.st.Until)
	select {
	case <-ctx.Done():
		return false
	case <-time.After(time.Until(until)):
		return true
	}
}

func (e *edge) buildChildren() error {
	cfg := e.cfg
	gwEnv := map[string]string{}
	wkEnv := map[string]string{}
	for _, kv := range os.Environ() {
		k, v, _ := strings.Cut(kv, "=")
		switch {
		case strings.HasPrefix(k, "CANDELA_EDGE_"):
		case strings.HasPrefix(k, "CANDELA_WORKER_") && k != "CANDELA_WORKER_TOKEN", strings.HasPrefix(k, "CANDELA_PRO_"):
			wkEnv[k] = v
		case strings.HasPrefix(k, "CANDELA_"):
			gwEnv[k] = v
		}
	}
	live := cfg.liveDir()
	snapshot := filepath.Join(cfg.gatewayDir(), "data/market.sqlite")
	for k, v := range map[string]string{
		"HOME": live, "TMPDIR": live, "GOMAXPROCS": "4",
		"CANDELA_ENV": "production", "CANDELA_ADDR": publicAddr, "CANDELA_INTERNAL_ADDR": internalAddr,
		"CANDELA_TRUSTED_PROXY": "cloudflare", "CANDELA_TRUSTED_PROXY_CIDRS": "127.0.0.1/32,::1/128",
		"CANDELA_WORKER_ON_PUBLIC": "false", "CANDELA_FALLBACK_ENABLED": "false",
		"CANDELA_DB_PATH": filepath.Join(live, "gateway.sqlite"), "CANDELA_SNAPSHOT_PATH": snapshot, "CANDELA_SNAPSHOT_URL": "",
		"CANDELA_RECORDINGS_DIR": filepath.Join(live, "recordings"), "CANDELA_SPARK_STATUS_PATH": cfg.SparkStatus,
		"CANDELA_WORKER_TOKEN": cfg.WorkerToken, "CANDELA_METRICS_TOKEN": cfg.MetricsToken,
	} {
		gwEnv[k] = v
	}
	if _, ok := gwEnv["CANDELA_ALLOWED_ORIGINS"]; !ok {
		gwEnv["CANDELA_ALLOWED_ORIGINS"] = "https://candela-terminal.netlify.app,http://localhost:4200"
	}
	tmp := filepath.Join(cfg.StateDir, "tmp", "worker")
	for k, v := range map[string]string{
		"HOME": cfg.home, "TMPDIR": tmp, "CANDELA_ENV": "production", "CANDELA_REPO_ROOT": cfg.Repo,
		"CANDELA_WORKER_URL": "ws://" + internalAddr + "/api/v1/worker/connect", "CANDELA_WORKER_TOKEN": cfg.WorkerToken,
		"CANDELA_LEASE_DIR": cfg.LeaseDir, "CANDELA_LOG_LEVEL": gwEnv["CANDELA_LOG_LEVEL"],
		"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
		"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "TOKENIZERS_PARALLELISM": "false",
	} {
		if v != "" {
			wkEnv[k] = v
		}
	}

	gwBin := filepath.Join(cfg.gatewayDir(), "bin/gateway")
	e.gateway = &child{name: "gateway", bin: gwBin, env: gwEnv, dir: cfg.Repo, stopIn: 45 * time.Second,
		logPath: filepath.Join(cfg.LogDir, "gateway.log"), log: e.log}
	venvPython := filepath.Join(cfg.workerDir(), ".venv/bin/python")
	e.worker = &child{name: "worker", bin: venvPython, args: []string{"-m", "candela_worker.cli", "connect"}, env: wkEnv,
		dir: cfg.workerDir(), stopIn: 160 * time.Second, logPath: filepath.Join(cfg.LogDir, "worker.log"), log: e.log}
	cfBin, err := filepath.EvalSymlinks(cfg.Cloudflared)
	if err != nil {
		return err
	}
	e.tunnel = &child{name: "cloudflared", bin: cfBin, dir: filepath.Join(cfg.StateDir, "cloudflared-home"), stopIn: 10 * time.Second,
		args: []string{"tunnel", "--no-autoupdate", "--protocol", "http2", "--url", "http://" + publicAddr,
			"--metrics", tunnelMetrics, "--loglevel", "info"},
		env:     map[string]string{"HOME": filepath.Join(cfg.StateDir, "cloudflared-home")},
		logPath: filepath.Join(cfg.LogDir, "cloudflared.log"), log: e.log}
	if !cfg.Sandbox {
		return nil
	}

	for _, n := range []string{"gateway", "worker", "cloudflared"} {
		if _, err := os.Stat(cfg.profile(n)); err != nil {
			return fmt.Errorf("sandbox profile missing: %s", n)
		}
	}
	real := func(p string) string {
		if r, err := filepath.EvalSymlinks(p); err == nil {
			return r
		}
		return p
	}
	e.gateway.profile = cfg.profile("gateway")
	e.gateway.params = map[string]string{"BIN": real(gwBin), "SNAPSHOT": real(snapshot), "STATE_DIR": real(live),
		"SPARK_STATUS": real(cfg.SparkStatus), "HOME": cfg.home}

	python := real(venvPython)
	pyHome := filepath.Dir(python)
	for i := 0; i < 8 && filepath.Base(pyHome) != "Frameworks" && filepath.Dir(pyHome) != pyHome; i++ {
		pyHome = filepath.Dir(pyHome)
	}
	if filepath.Base(pyHome) == "Frameworks" {
		pyHome = filepath.Dir(pyHome)
	} else {
		pyHome = filepath.Dir(filepath.Dir(python))
	}
	userCache, err := darwinUserCacheDir(context.Background())
	if err != nil {
		return err
	}
	e.worker.profile = cfg.profile("worker")
	pyApp := python
	if app := filepath.Join(filepath.Dir(filepath.Dir(python)), "Resources/Python.app/Contents/MacOS/Python"); fileExists(app) {
		pyApp = app
	}
	e.worker.params = map[string]string{"PYTHON": python, "PYTHON_APP": pyApp, "PYTHON_HOME": pyHome, "VENV": real(filepath.Join(cfg.workerDir(), ".venv")),
		"WORKER_DIR": cfg.workerDir(), "MODELS_CONFIG": filepath.Join(cfg.Repo, "ml/configs/models.yaml"),
		"LEASE_DIR": real(cfg.LeaseDir), "TMP_DIR": real(tmp), "USER_CACHE": userCache, "HOME": cfg.home}
	for i := range 6 {
		p := "/nonexistent/candela"
		if i < len(cfg.WorkerRead) {
			p = real(cfg.WorkerRead[i])
		}
		e.worker.params[fmt.Sprintf("READ_%d", i)] = p
	}

	e.tunnel.profile = cfg.profile("cloudflared")
	e.tunnel.params = map[string]string{"BIN": cfBin, "HOME": cfg.home}
	return nil
}

// darwinUserCacheDir is the per-user cache directory where Metal keeps its shader cache.
func darwinUserCacheDir(ctx context.Context) (string, error) {
	out, err := exec.CommandContext(ctx, "/usr/bin/getconf", "DARWIN_USER_CACHE_DIR").Output()
	if err != nil {
		return "", fmt.Errorf("getconf DARWIN_USER_CACHE_DIR: %w", err)
	}
	r, err := filepath.EvalSymlinks(strings.TrimSpace(string(out)))
	if err != nil {
		return "", err
	}
	return r + "/", nil
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
