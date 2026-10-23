package config

import (
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/netip"
	"net/url"
	"strings"
	"time"

	"github.com/caarlos0/env/v11"
)

type Config struct {
	Addr         string `env:"CANDELA_ADDR" envDefault:"127.0.0.1:8710"`
	Port         string `env:"PORT"`
	InternalAddr string `env:"CANDELA_INTERNAL_ADDR" envDefault:"127.0.0.1:8719"`
	LogLevel     string `env:"CANDELA_LOG_LEVEL" envDefault:"info"`
	Environment  string `env:"CANDELA_ENV" envDefault:"development"`

	DBPath       string `env:"CANDELA_DB_PATH" envDefault:"services/gateway/data/gateway.sqlite"`
	SnapshotPath string `env:"CANDELA_SNAPSHOT_PATH" envDefault:"services/gateway/data/market.sqlite"`
	SnapshotURL  string `env:"CANDELA_SNAPSHOT_URL"`

	AllowedOrigins    []string `env:"CANDELA_ALLOWED_ORIGINS" envSeparator:"," envDefault:"http://localhost:4200,https://candela-terminal.netlify.app"`
	TrustedProxy      string   `env:"CANDELA_TRUSTED_PROXY"`
	TrustedProxyCIDRs []string `env:"CANDELA_TRUSTED_PROXY_CIDRS" envSeparator:"," envDefault:"127.0.0.1/32,::1/128"`

	WorkerToken    string `env:"CANDELA_WORKER_TOKEN"`
	WorkerOnPublic bool   `env:"CANDELA_WORKER_ON_PUBLIC" envDefault:"false"`
	MetricsToken   string `env:"CANDELA_METRICS_TOKEN"`

	FallbackURL         string        `env:"CANDELA_FALLBACK_URL" envDefault:"http://127.0.0.1:8712/v1"`
	FallbackAPIKey      string        `env:"CANDELA_FALLBACK_API_KEY"`
	FallbackModel       string        `env:"CANDELA_FALLBACK_MODEL" envDefault:"qwen3-1.7b"`
	FallbackModelID     string        `env:"CANDELA_FALLBACK_MODEL_ID" envDefault:"qwen3-1.7b-base"`
	FallbackModelJSON   string        `env:"CANDELA_FALLBACK_MODEL_INFO"`
	FallbackConcurrency int           `env:"CANDELA_FALLBACK_CONCURRENCY" envDefault:"1"`
	FallbackTimeout     time.Duration `env:"CANDELA_FALLBACK_TIMEOUT" envDefault:"120s"`

	MaxConcurrentGenerations int           `env:"CANDELA_MAX_CONCURRENT_GENERATIONS" envDefault:"0"`
	QueueMaxDepth            int           `env:"CANDELA_QUEUE_MAX_DEPTH" envDefault:"16"`
	ChatTimeout              time.Duration `env:"CANDELA_CHAT_TIMEOUT" envDefault:"300s"`
	ToolTimeout              time.Duration `env:"CANDELA_TOOL_TIMEOUT" envDefault:"8s"`
	ShutdownTimeout          time.Duration `env:"CANDELA_SHUTDOWN_TIMEOUT" envDefault:"30s"`

	ChatRatePerMin     float64 `env:"CANDELA_RATE_CHAT_PER_MIN" envDefault:"6"`
	ChatBurst          int     `env:"CANDELA_RATE_CHAT_BURST" envDefault:"3"`
	MarketRatePerMin   float64 `env:"CANDELA_RATE_MARKET_PER_MIN" envDefault:"60"`
	MarketBurst        int     `env:"CANDELA_RATE_MARKET_BURST" envDefault:"20"`
	FeedbackRatePerMin float64 `env:"CANDELA_RATE_FEEDBACK_PER_MIN" envDefault:"20"`
	FeedbackBurst      int     `env:"CANDELA_RATE_FEEDBACK_BURST" envDefault:"5"`

	SymbolsBaseURL     string        `env:"CANDELA_SYMBOLS_BASE_URL" envDefault:"https://www.nasdaqtrader.com/dynamic/SymDir"`
	SymbolsRefresh     time.Duration `env:"CANDELA_SYMBOLS_REFRESH" envDefault:"24h"`
	MarketCacheTTL     time.Duration `env:"CANDELA_MARKET_CACHE_TTL" envDefault:"1h"`
	SECUserAgent       string        `env:"SEC_USER_AGENT"`
	LiveAPIKey         string        `env:"CANDELA_LIVE_API_KEY"`
	VanirasURL         string        `env:"CANDELA_VANIRAS_URL"`
	RecordSessions     bool          `env:"CANDELA_RECORD_SESSIONS" envDefault:"false"`
	RecordingsDir      string        `env:"CANDELA_RECORDINGS_DIR" envDefault:"services/gateway/data/recordings"`
	DisableSymbolFetch bool          `env:"CANDELA_DISABLE_SYMBOL_FETCH" envDefault:"false"`

	proxyPrefixes []netip.Prefix
}

func Load() (*Config, error) {
	var c Config
	if err := env.Parse(&c); err != nil {
		return nil, err
	}
	if c.Port != "" {
		c.Addr = net.JoinHostPort("0.0.0.0", c.Port)
	}
	return &c, c.validate()
}

func (c *Config) validate() error {
	var errs []error
	for _, a := range []struct{ name, v string }{{"CANDELA_ADDR", c.Addr}, {"CANDELA_INTERNAL_ADDR", c.InternalAddr}} {
		if _, _, err := net.SplitHostPort(a.v); err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", a.name, err))
		}
	}
	if c.Addr == c.InternalAddr {
		errs = append(errs, errors.New("CANDELA_ADDR and CANDELA_INTERNAL_ADDR must differ"))
	}
	switch c.TrustedProxy {
	case "", "cloudflare", "xff":
	default:
		errs = append(errs, fmt.Errorf("CANDELA_TRUSTED_PROXY: unsupported value %q (use cloudflare, xff or empty)", c.TrustedProxy))
	}
	for _, s := range c.TrustedProxyCIDRs {
		p, err := netip.ParsePrefix(strings.TrimSpace(s))
		if err != nil {
			errs = append(errs, fmt.Errorf("CANDELA_TRUSTED_PROXY_CIDRS: %w", err))
			continue
		}
		c.proxyPrefixes = append(c.proxyPrefixes, p.Masked())
	}
	for _, o := range c.AllowedOrigins {
		u, err := url.Parse(o)
		if err != nil || u.Scheme == "" || u.Host == "" || u.Path != "" {
			errs = append(errs, fmt.Errorf("CANDELA_ALLOWED_ORIGINS: invalid origin %q", o))
		}
	}
	if c.WorkerToken != "" && len(c.WorkerToken) < 43 {
		errs = append(errs, errors.New("CANDELA_WORKER_TOKEN must encode at least 32 random bytes"))
	}
	if c.MetricsToken != "" && len(c.MetricsToken) < 24 {
		errs = append(errs, errors.New("CANDELA_METRICS_TOKEN is too short"))
	}
	if _, err := url.Parse(c.FallbackURL); err != nil {
		errs = append(errs, fmt.Errorf("CANDELA_FALLBACK_URL: %w", err))
	}
	if c.FallbackConcurrency < 0 || c.QueueMaxDepth < 0 || c.MaxConcurrentGenerations < 0 {
		errs = append(errs, errors.New("concurrency and queue limits must not be negative"))
	}
	if c.ChatRatePerMin <= 0 || c.MarketRatePerMin <= 0 || c.FeedbackRatePerMin <= 0 {
		errs = append(errs, errors.New("rate limits must be positive"))
	}
	return errors.Join(errs...)
}

func (c *Config) ProxyPrefixes() []netip.Prefix { return c.proxyPrefixes }

func (c *Config) Production() bool { return c.Environment == "production" }

func (c *Config) LogValue() slog.Value {
	set := func(s string) bool { return s != "" }
	return slog.GroupValue(
		slog.String("addr", c.Addr),
		slog.String("internalAddr", c.InternalAddr),
		slog.String("env", c.Environment),
		slog.String("dbPath", c.DBPath),
		slog.String("snapshotPath", c.SnapshotPath),
		slog.Bool("snapshotURL", set(c.SnapshotURL)),
		slog.Any("allowedOrigins", c.AllowedOrigins),
		slog.String("trustedProxy", c.TrustedProxy),
		slog.Bool("workerToken", set(c.WorkerToken)),
		slog.Bool("workerOnPublic", c.WorkerOnPublic),
		slog.Bool("metricsToken", set(c.MetricsToken)),
		slog.String("fallbackURL", redactURL(c.FallbackURL)),
		slog.String("fallbackModelId", c.FallbackModelID),
		slog.Bool("secUserAgent", set(c.SECUserAgent)),
		slog.Bool("liveApiKey", set(c.LiveAPIKey)),
		slog.Bool("vaniras", set(c.VanirasURL)),
		slog.Int("queueMaxDepth", c.QueueMaxDepth),
		slog.Int("maxConcurrentGenerations", c.MaxConcurrentGenerations),
	)
}

func redactURL(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return "invalid"
	}
	u.User = nil
	u.RawQuery = ""
	return u.String()
}
