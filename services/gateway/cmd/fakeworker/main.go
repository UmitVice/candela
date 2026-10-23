// Command fakeworker is a scripted stand-in for the MLX worker: it speaks
// candela.worker.v1 and streams canned reasoning, tool calls and answer tokens so the
// gateway's hub, routing, cancellation and fallback paths can be exercised by hand.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"math/rand/v2"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/coder/websocket"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
)

type options struct {
	url, token, id, model string
	delay                 time.Duration
	crashOnJob, mutePongs bool
	once                  bool
}

func main() {
	var o options
	flag.StringVar(&o.url, "url", envOr("CANDELA_WORKER_URL", "ws://127.0.0.1:8719/api/v1/worker/connect"), "gateway worker endpoint")
	flag.StringVar(&o.id, "id", "fake-worker", "worker id")
	flag.StringVar(&o.model, "model", "candela-fake-pro", "model id to register")
	flag.DurationVar(&o.delay, "delay", 40*time.Millisecond, "delay between streamed tokens")
	flag.BoolVar(&o.crashOnJob, "crash-on-job", false, "drop the connection when a job arrives, before any token")
	flag.BoolVar(&o.mutePongs, "mute-pongs", false, "never answer heartbeat pings")
	flag.BoolVar(&o.once, "once", false, "exit instead of reconnecting")
	flag.Parse()
	o.token = os.Getenv("CANDELA_WORKER_TOKEN")
	log := observability.NewLogger("info").With("worker", o.id)
	if o.token == "" {
		log.Error("CANDELA_WORKER_TOKEN is not set")
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	backoff := time.Second
	for {
		start := time.Now()
		err := session(ctx, o, log)
		if ctx.Err() != nil || o.once {
			log.Info("fake worker exiting", "err", err)
			return
		}
		if time.Since(start) > time.Minute {
			backoff = time.Second
		}
		wait := time.Duration(rand.Int64N(int64(backoff))) //nolint:gosec // jitter only
		log.Warn("disconnected; reconnecting", "err", err, "in", wait.Round(time.Millisecond).String())
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
		backoff = min(backoff*2, time.Minute)
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

type inbound struct {
	Type     string        `json:"type"`
	TS       int64         `json:"ts"`
	JobID    string        `json:"jobId"`
	Messages []wireMessage `json:"messages"`
	Params   llm.Params    `json:"params"`
}

type wireMessage struct {
	Role       string `json:"role"`
	Content    string `json:"content"`
	ToolCallID string `json:"tool_call_id"`
}

type conn struct {
	c  *websocket.Conn
	mu sync.Mutex
}

func (c *conn) send(ctx context.Context, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.c.Write(ctx, websocket.MessageText, b)
}

func session(ctx context.Context, o options, log *slog.Logger) error {
	dctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	ws, resp, err := websocket.Dial(dctx, o.url, &websocket.DialOptions{
		Subprotocols: []string{"candela.worker.v1"},
		HTTPHeader:   http.Header{"Authorization": {"Bearer " + o.token}},
	})
	cancel()
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err != nil {
		if resp != nil {
			return fmt.Errorf("dial: HTTP %d", resp.StatusCode)
		}
		return fmt.Errorf("dial: %w", err)
	}
	defer func() { _ = ws.CloseNow() }()
	ws.SetReadLimit(1 << 20)
	c := &conn{c: ws}
	model := llm.ModelInfo{ID: o.model, DisplayName: "Candela Fake Pro", Tier: "pro", Version: "dev", BaseModel: "none/fake",
		Runtime: "mlx", Host: "local-gpu-worker", Quantization: "none", ContextLength: 8192,
		SupportsReasoning: true, SupportsTools: true, SupportsTelemetry: true}
	if err := c.send(ctx, map[string]any{"type": "hello", "protocol": "candela.worker.v1", "workerId": o.id, "version": "0.0.0-fake",
		"device": "fake device", "maxConcurrency": 1, "models": []llm.ModelInfo{model}}); err != nil {
		return err
	}
	jobs := map[string]context.CancelFunc{}
	var jmu sync.Mutex
	for {
		_, data, err := ws.Read(ctx)
		if err != nil {
			return err
		}
		var m inbound
		if json.Unmarshal(data, &m) != nil {
			continue
		}
		switch m.Type {
		case "welcome":
			log.Info("registered", "model", o.model)
		case "ping":
			if !o.mutePongs {
				_ = c.send(ctx, map[string]any{"type": "pong", "ts": m.TS})
			}
		case "drain":
			log.Info("drain requested")
			_ = c.send(ctx, map[string]any{"type": "status", "state": "draining", "loadedModelId": o.model})
		case "cancel":
			jmu.Lock()
			if f := jobs[m.JobID]; f != nil {
				f()
			}
			jmu.Unlock()
		case "job":
			if o.crashOnJob {
				log.Warn("crash-on-job: dropping connection")
				return errors.New("crashed on purpose")
			}
			jctx, jcancel := context.WithCancel(ctx)
			jmu.Lock()
			jobs[m.JobID] = jcancel
			jmu.Unlock()
			go func() {
				defer func() {
					jmu.Lock()
					delete(jobs, m.JobID)
					jmu.Unlock()
					jcancel()
				}()
				runJob(jctx, ctx, c, m, o, log)
			}()
		}
	}
}

var tickerRE = regexp.MustCompile(`\b[A-Z]{2,5}\b`)

func runJob(jctx, sctx context.Context, c *conn, m inbound, o options, log *slog.Logger) {
	seq := 0
	emit := func(event string, data any) {
		seq++
		_ = c.send(sctx, map[string]any{"type": "event", "jobId": m.JobID, "seq": seq, "event": event, "data": data})
	}
	_ = c.send(sctx, map[string]any{"type": "status", "state": "busy", "loadedModelId": o.model, "memoryMb": 512})
	defer func() {
		_ = c.send(sctx, map[string]any{"type": "status", "state": "idle", "loadedModelId": o.model, "memoryMb": 512})
	}()
	start := time.Now()
	var first time.Time
	tokens := 0
	stream := func(event, text string) bool {
		for _, w := range strings.SplitAfter(text, " ") {
			select {
			case <-jctx.Done():
				emit("done", map[string]string{"finishReason": "cancelled"})
				log.Info("job cancelled", "job", m.JobID)
				return false
			case <-time.After(o.delay):
			}
			if first.IsZero() {
				first = time.Now()
			}
			emit(event, map[string]string{"delta": w})
			if m.Params.Telemetry {
				emit("telemetry", map[string]any{"step": tokens, "token": w, "phase": map[bool]string{true: "reasoning", false: "answer"}[event == "reasoning"],
					"entropy": 1.2, "topK": []map[string]any{{"token": w, "p": 0.61}}, "layers": []map[string]any{{"layer": 0, "norm": 12.5}}})
			}
			tokens++
		}
		return true
	}
	last := m.Messages[len(m.Messages)-1]
	toolCall := last.Role == "user"
	if m.Params.Reasoning && !stream("reasoning", "The user wants an analysis, so I will call a tool first. ") {
		return
	}
	if toolCall {
		sym := "NVDA"
		if t := tickerRE.FindString(last.Content); t != "" {
			sym = t
		}
		emit("tool_call", map[string]any{"id": "call_fake_1", "name": "get_quote", "arguments": map[string]string{"symbol": sym}})
	} else if !stream("token", fmt.Sprintf("Fake worker answer based on %d characters of tool data. This is canned output for protocol testing. ", len(last.Content))) {
		return
	}
	elapsed := time.Since(start)
	emit("usage", map[string]any{"promptTokens": 100, "completionTokens": tokens, "reasoningTokens": 0,
		"timeToFirstTokenMs": first.Sub(start).Milliseconds(), "tokensPerSecond": float64(tokens) / elapsed.Seconds(), "totalMs": elapsed.Milliseconds()})
	finish := "stop"
	if toolCall {
		finish = "tool_calls"
	}
	emit("done", map[string]string{"finishReason": finish})
}
