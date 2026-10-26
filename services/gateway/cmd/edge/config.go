package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/caarlos0/env/v11"
)

const (
	publicAddr    = "127.0.0.1:8710"
	internalAddr  = "127.0.0.1:8719"
	tunnelMetrics = "127.0.0.1:8717"
	endpointFile  = "candela-endpoint.json"
)

var (
	tunnelHostRE = regexp.MustCompile(`^[a-z0-9-]+\.trycloudflare\.com$`)
	envKeyRE     = regexp.MustCompile(`^[A-Z][A-Z0-9_]*$`)
)

type config struct {
	Repo         string `env:"CANDELA_EDGE_REPO"`
	LogDir       string `env:"CANDELA_EDGE_LOG_DIR" envDefault:"${HOME}/Library/Logs/Candela"`
	StateDir     string `env:"CANDELA_EDGE_STATE_DIR" envDefault:"${HOME}/.candela/edge"`
	EndpointConf string `env:"CANDELA_EDGE_ENDPOINT_CONFIG" envDefault:"deploy/local/endpoint.json"`
	SandboxDir   string `env:"CANDELA_EDGE_SANDBOX_DIR" envDefault:"deploy/sandbox"`
	Cloudflared  string `env:"CANDELA_EDGE_CLOUDFLARED" envDefault:"/opt/homebrew/bin/cloudflared"`
	GH           string `env:"CANDELA_EDGE_GH" envDefault:"/opt/homebrew/bin/gh"`

	Sandbox bool `env:"CANDELA_EDGE_SANDBOX" envDefault:"true"`
	Tunnel  bool `env:"CANDELA_EDGE_TUNNEL" envDefault:"true"`
	Publish bool `env:"CANDELA_EDGE_PUBLISH" envDefault:"true"`
	Worker  bool `env:"CANDELA_EDGE_WORKER" envDefault:"true"`

	WorkerRead  []string `env:"CANDELA_EDGE_WORKER_READ" envSeparator:"," envDefault:"${HOME}/models/gemma-4-12b-it-qat-mlx-q4,ml/runs/candela-pro-v0.1-lr5e5/adapter,ml/runs/pilot-candela-pro/adapter,${HOME}/.cache/huggingface/hub/models--mlx-community--Qwen3-0.6B-4bit,${HOME}/.cache/huggingface/hub/blobs"`
	SparkStatus string   `env:"CANDELA_SPARK_STATUS_PATH" envDefault:"${HOME}/.candela/spark/status.json"`
	LeaseDir    string   `env:"CANDELA_LEASE_DIR" envDefault:"${HOME}/.candela/leases"`

	Heartbeat time.Duration `env:"CANDELA_EDGE_HEARTBEAT" envDefault:"10m"`

	KillWindow      time.Duration `env:"CANDELA_EDGE_KILL_WINDOW" envDefault:"2m"`
	KillCooldown    time.Duration `env:"CANDELA_EDGE_KILL_COOLDOWN" envDefault:"15m"`
	KillMaxTrips    int           `env:"CANDELA_EDGE_KILL_MAX_TRIPS" envDefault:"3"`
	KillRateLimited float64       `env:"CANDELA_EDGE_KILL_RATE_LIMITED" envDefault:"300"`
	KillOversized   float64       `env:"CANDELA_EDGE_KILL_OVERSIZED" envDefault:"30"`
	KillOrigin      float64       `env:"CANDELA_EDGE_KILL_ORIGIN" envDefault:"120"`
	KillProtocol    float64       `env:"CANDELA_EDGE_KILL_PROTOCOL" envDefault:"60"`
	KillInvalid     float64       `env:"CANDELA_EDGE_KILL_INVALID" envDefault:"300"`

	WorkerToken  string `env:"CANDELA_WORKER_TOKEN"`
	MetricsToken string `env:"CANDELA_METRICS_TOKEN"`

	home string
}

// loadDotenv applies deploy/.env without overriding variables already set, so a shell or
// LaunchAgent value wins. The file holds tokens, so it must not be readable by others.
func loadDotenv(path string) error {
	st, err := os.Stat(path) //nolint:gosec // fixed path inside the repository
	if errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	if st.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("%s must not be readable by group or others (chmod 600)", filepath.Base(path))
	}
	b, err := os.ReadFile(path) //nolint:gosec // fixed path inside the repository
	if err != nil {
		return err
	}
	for line := range strings.SplitSeq(string(b), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok || !envKeyRE.MatchString(k) {
			continue
		}
		v = strings.Trim(strings.TrimSpace(v), `"'`)
		if _, set := os.LookupEnv(k); !set {
			if err := os.Setenv(k, v); err != nil {
				return err
			}
		}
	}
	return nil
}

func loadConfig() (*config, error) {
	repo := os.Getenv("CANDELA_EDGE_REPO")
	if repo == "" {
		repo, _ = os.Getwd()
	}
	if err := loadDotenv(filepath.Join(repo, "deploy/.env")); err != nil {
		return nil, err
	}
	var c config
	if err := env.Parse(&c); err != nil {
		return nil, err
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	if c.home, err = filepath.EvalSymlinks(home); err != nil {
		return nil, err
	}
	if c.Repo == "" {
		if c.Repo, err = os.Getwd(); err != nil {
			return nil, err
		}
	}
	if c.Repo, err = filepath.EvalSymlinks(c.Repo); err != nil {
		return nil, err
	}
	for _, p := range []*string{&c.LogDir, &c.StateDir, &c.SparkStatus, &c.LeaseDir} {
		*p = c.abs(expandHome(*p, c.home))
	}
	c.EndpointConf = c.abs(c.EndpointConf)
	c.SandboxDir = c.abs(c.SandboxDir)
	for i, p := range c.WorkerRead {
		c.WorkerRead[i] = c.abs(expandHome(strings.TrimSpace(p), c.home))
	}
	return &c, c.validate()
}

// expandHome resolves ${HOME} and a leading ~ in defaults and operator-supplied paths.
func expandHome(p, home string) string {
	p = strings.ReplaceAll(p, "${HOME}", home)
	if p == "~" || strings.HasPrefix(p, "~/") {
		p = home + p[1:]
	}
	return p
}

func (c *config) abs(p string) string {
	if filepath.IsAbs(p) {
		return filepath.Clean(p)
	}
	return filepath.Join(c.Repo, p)
}

func (c *config) validate() error {
	var errs []error
	if c.Tunnel && !c.Sandbox {
		errs = append(errs, errors.New("refusing to open a public tunnel without the Seatbelt sandboxes (CANDELA_EDGE_SANDBOX=false)"))
	}
	if len(c.WorkerToken) < 43 {
		errs = append(errs, errors.New("CANDELA_WORKER_TOKEN must hold at least 32 random bytes (run make live-init)"))
	}
	if len(c.MetricsToken) < 43 {
		errs = append(errs, errors.New("CANDELA_METRICS_TOKEN must hold at least 32 random bytes (run make live-init)"))
	}
	if len(c.WorkerRead) > 6 {
		errs = append(errs, errors.New("CANDELA_EDGE_WORKER_READ takes at most 6 directories"))
	}
	if c.Heartbeat < time.Minute || c.KillWindow < 30*time.Second || c.KillCooldown < time.Minute || c.KillMaxTrips < 1 {
		errs = append(errs, errors.New("heartbeat >= 1m, kill window >= 30s, cooldown >= 1m and max trips >= 1 are required"))
	}
	for _, p := range []string{filepath.Join(c.Repo, "services/gateway/bin/gateway"), c.Cloudflared, c.GH} {
		if _, err := os.Stat(p); err != nil {
			errs = append(errs, fmt.Errorf("missing executable: %s", filepath.Base(p)))
		}
	}
	return errors.Join(errs...)
}

func (c *config) gatewayDir() string { return filepath.Join(c.Repo, "services/gateway") }
func (c *config) liveDir() string    { return filepath.Join(c.gatewayDir(), "data/live") }
func (c *config) workerDir() string  { return filepath.Join(c.Repo, "services/worker") }
func (c *config) profile(n string) string {
	return filepath.Join(c.SandboxDir, n+".sb")
}
