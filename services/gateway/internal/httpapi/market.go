package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"

	"github.com/UmitVice/candela/services/gateway/internal/chat"
	"github.com/UmitVice/candela/services/gateway/internal/market"
	"github.com/UmitVice/candela/services/gateway/internal/store/db"
)

func symbolParam(w http.ResponseWriter, r *http.Request) (string, bool) {
	sym := strings.ToUpper(chi.URLParam(r, "symbol"))
	if !market.ValidSymbol(sym) {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "symbol must match ^[A-Z][A-Z0-9.\\-]{0,9}$", 0)
		return "", false
	}
	return sym, true
}

func (s *Server) marketError(w http.ResponseWriter, r *http.Request, sym string, err error) {
	var se *market.SourceError
	switch {
	case errors.As(err, &se):
		writeError(w, r, http.StatusNotFound, "not_found", se.Msg, 0)
	case errors.Is(err, market.ErrNotFound):
		writeError(w, r, http.StatusNotFound, "not_found", "unknown symbol "+sym, 0)
	case errors.Is(err, market.ErrInvalid):
		writeError(w, r, http.StatusBadRequest, "invalid_request", "invalid parameters", 0)
	default:
		s.log.Warn("market request failed", "requestId", RequestID(r), "symbol", sym, "err", err)
		writeError(w, r, http.StatusServiceUnavailable, "data_unavailable", "the market data provider is unavailable", 30000)
	}
}

func cache(w http.ResponseWriter, seconds int) {
	w.Header().Set("Cache-Control", "public, max-age="+strconv.Itoa(seconds))
}

func queryDefault(r *http.Request, key, def string) string {
	if v := r.URL.Query().Get(key); v != "" {
		return v
	}
	return def
}

func (s *Server) marketSearch(w http.ResponseWriter, r *http.Request) {
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if n := utf8.RuneCountInString(q); n < 1 || n > 64 {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "q must have 1..64 characters", 0)
		return
	}
	limit, err := strconv.Atoi(queryDefault(r, "limit", "10"))
	if err != nil || limit < 1 || limit > 20 {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "limit must be 1..20", 0)
		return
	}
	cache(w, 3600)
	writeJSON(w, http.StatusOK, map[string]any{"results": s.Market.Search(q, limit)})
}

func (s *Server) marketQuote(w http.ResponseWriter, r *http.Request) {
	sym, ok := symbolParam(w, r)
	if !ok {
		return
	}
	q, err := s.Market.Quote(r.Context(), sym)
	if err != nil {
		s.marketError(w, r, sym, err)
		return
	}
	cache(w, 300)
	writeJSON(w, http.StatusOK, q)
}

func (s *Server) marketHistory(w http.ResponseWriter, r *http.Request) {
	sym, ok := symbolParam(w, r)
	if !ok {
		return
	}
	rng := strings.ToUpper(queryDefault(r, "range", "1Y"))
	if !market.ValidHistoryRange(rng) {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "range must be one of 1M, 3M, 6M, 1Y, 2Y, 5Y", 0)
		return
	}
	h, err := s.Market.History(r.Context(), sym, rng)
	if err != nil {
		s.marketError(w, r, sym, err)
		return
	}
	cache(w, 3600)
	writeJSON(w, http.StatusOK, h)
}

func (s *Server) marketIndicators(w http.ResponseWriter, r *http.Request) {
	sym, ok := symbolParam(w, r)
	if !ok {
		return
	}
	rng := strings.ToUpper(queryDefault(r, "range", "1Y"))
	if !market.ValidIndicatorRange(rng) {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "range must be one of 6M, 1Y, 2Y", 0)
		return
	}
	ind, err := s.Market.Indicators(r.Context(), sym, rng)
	if err != nil {
		s.marketError(w, r, sym, err)
		return
	}
	cache(w, 3600)
	writeJSON(w, http.StatusOK, ind)
}

func (s *Server) marketFundamentals(w http.ResponseWriter, r *http.Request) {
	sym, ok := symbolParam(w, r)
	if !ok {
		return
	}
	period := queryDefault(r, "period", "annual")
	limit, err := strconv.Atoi(queryDefault(r, "limit", "4"))
	if (period != "annual" && period != "quarterly") || err != nil || limit < 1 || limit > 8 {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "period must be annual or quarterly and limit 1..8", 0)
		return
	}
	f, err := s.Market.Fundamentals(r.Context(), sym, period, limit)
	if err != nil {
		s.marketError(w, r, sym, err)
		return
	}
	cache(w, 3600)
	writeJSON(w, http.StatusOK, f)
}

func (s *Server) marketForecast(w http.ResponseWriter, r *http.Request) {
	sym, ok := symbolParam(w, r)
	if !ok {
		return
	}
	f, err := s.Market.Forecast(r.Context(), sym)
	if err != nil {
		s.marketError(w, r, sym, err)
		return
	}
	cache(w, 3600)
	writeJSON(w, http.StatusOK, f)
}

type feedbackRequest struct {
	ConversationID string               `json:"conversationId"`
	MessageID      string               `json:"messageId"`
	Rating         int                  `json:"rating"`
	Reason         string               `json:"reason"`
	ConsentToStore bool                 `json:"consentToStore"`
	Transcript     []chat.ClientMessage `json:"transcript"`
}

var messageIDRE = regexp.MustCompile(`^[A-Za-z0-9_\-]{1,64}$`)

func (s *Server) feedback(w http.ResponseWriter, r *http.Request) {
	var f feedbackRequest
	if !decodeJSON(w, r, &f) {
		return
	}
	probe := chat.Request{ConversationID: f.ConversationID, Messages: []chat.ClientMessage{{Role: "user", Content: "x"}}}
	switch {
	case probe.Validate() != nil:
		writeError(w, r, http.StatusBadRequest, "invalid_request", "conversationId must be a UUID v4", 0)
		return
	case !messageIDRE.MatchString(f.MessageID):
		writeError(w, r, http.StatusBadRequest, "invalid_request", "messageId is invalid", 0)
		return
	case f.Rating != 1 && f.Rating != -1:
		writeError(w, r, http.StatusBadRequest, "invalid_request", "rating must be 1 or -1", 0)
		return
	case utf8.RuneCountInString(f.Reason) > 500:
		writeError(w, r, http.StatusBadRequest, "invalid_request", "reason must have at most 500 characters", 0)
		return
	}
	var transcript sql.NullString
	if f.ConsentToStore && len(f.Transcript) > 0 {
		tr := chat.Request{ConversationID: f.ConversationID, Messages: f.Transcript}
		if len(f.Transcript) > 40 || validateTranscript(f.Transcript) != nil {
			writeError(w, r, http.StatusBadRequest, "invalid_request", "transcript must hold 1..40 valid messages", 0)
			return
		}
		b, _ := json.Marshal(tr.Messages)
		transcript = sql.NullString{String: string(b), Valid: true}
	}
	consent := int64(0)
	if f.ConsentToStore {
		consent = 1
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	_, err := s.Store.Q.InsertFeedback(ctx, db.InsertFeedbackParams{
		ConversationID: f.ConversationID, MessageID: f.MessageID, Rating: int64(f.Rating),
		Reason: sql.NullString{String: f.Reason, Valid: f.Reason != ""}, Consent: consent, Transcript: transcript,
		CreatedAt: time.Now().Unix(),
	})
	if err != nil {
		s.log.Error("feedback insert", "requestId", RequestID(r), "err", err)
		writeError(w, r, http.StatusInternalServerError, "internal", "could not store feedback", 0)
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]bool{"accepted": true})
}

func validateTranscript(msgs []chat.ClientMessage) error {
	for _, m := range msgs {
		if m.Role != "user" && m.Role != "assistant" {
			return errors.New("role")
		}
		if n := utf8.RuneCountInString(m.Content); n < 1 || n > 8000 {
			return errors.New("content")
		}
	}
	return nil
}

type executeRequest struct {
	Name      string          `json:"name"`
	Arguments json.RawMessage `json:"arguments"`
}

func (s *Server) toolsExecute(w http.ResponseWriter, r *http.Request) {
	var req executeRequest
	if !decodeJSON(w, r, &req) {
		return
	}
	if req.Name == "" {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "name is required", 0)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.cfg.ToolTimeout)
	defer cancel()
	res := s.Tools.Execute(ctx, req.Name, req.Arguments)
	resp := map[string]any{"modelView": res.ModelView, "uiView": res.UIView, "ok": res.OK, "summary": res.Summary}
	if !res.OK {
		resp["error"] = res.Code
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) systemPrompt(w http.ResponseWriter, r *http.Request) {
	day := time.Now()
	if v := r.URL.Query().Get("date"); v != "" {
		t, err := time.Parse("2006-01-02", v)
		if err != nil {
			writeError(w, r, http.StatusBadRequest, "invalid_request", "date must be YYYY-MM-DD", 0)
			return
		}
		day = t
	}
	writeJSON(w, http.StatusOK, map[string]string{"systemPrompt": chat.SystemPrompt(day)})
}
