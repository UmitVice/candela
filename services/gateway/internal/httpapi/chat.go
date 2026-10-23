package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/UmitVice/candela/services/gateway/internal/chat"
)

const (
	chatSubprotocol = "candela.chat.v1"
	keepAliveEvery  = 15 * time.Second
	streamWriteWait = 30 * time.Second
)

type sseEmitter struct {
	mu  sync.Mutex
	w   http.ResponseWriter
	rc  *http.ResponseController
	seq int
}

func (e *sseEmitter) Emit(event string, data any) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.seq++
	_ = e.rc.SetWriteDeadline(time.Now().Add(streamWriteWait))
	if _, err := fmt.Fprintf(e.w, "id: %d\nevent: %s\ndata: %s\n\n", e.seq, event, payload); err != nil {
		return err
	}
	return e.rc.Flush()
}

func (e *sseEmitter) keepAlive() error {
	e.mu.Lock()
	defer e.mu.Unlock()
	_ = e.rc.SetWriteDeadline(time.Now().Add(streamWriteWait))
	if _, err := e.w.Write([]byte(": keep-alive\n\n")); err != nil {
		return err
	}
	return e.rc.Flush()
}

func (s *Server) chatContext(parent context.Context) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithTimeout(parent, s.cfg.ChatTimeout)
	stop := context.AfterFunc(s.hardStop, cancel)
	return ctx, func() { stop(); cancel() }
}

func (s *Server) preflightChat(req *chat.Request) *chat.PlanError {
	if s.draining.Load() {
		return &chat.PlanError{Code: "upstream_unavailable", Message: "the gateway is restarting", Status: http.StatusServiceUnavailable}
	}
	if err := req.Validate(); err != nil {
		return &chat.PlanError{Code: "invalid_request", Message: err.Error(), Status: http.StatusBadRequest}
	}
	return nil
}

func (s *Server) chatStream(w http.ResponseWriter, r *http.Request) {
	var req chat.Request
	if !decodeJSON(w, r, &req) {
		return
	}
	if perr := s.preflightChat(&req); perr != nil {
		writeError(w, r, perr.Status, perr.Code, perr.Message, 0)
		return
	}
	route, model, err := s.Orchestrator.Plan(&req)
	if err != nil {
		var pe *chat.PlanError
		errors.As(err, &pe)
		writeError(w, r, pe.Status, pe.Code, pe.Message, 10000)
		return
	}
	h := w.Header()
	h.Set("Content-Type", "text/event-stream; charset=utf-8")
	h.Set("Cache-Control", "no-cache, no-transform")
	h.Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	em := &sseEmitter{w: w, rc: http.NewResponseController(w)}
	_ = em.rc.Flush()

	ctx, cancel := s.chatContext(r.Context())
	defer cancel()
	go func() {
		t := time.NewTicker(keepAliveEvery)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if em.keepAlive() != nil {
					cancel()
					return
				}
			}
		}
	}()
	s.Orchestrator.Run(ctx, RequestID(r), "sse", &req, route, model, em)
}

type wsEmitter struct {
	ctx  context.Context
	conn *websocket.Conn
	mu   sync.Mutex
	seq  int
}

func (e *wsEmitter) Emit(event string, data any) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.seq++
	b, err := json.Marshal(map[string]any{"type": "event", "id": e.seq, "event": event, "data": data})
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(e.ctx, 10*time.Second)
	defer cancel()
	return e.conn.Write(ctx, websocket.MessageText, b)
}

func offers(r *http.Request, proto string) bool {
	for _, v := range r.Header.Values("Sec-WebSocket-Protocol") {
		for p := range strings.SplitSeq(v, ",") {
			if strings.TrimSpace(p) == proto {
				return true
			}
		}
	}
	return false
}

type wsClientFrame struct {
	Type    string          `json:"type"`
	Request json.RawMessage `json:"request"`
}

func (s *Server) chatWS(w http.ResponseWriter, r *http.Request) {
	origin := r.Header.Get("Origin")
	if !slices.Contains(s.cfg.AllowedOrigins, origin) {
		writeError(w, r, http.StatusForbidden, "unauthorized", "origin not allowed", 0)
		return
	}
	if !offers(r, chatSubprotocol) {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "subprotocol "+chatSubprotocol+" required", 0)
		return
	}
	if s.draining.Load() {
		writeError(w, r, http.StatusServiceUnavailable, "upstream_unavailable", "the gateway is restarting", 10000)
		return
	}
	// The Origin header was checked against the allowlist above, including its scheme,
	// which the library's host-only pattern matching cannot express.
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{Subprotocols: []string{chatSubprotocol}, InsecureSkipVerify: true})
	if err != nil {
		return
	}
	conn.SetReadLimit(64 << 10)
	base, cancelBase := s.chatContext(context.WithoutCancel(r.Context()))
	defer cancelBase()

	startCtx, cancelStart := context.WithTimeout(base, 10*time.Second)
	typ, data, err := conn.Read(startCtx)
	cancelStart()
	if err != nil {
		_ = conn.Close(websocket.StatusPolicyViolation, "start frame expected within 10s")
		return
	}
	var first wsClientFrame
	if typ != websocket.MessageText || json.Unmarshal(data, &first) != nil || first.Type != "start" || len(first.Request) == 0 {
		_ = conn.Close(websocket.StatusPolicyViolation, "first frame must be a start message")
		return
	}
	var req chat.Request
	dec := json.NewDecoder(bytes.NewReader(first.Request))
	if err := dec.Decode(&req); err != nil {
		_ = conn.Close(websocket.StatusPolicyViolation, "invalid request")
		return
	}
	em := &wsEmitter{ctx: base, conn: conn}
	if perr := s.preflightChat(&req); perr != nil {
		_ = em.Emit("error", map[string]any{"code": perr.Code, "message": perr.Message})
		_ = conn.Close(websocket.StatusPolicyViolation, perr.Code)
		return
	}
	route, model, err := s.Orchestrator.Plan(&req)
	if err != nil {
		var pe *chat.PlanError
		errors.As(err, &pe)
		_ = em.Emit("error", map[string]any{"code": pe.Code, "message": pe.Message, "retryAfterMs": 10000})
		_ = conn.Close(websocket.StatusNormalClosure, "")
		return
	}

	runCtx, cancelRun := context.WithCancel(base)
	defer cancelRun()
	go func() {
		for {
			typ, data, err := conn.Read(base)
			if err != nil {
				cancelRun()
				return
			}
			var f wsClientFrame
			if typ != websocket.MessageText || json.Unmarshal(data, &f) != nil {
				_ = conn.Close(websocket.StatusPolicyViolation, "invalid frame")
				cancelRun()
				return
			}
			if f.Type == "cancel" {
				cancelRun()
			}
		}
	}()
	go func() {
		t := time.NewTicker(keepAliveEvery)
		defer t.Stop()
		for {
			select {
			case <-runCtx.Done():
				return
			case <-t.C:
				pctx, cancel := context.WithTimeout(runCtx, 10*time.Second)
				err := conn.Ping(pctx)
				cancel()
				if err != nil && runCtx.Err() == nil {
					cancelRun()
					return
				}
			}
		}
	}()
	s.Orchestrator.Run(runCtx, RequestID(r), "ws", &req, route, model, em)
	_ = conn.Close(websocket.StatusNormalClosure, "")
}
