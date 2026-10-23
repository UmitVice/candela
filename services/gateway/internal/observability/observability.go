package observability

import (
	"log/slog"
	"os"
	"strings"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
)

func NewLogger(level string) *slog.Logger {
	var l slog.Level
	switch strings.ToLower(level) {
	case "debug":
		l = slog.LevelDebug
	case "warn":
		l = slog.LevelWarn
	case "error":
		l = slog.LevelError
	default:
		l = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: l}))
}

type Metrics struct {
	Registry *prometheus.Registry

	HTTPRequests  *prometheus.CounterVec
	HTTPDuration  *prometheus.HistogramVec
	ChatRequests  *prometheus.CounterVec
	TTFT          *prometheus.HistogramVec
	TokensPerSec  *prometheus.HistogramVec
	QueueDepth    prometheus.Gauge
	ActiveChats   prometheus.Gauge
	Workers       prometheus.Gauge
	ToolDuration  *prometheus.HistogramVec
	ToolErrors    *prometheus.CounterVec
	RateLimited   *prometheus.CounterVec
	UpstreamRetry prometheus.Counter
}

func NewMetrics() *Metrics {
	r := prometheus.NewRegistry()
	r.MustRegister(collectors.NewGoCollector(), collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}))
	m := &Metrics{
		Registry: r,
		HTTPRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "candela_http_requests_total", Help: "HTTP requests by listener, route and status class.",
		}, []string{"listener", "route", "method", "status"}),
		HTTPDuration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name: "candela_http_request_duration_seconds", Help: "HTTP request latency (streams excluded).",
			Buckets: prometheus.DefBuckets,
		}, []string{"listener", "route"}),
		ChatRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "candela_chat_requests_total", Help: "Chat requests by route, transport and outcome.",
		}, []string{"route", "transport", "outcome"}),
		TTFT: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name: "candela_chat_ttft_seconds", Help: "Time to first generated token.",
			Buckets: []float64{0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32},
		}, []string{"route"}),
		TokensPerSec: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name: "candela_chat_tokens_per_second", Help: "Generation throughput per chat request.",
			Buckets: []float64{2, 5, 10, 20, 30, 50, 80, 120, 200},
		}, []string{"route"}),
		QueueDepth: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "candela_queue_depth", Help: "Chat requests waiting for a generation slot.",
		}),
		ActiveChats: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "candela_active_chats", Help: "Chat requests currently streaming.",
		}),
		Workers: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "candela_workers_connected", Help: "Inference workers connected to the hub.",
		}),
		ToolDuration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name: "candela_tool_duration_seconds", Help: "Tool execution latency.",
			Buckets: []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8},
		}, []string{"tool"}),
		ToolErrors: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "candela_tool_errors_total", Help: "Tool executions that returned an error view.",
		}, []string{"tool", "code"}),
		RateLimited: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "candela_rate_limited_total", Help: "Requests rejected by the rate limiter.",
		}, []string{"bucket"}),
		UpstreamRetry: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "candela_upstream_fallback_retries_total", Help: "Generations retried on the fallback after a worker failure.",
		}),
	}
	r.MustRegister(m.HTTPRequests, m.HTTPDuration, m.ChatRequests, m.TTFT, m.TokensPerSec, m.QueueDepth,
		m.ActiveChats, m.Workers, m.ToolDuration, m.ToolErrors, m.RateLimited, m.UpstreamRetry)
	return m
}
