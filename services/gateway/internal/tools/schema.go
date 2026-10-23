package tools

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"slices"
	"sort"
	"strings"
	"unicode/utf8"
)

type property struct {
	Type      string          `json:"type"`
	MinLength *int            `json:"minLength"`
	MaxLength *int            `json:"maxLength"`
	Pattern   string          `json:"pattern"`
	Enum      []string        `json:"enum"`
	Minimum   *float64        `json:"minimum"`
	Maximum   *float64        `json:"maximum"`
	Default   json.RawMessage `json:"default"`
	re        *regexp.Regexp
}

type schema struct {
	Type                 string               `json:"type"`
	Properties           map[string]*property `json:"properties"`
	Required             []string             `json:"required"`
	AdditionalProperties *bool                `json:"additionalProperties"`
}

type toolDef struct {
	Type     string `json:"type"`
	Function struct {
		Name        string `json:"name"`
		Description string `json:"description"`
		Parameters  schema `json:"parameters"`
	} `json:"function"`
}

func parseDefs(raw []byte) ([]toolDef, error) {
	var defs []toolDef
	if err := json.Unmarshal(raw, &defs); err != nil {
		return nil, fmt.Errorf("tools.json: %w", err)
	}
	for _, d := range defs {
		for name, p := range d.Function.Parameters.Properties {
			if p.Pattern != "" {
				re, err := regexp.Compile(p.Pattern)
				if err != nil {
					return nil, fmt.Errorf("tools.json %s.%s: %w", d.Function.Name, name, err)
				}
				p.re = re
			}
		}
	}
	return defs, nil
}

// validate checks arguments against the subset of JSON Schema used in tools.json and
// returns the arguments with defaults applied.
func (s *schema) validate(raw []byte) (map[string]any, error) {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 {
		raw = []byte("{}")
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var args map[string]any
	if err := dec.Decode(&args); err != nil || args == nil {
		return nil, fmt.Errorf("arguments must be a JSON object")
	}
	if dec.More() {
		return nil, fmt.Errorf("arguments must be a single JSON object")
	}
	if s.AdditionalProperties != nil && !*s.AdditionalProperties {
		var extra []string
		for k := range args {
			if _, ok := s.Properties[k]; !ok {
				extra = append(extra, k)
			}
		}
		if len(extra) > 0 {
			sort.Strings(extra)
			return nil, fmt.Errorf("unknown argument(s): %s", strings.Join(extra, ", "))
		}
	}
	for _, r := range s.Required {
		if _, ok := args[r]; !ok {
			return nil, fmt.Errorf("missing required argument %q", r)
		}
	}
	names := make([]string, 0, len(s.Properties))
	for k := range s.Properties {
		names = append(names, k)
	}
	sort.Strings(names)
	for _, name := range names {
		p := s.Properties[name]
		v, ok := args[name]
		if !ok {
			if len(p.Default) > 0 {
				var d any
				dd := json.NewDecoder(bytes.NewReader(p.Default))
				dd.UseNumber()
				if err := dd.Decode(&d); err == nil {
					args[name] = d
				}
			}
			continue
		}
		if err := p.check(name, v); err != nil {
			return nil, err
		}
	}
	return args, nil
}

func (p *property) check(name string, v any) error {
	switch p.Type {
	case "string":
		s, ok := v.(string)
		if !ok {
			return fmt.Errorf("%s must be a string", name)
		}
		n := utf8.RuneCountInString(s)
		if p.MinLength != nil && n < *p.MinLength {
			return fmt.Errorf("%s must have at least %d characters", name, *p.MinLength)
		}
		if p.MaxLength != nil && n > *p.MaxLength {
			return fmt.Errorf("%s must have at most %d characters", name, *p.MaxLength)
		}
		if p.re != nil && !p.re.MatchString(s) {
			return fmt.Errorf("%s %q does not match %s", name, s, p.Pattern)
		}
		if len(p.Enum) > 0 && !slices.Contains(p.Enum, s) {
			return fmt.Errorf("%s must be one of %s", name, strings.Join(p.Enum, ", "))
		}
	case "integer":
		n, ok := v.(json.Number)
		if !ok {
			return fmt.Errorf("%s must be an integer", name)
		}
		f, err := n.Float64()
		if err != nil || f != math.Trunc(f) {
			return fmt.Errorf("%s must be an integer", name)
		}
		if p.Minimum != nil && f < *p.Minimum {
			return fmt.Errorf("%s must be >= %v", name, *p.Minimum)
		}
		if p.Maximum != nil && f > *p.Maximum {
			return fmt.Errorf("%s must be <= %v", name, *p.Maximum)
		}
	}
	return nil
}

func argString(args map[string]any, k string) string {
	s, _ := args[k].(string)
	return s
}

func argInt(args map[string]any, k string) int {
	n, _ := args[k].(json.Number)
	i, _ := n.Int64()
	return int(i)
}
