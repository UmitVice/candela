package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/UmitVice/candela/services/gateway/internal/ratelimit"
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func writeError(w http.ResponseWriter, r *http.Request, status int, code, msg string, retryAfterMs int64) {
	body := map[string]any{"code": code, "message": msg, "requestId": RequestID(r)}
	if retryAfterMs > 0 {
		body["retryAfterMs"] = retryAfterMs
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, status, map[string]any{"error": body})
}

func decodeJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(v); err != nil {
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			writeError(w, r, http.StatusRequestEntityTooLarge, "invalid_request", "request body too large", 0)
			return false
		}
		writeError(w, r, http.StatusBadRequest, "invalid_request", "request body must be valid JSON", 0)
		return false
	}
	if dec.More() {
		writeError(w, r, http.StatusBadRequest, "invalid_request", "request body must contain one JSON object", 0)
		return false
	}
	return true
}

func setRateHeaders(w http.ResponseWriter, d ratelimit.Decision) {
	h := w.Header()
	h.Set("RateLimit-Limit", strconv.Itoa(d.Limit))
	h.Set("RateLimit-Remaining", strconv.Itoa(d.Remaining))
	h.Set("RateLimit-Reset", strconv.Itoa(d.ResetSec))
}

func (s *Server) limit(l *ratelimit.Limiter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method == http.MethodOptions {
				next.ServeHTTP(w, r)
				return
			}
			d := l.Allow(ClientIP(r))
			setRateHeaders(w, d)
			if !d.Allowed {
				s.metrics.RateLimited.WithLabelValues(l.Name()).Inc()
				w.Header().Set("Retry-After", strconv.Itoa(max(1, d.ResetSec)))
				writeError(w, r, http.StatusTooManyRequests, "rate_limited", "too many requests", d.RetryAfter.Milliseconds())
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
