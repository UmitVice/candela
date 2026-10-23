package chat

import (
	"fmt"
	"regexp"
	"unicode/utf8"
)

type ClientMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type Options struct {
	Reasoning   *bool    `json:"reasoning,omitempty"`
	Telemetry   *bool    `json:"telemetry,omitempty"`
	Temperature *float64 `json:"temperature,omitempty"`
	MaxTokens   *int     `json:"maxTokens,omitempty"`
}

type Request struct {
	ConversationID string          `json:"conversationId"`
	Messages       []ClientMessage `json:"messages"`
	Model          string          `json:"model,omitempty"`
	Options        *Options        `json:"options,omitempty"`
}

var (
	uuidV4  = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$`)
	modelID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$`)
)

func (r *Request) Validate() error {
	if !uuidV4.MatchString(r.ConversationID) {
		return fmt.Errorf("conversationId must be a UUID v4")
	}
	if n := len(r.Messages); n < 1 || n > 40 {
		return fmt.Errorf("messages must contain 1..40 items")
	}
	for i, m := range r.Messages {
		if m.Role != "user" && m.Role != "assistant" {
			return fmt.Errorf("messages[%d].role must be user or assistant", i)
		}
		if n := utf8.RuneCountInString(m.Content); n < 1 || n > 8000 {
			return fmt.Errorf("messages[%d].content must have 1..8000 characters", i)
		}
		if !utf8.ValidString(m.Content) {
			return fmt.Errorf("messages[%d].content must be valid UTF-8", i)
		}
	}
	if r.Messages[len(r.Messages)-1].Role != "user" {
		return fmt.Errorf("the last message must have role user")
	}
	if r.Model == "" {
		r.Model = "auto"
	}
	if r.Model != "auto" && !modelID.MatchString(r.Model) {
		return fmt.Errorf("model must be 'auto' or a model id")
	}
	if o := r.Options; o != nil {
		if o.Temperature != nil && (*o.Temperature < 0 || *o.Temperature > 1.2) {
			return fmt.Errorf("options.temperature must be within 0..1.2")
		}
		if o.MaxTokens != nil && (*o.MaxTokens < 64 || *o.MaxTokens > 2048) {
			return fmt.Errorf("options.maxTokens must be within 64..2048")
		}
	}
	return nil
}

type resolvedOptions struct {
	reasoning   bool
	telemetry   bool
	temperature float64
	maxTokens   int
}

func (r *Request) options() resolvedOptions {
	o := resolvedOptions{reasoning: true, temperature: 0.6, maxTokens: 1024}
	if r.Options == nil {
		return o
	}
	if r.Options.Reasoning != nil {
		o.reasoning = *r.Options.Reasoning
	}
	if r.Options.Telemetry != nil {
		o.telemetry = *r.Options.Telemetry
	}
	if r.Options.Temperature != nil {
		o.temperature = *r.Options.Temperature
	}
	if r.Options.MaxTokens != nil {
		o.maxTokens = *r.Options.MaxTokens
	}
	return o
}
