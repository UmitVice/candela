package tools

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/contracts"
	"github.com/UmitVice/candela/services/gateway/internal/market"
)

const maxModelView = 2500

type Result struct {
	Name      string        `json:"-"`
	OK        bool          `json:"-"`
	ModelView string        `json:"modelView"`
	UIView    any           `json:"uiView"`
	Summary   string        `json:"-"`
	Error     string        `json:"-"`
	Code      string        `json:"-"`
	Duration  time.Duration `json:"-"`
}

type handler func(ctx context.Context, args map[string]any) (Result, error)

type Registry struct {
	defs     map[string]*toolDef
	order    []string
	handlers map[string]handler
	market   *market.Service
	raw      json.RawMessage
}

func NewRegistry(m *market.Service) (*Registry, error) {
	defs, err := parseDefs(contracts.ToolsJSON)
	if err != nil {
		return nil, err
	}
	r := &Registry{defs: map[string]*toolDef{}, market: m, raw: json.RawMessage(contracts.ToolsJSON)}
	r.handlers = map[string]handler{
		"search_symbols":           r.searchSymbols,
		"get_quote":                r.getQuote,
		"get_price_history":        r.getPriceHistory,
		"get_technical_indicators": r.getIndicators,
		"get_fundamentals":         r.getFundamentals,
		"get_forecast":             r.getForecast,
	}
	for i := range defs {
		name := defs[i].Function.Name
		if _, ok := r.handlers[name]; !ok {
			return nil, fmt.Errorf("tools.json declares %q without an implementation", name)
		}
		r.defs[name] = &defs[i]
		r.order = append(r.order, name)
	}
	for name := range r.handlers {
		if _, ok := r.defs[name]; !ok {
			return nil, fmt.Errorf("tool %q is implemented but missing from tools.json", name)
		}
	}
	return r, nil
}

func (r *Registry) Definitions() json.RawMessage { return r.raw }

func (r *Registry) Names() []string { return r.order }

func (r *Registry) Known(name string) bool { _, ok := r.defs[name]; return ok }

func (r *Registry) Execute(ctx context.Context, name string, rawArgs json.RawMessage) Result {
	start := time.Now()
	res := r.execute(ctx, name, rawArgs)
	res.Name = name
	res.Duration = time.Since(start)
	return res
}

func failure(code, msg string) Result {
	return Result{OK: false, Code: code, Error: msg, ModelView: errorView(code, msg), Summary: msg}
}

func (r *Registry) execute(ctx context.Context, name string, rawArgs json.RawMessage) Result {
	def, ok := r.defs[name]
	if !ok {
		return failure("invalid_arguments", fmt.Sprintf("unknown tool %q", name))
	}
	args, err := def.Function.Parameters.validate(rawArgs)
	if err != nil {
		return failure("invalid_arguments", err.Error())
	}
	res, err := r.handlers[name](ctx, args)
	if err != nil {
		return mapError(err, args)
	}
	res.OK = true
	return res
}

func mapError(err error, args map[string]any) Result {
	sym := argString(args, "symbol")
	var se *market.SourceError
	switch {
	case errors.As(err, &se):
		return failure("data_unavailable", se.Msg)
	case errors.Is(err, market.ErrNotFound):
		return failure("not_found", fmt.Sprintf("unknown symbol %s", sym))
	case errors.Is(err, market.ErrInvalid):
		return failure("invalid_arguments", "invalid arguments")
	case errors.Is(err, context.DeadlineExceeded):
		return failure("data_unavailable", "the data source timed out")
	case errors.Is(err, context.Canceled):
		return failure("data_unavailable", "the request was cancelled")
	default:
		return failure("data_unavailable", "the data source is unavailable")
	}
}

// fit trims the trimmable array of a model view, oldest side first, until the
// encoded view fits the 2 500 character cap from contracts/tools.md.
func fit(build func(keep int) []byte, total int) string {
	for keep := total; keep >= 0; keep-- {
		b := build(keep)
		if len(b) <= maxModelView || keep == 0 {
			return string(b)
		}
	}
	return string(build(0))
}
