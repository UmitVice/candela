package workerhub

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
)

const (
	Protocol      = "candela.worker.v1"
	heartbeat     = 15 * time.Second
	pongWait      = 5 * time.Second
	helloWait     = 10 * time.Second
	writeWait     = 10 * time.Second
	maxFrameBytes = 1 << 20
)

type Hub struct {
	token    []byte
	log      *slog.Logger
	metrics  *observability.Metrics
	onChange func()

	mu       sync.Mutex
	workers  map[string]*Worker
	draining bool
}

func New(token string, log *slog.Logger, m *observability.Metrics) *Hub {
	return &Hub{token: []byte(token), log: log, metrics: m, workers: map[string]*Worker{}, onChange: func() {}}
}

func (h *Hub) OnChange(f func()) { h.onChange = f }

func (h *Hub) Enabled() bool { return len(h.token) > 0 }

type WorkerStatus struct {
	ID          string `json:"id"`
	ModelID     string `json:"modelId"`
	State       string `json:"state"`
	ConnectedAt string `json:"connectedAt"`
	Device      string `json:"device,omitempty"`
}

func (h *Hub) Workers() []*Worker {
	h.mu.Lock()
	defer h.mu.Unlock()
	out := make([]*Worker, 0, len(h.workers))
	for _, w := range h.workers {
		out = append(out, w)
	}
	slices.SortFunc(out, func(a, b *Worker) int { return a.ConnectedAt.Compare(b.ConnectedAt) })
	return out
}

func (h *Hub) Status() []WorkerStatus {
	ws := h.Workers()
	out := make([]WorkerStatus, 0, len(ws))
	for _, w := range ws {
		out = append(out, w.Status())
	}
	return out
}

func (h *Hub) Drain(ctx context.Context) {
	h.mu.Lock()
	h.draining = true
	ws := make([]*Worker, 0, len(h.workers))
	for _, w := range h.workers {
		ws = append(ws, w)
	}
	h.mu.Unlock()
	for _, w := range ws {
		w.markDraining()
		if err := w.send(ctx, map[string]any{"type": "drain"}); err != nil {
			h.log.Warn("drain worker", "worker", w.WorkerID, "err", err)
		}
	}
	h.onChange()
}

func (h *Hub) Close() {
	for _, w := range h.Workers() {
		_ = w.conn.Close(websocket.StatusGoingAway, "gateway shutting down")
	}
}

func (h *Hub) authorized(r *http.Request) bool {
	if len(h.token) == 0 {
		return false
	}
	got, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
	if !ok {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(strings.TrimSpace(got)), h.token) == 1
}

func offersProtocol(r *http.Request) bool {
	for _, v := range r.Header.Values("Sec-WebSocket-Protocol") {
		for p := range strings.SplitSeq(v, ",") {
			if strings.TrimSpace(p) == Protocol {
				return true
			}
		}
	}
	return false
}

type hello struct {
	Type           string          `json:"type"`
	Protocol       string          `json:"protocol"`
	WorkerID       string          `json:"workerId"`
	Version        string          `json:"version"`
	Device         string          `json:"device"`
	MaxConcurrency int             `json:"maxConcurrency"`
	Models         []llm.ModelInfo `json:"models"`
}

func (h *Hub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if !h.authorized(r) {
		http.Error(w, `{"error":{"code":"unauthorized","message":"invalid worker token"}}`, http.StatusUnauthorized)
		return
	}
	if !offersProtocol(r) {
		http.Error(w, `{"error":{"code":"invalid_request","message":"subprotocol candela.worker.v1 required"}}`, http.StatusBadRequest)
		return
	}
	// Workers are not browsers: the bearer token authenticates them, and browsers cannot
	// attach an Authorization header to a WebSocket handshake, so Origin checks add nothing.
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{Subprotocols: []string{Protocol}, InsecureSkipVerify: true})
	if err != nil {
		h.log.Warn("worker upgrade failed", "err", err)
		return
	}
	conn.SetReadLimit(maxFrameBytes)
	ctx, cancel := context.WithCancel(context.WithoutCancel(r.Context()))
	defer cancel()

	hctx, hcancel := context.WithTimeout(ctx, helloWait)
	_, data, err := conn.Read(hctx)
	hcancel()
	if err != nil {
		_ = conn.Close(websocket.StatusPolicyViolation, "hello expected")
		return
	}
	var hi hello
	if err := json.Unmarshal(data, &hi); err != nil || hi.Type != "hello" || hi.Protocol != Protocol {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid hello")
		return
	}
	if err := validateHello(&hi); err != nil {
		_ = conn.Close(websocket.StatusPolicyViolation, err.Error())
		return
	}
	h.mu.Lock()
	if h.draining {
		h.mu.Unlock()
		_ = conn.Close(websocket.StatusTryAgainLater, "gateway draining")
		return
	}
	wk := &Worker{
		hub: h, conn: conn, SessionID: "ws_" + randomID(), WorkerID: hi.WorkerID, Version: hi.Version,
		Device: hi.Device, MaxConcurrency: hi.MaxConcurrency, Models: hi.Models, ConnectedAt: time.Now().UTC(),
		state: "idle", jobs: map[string]*job{}, closed: make(chan struct{}), pending: map[int64]time.Time{},
	}
	h.workers[wk.SessionID] = wk
	h.metrics.Workers.Set(float64(len(h.workers)))
	h.mu.Unlock()

	log := h.log.With("worker", wk.WorkerID, "session", wk.SessionID)
	if err := wk.send(ctx, map[string]any{"type": "welcome", "sessionId": wk.SessionID, "heartbeatSec": int(heartbeat.Seconds())}); err != nil {
		log.Warn("welcome failed", "err", err)
		h.remove(wk, "welcome failed")
		return
	}
	log.Info("worker connected", "device", wk.Device, "version", wk.Version, "models", len(wk.Models), "maxConcurrency", wk.MaxConcurrency)
	h.onChange()

	go wk.heartbeat(ctx, cancel, log)
	reason := wk.readLoop(ctx, log)
	cancel()
	h.remove(wk, reason)
	log.Info("worker disconnected", "reason", reason)
}

func validateHello(hi *hello) error {
	if hi.WorkerID == "" || len(hi.WorkerID) > 64 {
		return errors.New("workerId must have 1..64 characters")
	}
	if len(hi.Device) > 64 {
		hi.Device = hi.Device[:64]
	}
	if hi.MaxConcurrency < 1 || hi.MaxConcurrency > 8 {
		return errors.New("maxConcurrency must be 1..8")
	}
	if len(hi.Models) == 0 || len(hi.Models) > 8 {
		return errors.New("models must list 1..8 entries")
	}
	for i := range hi.Models {
		m := &hi.Models[i]
		if m.ID == "" || len(m.ID) > 64 {
			return errors.New("model id must have 1..64 characters")
		}
		if m.Tier == "" {
			m.Tier = "pro"
		}
		m.Host = "local-gpu-worker"
		if m.Runtime == "" {
			m.Runtime = "mlx"
		}
	}
	return nil
}

func (h *Hub) remove(w *Worker, reason string) {
	h.mu.Lock()
	delete(h.workers, w.SessionID)
	h.metrics.Workers.Set(float64(len(h.workers)))
	h.mu.Unlock()
	w.failAll(reason)
	_ = w.conn.Close(websocket.StatusNormalClosure, "")
	h.onChange()
}

func randomID() string {
	b := make([]byte, 9)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

type Worker struct {
	hub            *Hub
	conn           *websocket.Conn
	SessionID      string
	WorkerID       string
	Version        string
	Device         string
	MaxConcurrency int
	Models         []llm.ModelInfo
	ConnectedAt    time.Time

	writeMu sync.Mutex

	mu       sync.Mutex
	state    string
	loaded   string
	memoryMb int
	draining bool
	jobs     map[string]*job
	pending  map[int64]time.Time
	misses   int
	closed   chan struct{}
	gone     bool
}

func (w *Worker) Status() WorkerStatus {
	w.mu.Lock()
	defer w.mu.Unlock()
	state := w.state
	if w.draining {
		state = "draining"
	} else if len(w.jobs) > 0 {
		state = "busy"
	}
	model := w.loaded
	if model == "" && len(w.Models) > 0 {
		model = w.Models[0].ID
	}
	// Worker ids are often hostnames, so /status shows an opaque session-derived id instead.
	return WorkerStatus{ID: "w-" + strings.TrimPrefix(w.SessionID, "ws_")[:8], ModelID: model, State: state,
		ConnectedAt: w.ConnectedAt.Format(time.RFC3339), Device: w.Device}
}

func (w *Worker) Healthy() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return !w.gone && !w.draining && w.state != "draining" && w.misses == 0
}

func (w *Worker) markDraining() {
	w.mu.Lock()
	w.draining = true
	w.mu.Unlock()
}

func (w *Worker) send(ctx context.Context, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, writeWait)
	defer cancel()
	w.writeMu.Lock()
	defer w.writeMu.Unlock()
	return w.conn.Write(ctx, websocket.MessageText, b)
}

func (w *Worker) heartbeat(ctx context.Context, cancel context.CancelFunc, log *slog.Logger) {
	t := time.NewTicker(heartbeat)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		ts := time.Now().UnixMilli()
		w.mu.Lock()
		w.pending[ts] = time.Now()
		w.mu.Unlock()
		if err := w.send(ctx, map[string]any{"type": "ping", "ts": ts}); err != nil {
			log.Warn("ping failed", "err", err)
			cancel()
			return
		}
		pctx, pcancel := context.WithTimeout(ctx, pongWait)
		_ = w.conn.Ping(pctx)
		pcancel()
		time.AfterFunc(pongWait, func() {
			w.mu.Lock()
			_, missed := w.pending[ts]
			if missed {
				delete(w.pending, ts)
				w.misses++
			}
			misses := w.misses
			w.mu.Unlock()
			if missed {
				log.Warn("worker missed pong", "misses", misses)
				w.hub.onChange()
			}
			if misses >= 2 {
				cancel()
			}
		})
	}
}

type inbound struct {
	Type          string          `json:"type"`
	TS            int64           `json:"ts"`
	State         string          `json:"state"`
	LoadedModelID string          `json:"loadedModelId"`
	MemoryMb      int             `json:"memoryMb"`
	JobID         string          `json:"jobId"`
	Seq           int             `json:"seq"`
	Event         string          `json:"event"`
	Data          json.RawMessage `json:"data"`
}

func (w *Worker) readLoop(ctx context.Context, log *slog.Logger) string {
	for {
		typ, data, err := w.conn.Read(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return "heartbeat timeout or shutdown"
			}
			return fmt.Sprintf("read: %v", websocket.CloseStatus(err))
		}
		if typ != websocket.MessageText {
			return "binary frame"
		}
		var m inbound
		if err := json.Unmarshal(data, &m); err != nil {
			log.Warn("invalid worker frame")
			continue
		}
		switch m.Type {
		case "pong":
			w.mu.Lock()
			delete(w.pending, m.TS)
			recovered := w.misses > 0
			w.misses = 0
			w.mu.Unlock()
			if recovered {
				w.hub.onChange()
			}
		case "status":
			w.mu.Lock()
			if m.State == "idle" || m.State == "busy" || m.State == "draining" {
				w.state = m.State
			}
			w.loaded, w.memoryMb = m.LoadedModelID, m.MemoryMb
			w.mu.Unlock()
			w.hub.onChange()
		case "event":
			w.route(m)
		default:
			log.Debug("ignored worker frame", "type", m.Type)
		}
	}
}
