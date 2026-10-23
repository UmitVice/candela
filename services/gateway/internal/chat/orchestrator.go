package chat

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"sync"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/contracts"
	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
	"github.com/UmitVice/candela/services/gateway/internal/tools"
)

const (
	MaxToolRounds   = 6
	telemetryMinGap = 50 * time.Millisecond
	defaultTopP     = 0.95
	overloadRetryMs = 5000
	upstreamRetryMs = 10000
)

type Emitter interface {
	Emit(event string, data any) error
}

type Limits struct {
	MaxInputChars   int
	MaxContextChars int
	MaxOutputTokens int
	ToolTimeout     time.Duration
}

var publicMessages = map[string]string{
	"upstream_unavailable": "the model is unavailable right now",
	"upstream_timeout":     "the model did not answer in time",
	"overloaded":           "all generation slots and the queue are full",
	"invalid_request":      "the request was rejected",
	"internal":             "internal error",
}

type Orchestrator struct {
	limits      Limits
	sched       *Scheduler
	tools       *tools.Registry
	metrics     *observability.Metrics
	log         *slog.Logger
	toolTimeout time.Duration
	recorder    *Recorder
	now         func() time.Time

	active sync.WaitGroup
}

func NewOrchestrator(s *Scheduler, t *tools.Registry, m *observability.Metrics, log *slog.Logger, limits Limits, rec *Recorder) *Orchestrator {
	return &Orchestrator{sched: s, tools: t, metrics: m, log: log, limits: limits, toolTimeout: limits.ToolTimeout, recorder: rec, now: time.Now}
}

func msgChars(msgs []llm.Message) int {
	n := 0
	for _, m := range msgs {
		n += len(m.Content) + 16
		for _, c := range m.ToolCalls {
			n += len(c.Name) + len(c.Arguments) + 16
		}
	}
	return n
}

// boundHistory keeps the newest turns that fit the input budget so prompt size is
// bounded before any generation starts; the latest user message is always kept.
func (o *Orchestrator) boundHistory(msgs []ClientMessage) ([]ClientMessage, bool) {
	total := 0
	start := len(msgs)
	for i := len(msgs) - 1; i >= 0; i-- {
		total += len(msgs[i].Content) + 16
		if total > o.limits.MaxInputChars {
			break
		}
		start = i
	}
	if start == len(msgs) {
		return nil, false
	}
	for start < len(msgs)-1 && msgs[start].Role != "user" {
		start++
	}
	return msgs[start:], true
}

func (o *Orchestrator) Scheduler() *Scheduler { return o.sched }

func (o *Orchestrator) Wait() { o.active.Wait() }

type PlanError struct {
	Code    string
	Message string
	Status  int
}

func (e *PlanError) Error() string { return e.Message }

// Plan resolves the route before any event is written so that HTTP-level failures can
// still be reported with a status code.
func (o *Orchestrator) Plan(req *Request) (route string, model llm.ModelInfo, err error) {
	route, model, err = o.sched.Resolve(req.Model)
	switch {
	case errors.Is(err, ErrUnknownModel):
		return "", model, &PlanError{Code: "invalid_request", Message: "unknown model " + req.Model, Status: 400}
	case err != nil:
		return "", model, &PlanError{Code: "upstream_unavailable", Message: "no model is available right now", Status: 503}
	}
	return route, model, nil
}

func SystemPrompt(now time.Time) string {
	return contracts.SystemPrompt(now.UTC().Format("2006-01-02"))
}

type runState struct {
	o         *Orchestrator
	req       *Request
	opts      resolvedOptions
	emitter   Emitter
	log       *slog.Logger
	start     time.Time
	route     string
	model     llm.ModelInfo
	firstTok  time.Time
	genTime   time.Duration
	usage     llm.Usage
	lastTelem time.Time
	toolNames []string
	rounds    int
	recorded  []RecordedEvent
	emitErr   error
}

func (st *runState) emit(event string, data any) error {
	if st.emitErr != nil {
		return st.emitErr
	}
	if st.o.recorder != nil {
		raw, _ := json.Marshal(data)
		st.recorded = append(st.recorded, RecordedEvent{AtMs: time.Since(st.start).Milliseconds(), Event: event, Data: raw})
	}
	st.emitErr = st.emitter.Emit(event, data)
	return st.emitErr
}

func (o *Orchestrator) Run(ctx context.Context, requestID, transport string, req *Request, route string, model llm.ModelInfo, emitter Emitter) {
	o.active.Add(1)
	defer o.active.Done()
	o.metrics.ActiveChats.Inc()
	defer o.metrics.ActiveChats.Dec()

	st := &runState{o: o, req: req, opts: req.options(), emitter: emitter, start: o.now(), route: route, model: model,
		log: o.log.With("requestId", requestID)}
	messageID := "msg_" + randomHex(8)
	modelID := ""
	if req.Model != "auto" {
		modelID = req.Model
	}
	_ = st.emit("meta", map[string]any{"requestId": requestID, "conversationId": req.ConversationID, "messageId": messageID,
		"model": model, "route": route, "createdAt": st.start.UTC().Format(time.RFC3339)})

	outcome, finish := st.execute(ctx, modelID, messageID, requestID)

	o.metrics.ChatRequests.WithLabelValues(st.route, transport, outcome).Inc()
	if !st.firstTok.IsZero() {
		o.metrics.TTFT.WithLabelValues(st.route).Observe(st.usage.TimeToFirstTokenMs / 1000)
		if st.usage.TokensPerSecond > 0 {
			o.metrics.TokensPerSec.WithLabelValues(st.route).Observe(st.usage.TokensPerSecond)
		}
	}
	st.log.Info("chat",
		"transport", transport, "route", st.route, "model", st.model.ID, "rounds", st.rounds, "tools", st.toolNames,
		"promptTokens", st.usage.PromptTokens, "completionTokens", st.usage.CompletionTokens,
		"ttftMs", int64(st.usage.TimeToFirstTokenMs), "totalMs", time.Since(st.start).Milliseconds(),
		"outcome", outcome, "finishReason", finish)
	if o.recorder != nil && outcome == "ok" {
		o.recorder.Save(req, st.model, st.recorded, st.log)
	}
}

func (st *runState) fail(code, message string, retryMs int) (string, string) {
	data := map[string]any{"code": code, "message": message}
	if retryMs > 0 {
		data["retryAfterMs"] = retryMs
	}
	_ = st.emit("error", data)
	return code, ""
}

func (st *runState) cancelled() (string, string) {
	_ = st.emit("done", map[string]any{"finishReason": "cancelled"})
	return "cancelled", "cancelled"
}

func (st *runState) acquire(ctx context.Context, route, modelID string) (*Lease, error) {
	return st.o.sched.Acquire(ctx, route, modelID, func(pos int) {
		_ = st.emit("queue", map[string]any{"position": pos, "etaMs": int64(st.o.sched.ETA(pos))})
	})
}

func (st *runState) execute(ctx context.Context, modelID, messageID, requestID string) (string, string) {
	o := st.o
	lease, err := st.acquire(ctx, st.route, modelID)
	switch {
	case errors.Is(err, ErrOverloaded):
		return st.fail("overloaded", "all generation slots and the queue are full", overloadRetryMs)
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		return st.cancelled()
	case err != nil:
		return st.fail("upstream_unavailable", "no model is available right now", upstreamRetryMs)
	}
	defer func() { lease.Release() }()

	history, ok := o.boundHistory(st.req.Messages)
	if !ok {
		return st.fail("invalid_request", "the latest message exceeds the input limit", 0)
	}
	messages := make([]llm.Message, 0, len(history)+8)
	messages = append(messages, llm.Message{Role: "system", Content: SystemPrompt(o.now())})
	for _, m := range history {
		messages = append(messages, llm.Message{Role: m.Role, Content: m.Content})
	}
	budget := min(st.opts.maxTokens, o.limits.MaxOutputTokens)
	params := llm.Params{Temperature: st.opts.temperature, TopP: defaultTopP, MaxTokens: budget,
		Reasoning: st.opts.reasoning, Telemetry: st.opts.telemetry && lease.Model.SupportsTelemetry}
	retried := false
	finish := "stop"

	for {
		remaining := budget - st.usage.CompletionTokens
		if remaining < 16 {
			finish = "length"
			break
		}
		if msgChars(messages) > o.limits.MaxContextChars {
			finish = "tool_limit"
			break
		}
		params.MaxTokens = remaining
		genStart := time.Now()
		res, answer, err := st.generate(ctx, lease, messages, params)
		st.genTime += time.Since(genStart)
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, context.Canceled) {
				return st.cancelled()
			}
			if st.emitErr != nil {
				return "client_gone", ""
			}
			le, _ := llm.AsError(err)
			if le != nil && le.Retryable && lease.Route == "worker" && !retried && st.firstTok.IsZero() {
				if fb := st.retryOnFallback(ctx, lease, requestID, messageID); fb != nil {
					lease, retried = fb, true
					params.Telemetry = st.opts.telemetry && lease.Model.SupportsTelemetry
					continue
				}
			}
			code := "upstream_unavailable"
			if le != nil && knownCode(le.Code) {
				code = le.Code
			}
			st.log.Warn("generation failed", "route", lease.Route, "code", code, "err", err)
			msg, ok := publicMessages[code]
			if !ok {
				msg = publicMessages["upstream_unavailable"]
			}
			return st.fail(code, msg, 0)
		}
		if len(res.ToolCalls) == 0 {
			if res.FinishReason == "length" {
				finish = "length"
			}
			break
		}
		if st.rounds >= MaxToolRounds {
			finish = "tool_limit"
			break
		}
		st.rounds++
		calls := normalizeCalls(res.ToolCalls)
		messages = append(messages, llm.Message{Role: "assistant", Content: answer, ToolCalls: calls})
		results := st.runTools(ctx, calls)
		if ctx.Err() != nil {
			return st.cancelled()
		}
		for i, c := range calls {
			messages = append(messages, llm.Message{Role: "tool", ToolCallID: c.ID, Content: results[i].ModelView})
		}
	}
	st.finishUsage()
	o.sched.ObserveDuration(st.genTime)
	_ = st.emit("usage", st.usage)
	_ = st.emit("done", map[string]any{"finishReason": finish})
	if st.emitErr != nil {
		return "client_gone", finish
	}
	return "ok", finish
}

func knownCode(c string) bool {
	switch c {
	case "invalid_request", "not_found", "rate_limited", "overloaded", "upstream_unavailable", "upstream_timeout",
		"data_unavailable", "unauthorized", "internal":
		return true
	}
	return false
}

func (st *runState) retryOnFallback(ctx context.Context, failed *Lease, requestID, messageID string) *Lease {
	failed.Release()
	fb := st.o.sched.fallback
	if fb == nil || fb.Concurrency == 0 || !fb.Healthy() {
		return nil
	}
	st.o.metrics.UpstreamRetry.Inc()
	st.log.Warn("worker failed before the first token; retrying on the fallback")
	lease, err := st.acquire(ctx, "fallback", "")
	if err != nil {
		return nil
	}
	st.route, st.model = lease.Route, lease.Model
	_ = st.emit("meta", map[string]any{"requestId": requestID, "conversationId": st.req.ConversationID, "messageId": messageID,
		"model": lease.Model, "route": lease.Route, "createdAt": st.start.UTC().Format(time.RFC3339)})
	return lease
}

func (st *runState) generate(ctx context.Context, lease *Lease, messages []llm.Message, params llm.Params) (llm.Result, string, error) {
	sp := &splitter{}
	var answer []byte
	chunks := 0
	reasoningChunks := 0
	push := func(p piece) error {
		if st.firstTok.IsZero() {
			st.firstTok = time.Now()
		}
		if p.reasoning {
			reasoningChunks++
			if !st.opts.reasoning {
				return nil
			}
			return st.emit("reasoning", map[string]string{"delta": p.text})
		}
		answer = append(answer, p.text...)
		return st.emit("token", map[string]string{"delta": p.text})
	}
	emit := func(d llm.Delta) error {
		switch d.Kind {
		case llm.DeltaTelemetry:
			if !params.Telemetry || time.Since(st.lastTelem) < telemetryMinGap {
				return nil
			}
			st.lastTelem = time.Now()
			return st.emit("telemetry", d.Raw)
		case llm.DeltaReasoning:
			chunks++
			return push(piece{reasoning: true, text: d.Text})
		default:
			chunks++
			for _, p := range sp.push(d.Text) {
				if err := push(p); err != nil {
					return err
				}
			}
		}
		return nil
	}
	req := llm.Request{Model: lease.Model, Messages: messages, Tools: st.o.tools.Definitions(), Params: params}
	res, err := lease.Upstream.Stream(ctx, req, emit)
	if err == nil {
		for _, p := range sp.flush() {
			if e := push(p); e != nil {
				err = e
			}
		}
	}
	if u := res.Usage; u != nil {
		st.usage.PromptTokens += u.PromptTokens
		st.usage.CompletionTokens += u.CompletionTokens
		if u.ReasoningTokens > 0 {
			st.usage.ReasoningTokens += u.ReasoningTokens
		} else {
			st.usage.ReasoningTokens += reasoningChunks
		}
	} else {
		st.usage.CompletionTokens += chunks
		st.usage.ReasoningTokens += reasoningChunks
	}
	return res, string(answer), err
}

func (st *runState) finishUsage() {
	total := time.Since(st.start)
	st.usage.TotalMs = float64(total.Milliseconds())
	if !st.firstTok.IsZero() {
		st.usage.TimeToFirstTokenMs = float64(st.firstTok.Sub(st.start).Milliseconds())
	}
	if secs := st.genTime.Seconds(); secs > 0 {
		st.usage.TokensPerSecond = roundTo(float64(st.usage.CompletionTokens)/secs, 1)
	}
}

func roundTo(v float64, dp int) float64 {
	p := 1.0
	for range dp {
		p *= 10
	}
	return float64(int64(v*p+0.5)) / p
}

func normalizeCalls(calls []llm.ToolCall) []llm.ToolCall {
	seen := map[string]bool{}
	out := make([]llm.ToolCall, len(calls))
	for i, c := range calls {
		if c.ID == "" || seen[c.ID] {
			c.ID = "call_" + randomHex(6)
		}
		seen[c.ID] = true
		out[i] = c
	}
	return out
}

func (st *runState) runTools(ctx context.Context, calls []llm.ToolCall) []tools.Result {
	o := st.o
	for _, c := range calls {
		var args any = map[string]any{}
		var parsed map[string]any
		if json.Unmarshal(c.Arguments, &parsed) == nil && parsed != nil {
			args = parsed
		}
		st.toolNames = append(st.toolNames, c.Name)
		_ = st.emit("tool_call", map[string]any{"id": c.ID, "name": c.Name, "arguments": args})
	}
	results := make([]tools.Result, len(calls))
	var wg sync.WaitGroup
	for i, c := range calls {
		wg.Go(func() {
			tctx, cancel := context.WithTimeout(ctx, o.toolTimeout)
			defer cancel()
			results[i] = o.tools.Execute(tctx, c.Name, c.Arguments)
		})
	}
	wg.Wait()
	for i, c := range calls {
		r := results[i]
		o.metrics.ToolDuration.WithLabelValues(metricToolName(o.tools, c.Name)).Observe(r.Duration.Seconds())
		data := map[string]any{"id": c.ID, "name": c.Name, "ok": r.OK, "durationMs": r.Duration.Milliseconds(), "summary": r.Summary}
		if r.OK {
			data["data"] = r.UIView
		} else {
			data["error"] = r.Error
			o.metrics.ToolErrors.WithLabelValues(metricToolName(o.tools, c.Name), r.Code).Inc()
		}
		_ = st.emit("tool_result", data)
		st.log.Debug("tool executed", "tool", c.Name, "ok", r.OK, "modelViewSha256", sha(r.ModelView), "modelViewBytes", len(r.ModelView))
	}
	return results
}

func metricToolName(r *tools.Registry, name string) string {
	if r.Known(name) {
		return name
	}
	return "unknown"
}

func sha(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
