package contracts

import (
	_ "embed"
	"strings"
)

//go:embed tools.json
var ToolsJSON []byte

//go:embed system-prompt.md
var systemPrompt string

func SystemPrompt(today string) string {
	return strings.ReplaceAll(strings.TrimSpace(systemPrompt), "{{today}}", today)
}
