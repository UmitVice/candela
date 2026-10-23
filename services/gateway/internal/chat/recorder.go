package chat

import (
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
)

type RecordedEvent struct {
	AtMs  int64           `json:"atMs"`
	Event string          `json:"event"`
	Data  json.RawMessage `json:"data"`
}

type Recording struct {
	Version    int             `json:"version"`
	Title      string          `json:"title"`
	RecordedAt string          `json:"recordedAt"`
	Model      llm.ModelInfo   `json:"model"`
	Request    *Request        `json:"request"`
	Events     []RecordedEvent `json:"events"`
}

// Recorder writes replayable sessions (contracts/api.md, "Recorded sessions"); it is an
// owner-only local feature because recordings contain the conversation text.
type Recorder struct{ dir string }

func NewRecorder(dir string) (*Recorder, error) {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return nil, err
	}
	return &Recorder{dir: dir}, nil
}

func (r *Recorder) Save(req *Request, model llm.ModelInfo, events []RecordedEvent, log *slog.Logger) {
	title := req.Messages[len(req.Messages)-1].Content
	if rs := []rune(title); len(rs) > 80 {
		title = string(rs[:80])
	}
	rec := Recording{Version: 1, Title: strings.TrimSpace(title), RecordedAt: time.Now().UTC().Format(time.RFC3339),
		Model: model, Request: req, Events: events}
	b, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		log.Warn("recording encode failed", "err", err)
		return
	}
	name := time.Now().UTC().Format("20060102T150405Z") + "-" + randomHex(4) + ".json"
	if err := os.WriteFile(filepath.Join(r.dir, name), b, 0o600); err != nil {
		log.Warn("recording write failed", "err", err)
		return
	}
	log.Info("session recorded", "file", name)
}
