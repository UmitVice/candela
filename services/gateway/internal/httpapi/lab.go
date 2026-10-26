package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	sparkStatusSchema  = "candela.spark.status.v1"
	sparkStatusMaxSize = 256 << 10
	sparkCacheTTL      = 10 * time.Second
	sparkMaxMilestones = 64
)

var (
	sparkIdentRE  = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
	sparkStateRE  = regexp.MustCompile(`^[a-z][a-z-]{0,23}$`)
	sparkReasonRE = regexp.MustCompile(`^[A-Za-z0-9 ,.%=-]{1,120}$`)
)

type sparkTrain struct {
	Loss         *float64 `json:"loss,omitempty"`
	TokensPerSec *float64 `json:"tokensPerSec,omitempty"`
	LR           *float64 `json:"lr,omitempty"`
	PeakMemGB    *float64 `json:"peakMemGb,omitempty"`
}

type sparkValid struct {
	BF16   *float64 `json:"bf16,omitempty"`
	Int4   *float64 `json:"int4,omitempty"`
	GapRel *float64 `json:"gapRel,omitempty"`
	Step   *int64   `json:"step,omitempty"`
}

type sparkMilestone struct {
	Step   int64  `json:"step"`
	Tokens int64  `json:"tokens"`
	At     string `json:"at,omitempty"`
	Kind   string `json:"kind,omitempty"`
}

type sparkStatus struct {
	Schema        string           `json:"schema"`
	UpdatedAt     string           `json:"updatedAt"`
	State         string           `json:"state"`
	RunID         string           `json:"runId"`
	Model         string           `json:"model"`
	Parameters    int64            `json:"parameters"`
	Phase         string           `json:"phase"`
	Step          int64            `json:"step"`
	Tokens        int64            `json:"tokens"`
	PauseReason   *string          `json:"pauseReason"`
	Train         *sparkTrain      `json:"train"`
	Valid         *sparkValid      `json:"valid"`
	Milestones    []sparkMilestone `json:"milestones"`
	LeasePriority *int64           `json:"leasePriority,omitempty"`
	StartedAt     string           `json:"startedAt,omitempty"`
}

type sparkCache struct {
	mu      sync.Mutex
	path    string
	at      time.Time
	body    []byte
	missing bool
}

func finite(p *float64) *float64 {
	if p == nil || math.IsNaN(*p) || math.IsInf(*p, 0) {
		return nil
	}
	return p
}

func isoTime(s string) string {
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}

func ident(s string) string {
	if sparkIdentRE.MatchString(s) {
		return s
	}
	return ""
}

// pauseReason keeps the coarse reason only: the trainer may embed a foreign process
// name in parentheses or after a colon, which is local information that must not reach visitors.
func pauseReason(p *string) *string {
	if p == nil {
		return nil
	}
	r, _, _ := strings.Cut(*p, "(")
	r, _, _ = strings.Cut(r, ":")
	r = strings.TrimSpace(r)
	if !sparkReasonRE.MatchString(r) {
		r = "paused"
	}
	return &r
}

func sanitizeSpark(raw []byte) ([]byte, error) {
	var in sparkStatus
	if err := json.Unmarshal(raw, &in); err != nil {
		return nil, err
	}
	if in.Schema != sparkStatusSchema {
		return nil, errors.New("unexpected schema")
	}
	out := sparkStatus{
		Schema: sparkStatusSchema, UpdatedAt: isoTime(in.UpdatedAt), RunID: ident(in.RunID), Model: ident(in.Model),
		Parameters: max(0, in.Parameters), Phase: ident(in.Phase), Step: max(0, in.Step), Tokens: max(0, in.Tokens),
		PauseReason: pauseReason(in.PauseReason), LeasePriority: in.LeasePriority, StartedAt: isoTime(in.StartedAt),
		Milestones: []sparkMilestone{},
	}
	if sparkStateRE.MatchString(in.State) {
		out.State = in.State
	} else {
		out.State = "unknown"
	}
	if t := in.Train; t != nil {
		out.Train = &sparkTrain{Loss: finite(t.Loss), TokensPerSec: finite(t.TokensPerSec), LR: finite(t.LR), PeakMemGB: finite(t.PeakMemGB)}
	}
	if v := in.Valid; v != nil {
		out.Valid = &sparkValid{BF16: finite(v.BF16), Int4: finite(v.Int4), GapRel: finite(v.GapRel), Step: v.Step}
	}
	ms := in.Milestones
	if len(ms) > sparkMaxMilestones {
		ms = ms[len(ms)-sparkMaxMilestones:]
	}
	for _, m := range ms {
		out.Milestones = append(out.Milestones, sparkMilestone{Step: max(0, m.Step), Tokens: max(0, m.Tokens), At: isoTime(m.At), Kind: ident(m.Kind)})
	}
	return json.Marshal(out)
}

func (c *sparkCache) load() ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if time.Since(c.at) < sparkCacheTTL {
		return c.body, !c.missing
	}
	c.at = time.Now()
	c.body, c.missing = nil, true
	if c.path == "" {
		return nil, false
	}
	f, err := os.Open(c.path)
	if err != nil {
		return nil, false
	}
	defer f.Close()
	raw, err := io.ReadAll(io.LimitReader(f, sparkStatusMaxSize+1))
	if err != nil || len(raw) > sparkStatusMaxSize {
		return nil, false
	}
	body, err := sanitizeSpark(raw)
	if err != nil {
		return nil, false
	}
	c.body, c.missing = body, false
	return body, true
}

func (s *Server) labSpark(w http.ResponseWriter, r *http.Request) {
	body, ok := s.spark.load()
	if !ok {
		writeError(w, r, http.StatusNotFound, "not_found", "no Spark training status is published", 0)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "public, max-age=10")
	_, _ = w.Write(body)
}
