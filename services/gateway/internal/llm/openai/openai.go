package openai

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
)

type Client struct {
	baseURL   string
	apiKey    string
	model     string
	timeout   time.Duration
	idleLimit time.Duration
	http      *http.Client
}

func New(baseURL, apiKey, model string, timeout time.Duration) *Client {
	tr := &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		DialContext:           (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		MaxIdleConns:          8,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 60 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
	}
	return &Client{baseURL: strings.TrimRight(baseURL, "/"), apiKey: apiKey, model: model, timeout: timeout,
		idleLimit: 60 * time.Second, http: &http.Client{Transport: tr}}
}

type wireToolCall struct {
	Index    *int   `json:"index,omitempty"`
	ID       string `json:"id,omitempty"`
	Type     string `json:"type,omitempty"`
	Function struct {
		Name      string `json:"name,omitempty"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type wireMessage struct {
	Role       string         `json:"role"`
	Content    string         `json:"content"`
	ToolCalls  []wireToolCall `json:"tool_calls,omitempty"`
	ToolCallID string         `json:"tool_call_id,omitempty"`
}

type wireRequest struct {
	Model              string          `json:"model"`
	Messages           []wireMessage   `json:"messages"`
	Tools              json.RawMessage `json:"tools,omitempty"`
	ToolChoice         string          `json:"tool_choice,omitempty"`
	Stream             bool            `json:"stream"`
	StreamOptions      map[string]bool `json:"stream_options"`
	Temperature        float64         `json:"temperature"`
	TopP               float64         `json:"top_p"`
	MaxTokens          int             `json:"max_tokens"`
	Seed               *int64          `json:"seed,omitempty"`
	ChatTemplateKwargs map[string]any  `json:"chat_template_kwargs,omitempty"`
	CandelaTelemetry   bool            `json:"candela_telemetry,omitempty"`
}

type wireChunk struct {
	Choices []struct {
		Delta struct {
			Content          *string        `json:"content"`
			ReasoningContent *string        `json:"reasoning_content"`
			ToolCalls        []wireToolCall `json:"tool_calls"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens            int `json:"prompt_tokens"`
		CompletionTokens        int `json:"completion_tokens"`
		CompletionTokensDetails *struct {
			ReasoningTokens int `json:"reasoning_tokens"`
		} `json:"completion_tokens_details"`
	} `json:"usage"`
	Telemetry json.RawMessage `json:"candela_telemetry"`
	Error     *struct {
		Message string `json:"message"`
	} `json:"error"`
}

func encodeMessages(msgs []llm.Message) []wireMessage {
	out := make([]wireMessage, 0, len(msgs))
	for _, m := range msgs {
		wm := wireMessage{Role: m.Role, Content: m.Content, ToolCallID: m.ToolCallID}
		for _, tc := range m.ToolCalls {
			w := wireToolCall{ID: tc.ID, Type: "function"}
			w.Function.Name = tc.Name
			w.Function.Arguments = string(tc.Arguments)
			wm.ToolCalls = append(wm.ToolCalls, w)
		}
		out = append(out, wm)
	}
	return out
}

func (c *Client) Ping(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/models", nil)
	if err != nil {
		return err
	}
	c.auth(req)
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return nil
}

func (c *Client) auth(req *http.Request) {
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}
}

func (c *Client) Stream(ctx context.Context, r llm.Request, emit func(llm.Delta) error) (llm.Result, error) {
	ctx, cancelTimeout := context.WithTimeout(ctx, c.timeout)
	defer cancelTimeout()
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	body := wireRequest{
		Model: c.model, Messages: encodeMessages(r.Messages), Stream: true,
		StreamOptions: map[string]bool{"include_usage": true},
		Temperature:   r.Params.Temperature, TopP: r.Params.TopP, MaxTokens: r.Params.MaxTokens, Seed: r.Params.Seed,
		ChatTemplateKwargs: map[string]any{"enable_thinking": r.Params.Reasoning},
		CandelaTelemetry:   r.Params.Telemetry,
	}
	if len(r.Tools) > 0 {
		body.Tools, body.ToolChoice = r.Tools, "auto"
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return llm.Result{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return llm.Result{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	c.auth(req)
	resp, err := c.http.Do(req)
	if err != nil {
		return llm.Result{}, classify(ctx, err, true)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return llm.Result{}, &llm.Error{Code: "upstream_unavailable", Retryable: true,
			Message: fmt.Sprintf("fallback upstream returned HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))}
	}

	idle := time.AfterFunc(c.idleLimit, func() { cancel(errIdle) })
	defer idle.Stop()

	type partial struct {
		id, name string
		args     strings.Builder
	}
	calls := map[int]*partial{}
	var res llm.Result
	produced := false
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 64<<10), 4<<20)
	for sc.Scan() {
		idle.Reset(c.idleLimit)
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			break
		}
		var ch wireChunk
		if err := json.Unmarshal([]byte(data), &ch); err != nil {
			continue
		}
		if ch.Error != nil {
			return res, &llm.Error{Code: "upstream_unavailable", Message: ch.Error.Message, Retryable: !produced}
		}
		if ch.Usage != nil {
			u := &llm.Usage{PromptTokens: ch.Usage.PromptTokens, CompletionTokens: ch.Usage.CompletionTokens}
			if ch.Usage.CompletionTokensDetails != nil {
				u.ReasoningTokens = ch.Usage.CompletionTokensDetails.ReasoningTokens
			}
			res.Usage = u
		}
		if len(ch.Telemetry) > 0 && string(ch.Telemetry) != "null" {
			if err := emit(llm.Delta{Kind: llm.DeltaTelemetry, Raw: ch.Telemetry}); err != nil {
				return res, err
			}
		}
		for _, choice := range ch.Choices {
			d := choice.Delta
			if d.ReasoningContent != nil && *d.ReasoningContent != "" {
				produced = true
				if err := emit(llm.Delta{Kind: llm.DeltaReasoning, Text: *d.ReasoningContent}); err != nil {
					return res, err
				}
			}
			if d.Content != nil && *d.Content != "" {
				produced = true
				if err := emit(llm.Delta{Kind: llm.DeltaContent, Text: *d.Content}); err != nil {
					return res, err
				}
			}
			for i, tc := range d.ToolCalls {
				produced = true
				idx := i
				if tc.Index != nil {
					idx = *tc.Index
				}
				p := calls[idx]
				if p == nil {
					p = &partial{}
					calls[idx] = p
				}
				if tc.ID != "" {
					p.id = tc.ID
				}
				if tc.Function.Name != "" {
					p.name += tc.Function.Name
				}
				p.args.WriteString(tc.Function.Arguments)
			}
			if choice.FinishReason != nil && *choice.FinishReason != "" {
				res.FinishReason = *choice.FinishReason
			}
		}
	}
	if err := sc.Err(); err != nil {
		return res, classify(ctx, err, !produced)
	}
	if err := ctx.Err(); err != nil {
		return res, classify(ctx, err, !produced)
	}
	idxs := make([]int, 0, len(calls))
	for i := range calls {
		idxs = append(idxs, i)
	}
	sort.Ints(idxs)
	for n, i := range idxs {
		p := calls[i]
		id := p.id
		if id == "" {
			id = fmt.Sprintf("call_%d", n)
		}
		args := strings.TrimSpace(p.args.String())
		if args == "" {
			args = "{}"
		}
		res.ToolCalls = append(res.ToolCalls, llm.ToolCall{ID: id, Name: p.name, Arguments: json.RawMessage(args)})
	}
	if len(res.ToolCalls) > 0 {
		res.FinishReason = "tool_calls"
	}
	return res, nil
}

var errIdle = errors.New("upstream stream idle")

func classify(ctx context.Context, err error, retryable bool) error {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) || errors.Is(context.Cause(ctx), errIdle) {
		return &llm.Error{Code: "upstream_timeout", Message: "the model did not answer in time", Retryable: retryable}
	}
	if errors.Is(err, context.Canceled) || errors.Is(ctx.Err(), context.Canceled) {
		return context.Canceled
	}
	return &llm.Error{Code: "upstream_unavailable", Message: "the fallback model is unreachable", Retryable: retryable}
}
