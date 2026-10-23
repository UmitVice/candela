package workerhub

import (
	"context"
	"encoding/json"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
)

const jobDeadline = 120 * time.Second

type frame struct {
	event string
	data  json.RawMessage
}

type job struct {
	id      string
	events  chan frame
	lastSeq int
	failed  chan string
}

func (w *Worker) route(m inbound) {
	w.mu.Lock()
	j := w.jobs[m.JobID]
	if j == nil || m.Seq <= j.lastSeq {
		w.mu.Unlock()
		return
	}
	j.lastSeq = m.Seq
	w.mu.Unlock()
	select {
	case j.events <- frame{event: m.Event, data: m.Data}:
	default:
		w.hub.log.Warn("worker job buffer full; dropping frame", "job", j.id, "event", m.Event)
	}
}

func (w *Worker) failAll(reason string) {
	w.mu.Lock()
	w.gone = true
	jobs := w.jobs
	w.jobs = map[string]*job{}
	w.mu.Unlock()
	for _, j := range jobs {
		select {
		case j.failed <- reason:
		default:
		}
	}
}

func (w *Worker) Offers(modelID string) bool {
	for _, m := range w.Models {
		if m.ID == modelID {
			return true
		}
	}
	return false
}

type wireToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type wireMessage struct {
	Role       string         `json:"role"`
	Content    string         `json:"content"`
	ToolCalls  []wireToolCall `json:"tool_calls,omitempty"`
	ToolCallID string         `json:"tool_call_id,omitempty"`
}

func encodeMessages(msgs []llm.Message) []wireMessage {
	out := make([]wireMessage, 0, len(msgs))
	for _, m := range msgs {
		wm := wireMessage{Role: m.Role, Content: m.Content, ToolCallID: m.ToolCallID}
		for _, tc := range m.ToolCalls {
			c := wireToolCall{ID: tc.ID, Type: "function"}
			c.Function.Name, c.Function.Arguments = tc.Name, string(tc.Arguments)
			wm.ToolCalls = append(wm.ToolCalls, c)
		}
		out = append(out, wm)
	}
	return out
}

// Stream implements llm.Upstream for one worker connection.
func (w *Worker) Stream(ctx context.Context, req llm.Request, emit func(llm.Delta) error) (llm.Result, error) {
	j := &job{id: "j_" + randomID(), events: make(chan frame, 1024), failed: make(chan string, 1)}
	w.mu.Lock()
	if w.gone {
		w.mu.Unlock()
		return llm.Result{}, &llm.Error{Code: "upstream_unavailable", Message: "worker disconnected", Retryable: true}
	}
	w.jobs[j.id] = j
	w.mu.Unlock()
	defer func() {
		w.mu.Lock()
		delete(w.jobs, j.id)
		w.mu.Unlock()
		w.hub.onChange()
	}()

	msg := map[string]any{
		"type": "job", "jobId": j.id, "modelId": req.Model.ID, "messages": encodeMessages(req.Messages),
		"tools": req.Tools, "params": req.Params, "deadlineMs": jobDeadline.Milliseconds(),
	}
	if err := w.send(ctx, msg); err != nil {
		return llm.Result{}, &llm.Error{Code: "upstream_unavailable", Message: "could not send job to worker", Retryable: true}
	}
	deadline := time.NewTimer(jobDeadline + 5*time.Second)
	defer deadline.Stop()

	var res llm.Result
	produced := false
	for {
		select {
		case <-ctx.Done():
			cctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
			_ = w.send(cctx, map[string]any{"type": "cancel", "jobId": j.id})
			cancel()
			return res, ctx.Err()
		case <-deadline.C:
			cctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
			_ = w.send(cctx, map[string]any{"type": "cancel", "jobId": j.id})
			cancel()
			return res, &llm.Error{Code: "upstream_timeout", Message: "worker job deadline exceeded", Retryable: !produced}
		case reason := <-j.failed:
			return res, &llm.Error{Code: "upstream_unavailable", Message: "worker disconnected: " + reason, Retryable: !produced}
		case f := <-j.events:
			switch f.event {
			case "reasoning", "token":
				var d struct {
					Delta string `json:"delta"`
				}
				if json.Unmarshal(f.data, &d) != nil || d.Delta == "" {
					continue
				}
				produced = true
				kind := llm.DeltaContent
				if f.event == "reasoning" {
					kind = llm.DeltaReasoning
				}
				if err := emit(llm.Delta{Kind: kind, Text: d.Delta}); err != nil {
					return res, err
				}
			case "telemetry":
				if err := emit(llm.Delta{Kind: llm.DeltaTelemetry, Raw: f.data}); err != nil {
					return res, err
				}
			case "tool_call":
				var tc struct {
					ID        string          `json:"id"`
					Name      string          `json:"name"`
					Arguments json.RawMessage `json:"arguments"`
				}
				if json.Unmarshal(f.data, &tc) != nil {
					continue
				}
				produced = true
				args := tc.Arguments
				var s string
				if json.Unmarshal(args, &s) == nil {
					args = json.RawMessage(s)
				}
				if len(args) == 0 {
					args = json.RawMessage("{}")
				}
				res.ToolCalls = append(res.ToolCalls, llm.ToolCall{ID: tc.ID, Name: tc.Name, Arguments: args})
			case "usage":
				var u llm.Usage
				if json.Unmarshal(f.data, &u) == nil {
					res.Usage = &u
				}
			case "done":
				var d struct {
					FinishReason string `json:"finishReason"`
				}
				_ = json.Unmarshal(f.data, &d)
				res.FinishReason = d.FinishReason
				if len(res.ToolCalls) > 0 {
					res.FinishReason = "tool_calls"
				}
				return res, nil
			case "error":
				var e struct {
					Code    string `json:"code"`
					Message string `json:"message"`
				}
				_ = json.Unmarshal(f.data, &e)
				if e.Code == "" {
					e.Code = "upstream_unavailable"
				}
				return res, &llm.Error{Code: e.Code, Message: e.Message, Retryable: !produced}
			}
		}
	}
}
