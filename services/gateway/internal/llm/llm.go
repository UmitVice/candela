package llm

import (
	"context"
	"encoding/json"
	"errors"
)

type ModelArchitecture struct {
	Layers         int    `json:"layers"`
	HiddenSize     int    `json:"hiddenSize"`
	AttentionHeads int    `json:"attentionHeads"`
	KVHeads        int    `json:"kvHeads"`
	VocabSize      int    `json:"vocabSize"`
	Parameters     string `json:"parameters"`
}

type ModelInfo struct {
	ID                string             `json:"id"`
	DisplayName       string             `json:"displayName"`
	Tier              string             `json:"tier"`
	Version           string             `json:"version"`
	BaseModel         string             `json:"baseModel"`
	Runtime           string             `json:"runtime"`
	Host              string             `json:"host"`
	Quantization      string             `json:"quantization"`
	ContextLength     int                `json:"contextLength"`
	SupportsReasoning bool               `json:"supportsReasoning"`
	SupportsTools     bool               `json:"supportsTools"`
	SupportsTelemetry bool               `json:"supportsTelemetry"`
	Architecture      *ModelArchitecture `json:"architecture,omitempty"`
}

type ToolCall struct {
	ID        string          `json:"id"`
	Name      string          `json:"name"`
	Arguments json.RawMessage `json:"arguments"`
}

type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content"`
	ToolCalls  []ToolCall `json:"toolCalls,omitempty"`
	ToolCallID string     `json:"toolCallId,omitempty"`
}

type Params struct {
	Temperature float64 `json:"temperature"`
	TopP        float64 `json:"topP"`
	MaxTokens   int     `json:"maxTokens"`
	Reasoning   bool    `json:"reasoning"`
	Telemetry   bool    `json:"telemetry"`
	Seed        *int64  `json:"seed"`
}

type Request struct {
	Model    ModelInfo
	Messages []Message
	Tools    json.RawMessage
	Params   Params
}

type DeltaKind int

const (
	DeltaContent DeltaKind = iota
	DeltaReasoning
	DeltaTelemetry
)

type Delta struct {
	Kind DeltaKind
	Text string
	Raw  json.RawMessage
}

type Usage struct {
	PromptTokens       int     `json:"promptTokens"`
	CompletionTokens   int     `json:"completionTokens"`
	ReasoningTokens    int     `json:"reasoningTokens"`
	TimeToFirstTokenMs float64 `json:"timeToFirstTokenMs"`
	TokensPerSecond    float64 `json:"tokensPerSecond"`
	TotalMs            float64 `json:"totalMs"`
}

type Result struct {
	ToolCalls    []ToolCall
	FinishReason string
	Usage        *Usage
}

type Upstream interface {
	Stream(ctx context.Context, req Request, emit func(Delta) error) (Result, error)
}

type Error struct {
	Code    string
	Message string
	// Retryable marks failures that happened before any output was produced, which the
	// orchestrator may retry on another upstream.
	Retryable bool
}

func (e *Error) Error() string { return e.Code + ": " + e.Message }

func AsError(err error) (*Error, bool) {
	var e *Error
	ok := errors.As(err, &e)
	return e, ok
}
