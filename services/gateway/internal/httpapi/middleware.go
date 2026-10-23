package httpapi

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/netip"
	"regexp"
	"runtime/debug"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/UmitVice/candela/services/gateway/internal/observability"
)

type ctxKey int

const (
	keyRequestID ctxKey = iota
	keyClientIP
)

var requestIDRE = regexp.MustCompile(`^[A-Za-z0-9-]{1,64}$`)

func RequestID(r *http.Request) string {
	v, _ := r.Context().Value(keyRequestID).(string)
	return v
}

func ClientIP(r *http.Request) string {
	v, _ := r.Context().Value(keyClientIP).(string)
	return v
}

func newRequestID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	h := hex.EncodeToString(b)
	return h[:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:]
}

func withRequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-Id")
		if !requestIDRE.MatchString(id) {
			id = newRequestID()
		}
		w.Header().Set("X-Request-Id", id)
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), keyRequestID, id)))
	})
}

type ipResolver struct {
	mode     string
	prefixes []netip.Prefix
}

// resolve never trusts forwarding headers unless the socket peer is a configured proxy:
// behind cloudflared every public request arrives from loopback, so the remote address
// alone says nothing about the client.
func (p ipResolver) resolve(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer, err := netip.ParseAddr(host)
	if err != nil {
		return host
	}
	peer = peer.Unmap()
	trusted := slices.ContainsFunc(p.prefixes, func(pr netip.Prefix) bool { return pr.Contains(peer) })
	if !trusted {
		return peer.String()
	}
	switch p.mode {
	case "cloudflare":
		if a, err := netip.ParseAddr(strings.TrimSpace(r.Header.Get("CF-Connecting-IP"))); err == nil {
			return a.Unmap().String()
		}
	case "xff":
		hops := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
		for i := len(hops) - 1; i >= 0; i-- {
			a, err := netip.ParseAddr(strings.TrimSpace(hops[i]))
			if err != nil {
				break
			}
			a = a.Unmap()
			if !slices.ContainsFunc(p.prefixes, func(pr netip.Prefix) bool { return pr.Contains(a) }) {
				return a.String()
			}
		}
	}
	return peer.String()
}

func withClientIP(res ipResolver) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), keyClientIP, res.resolve(r))))
		})
	}
}

func withRecover(log *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if v := recover(); v != nil {
					if err, ok := v.(error); ok && errors.Is(err, http.ErrAbortHandler) {
						panic(v)
					}
					log.Error("panic", "requestId", RequestID(r), "panic", v, "stack", string(debug.Stack()))
					writeError(w, r, http.StatusInternalServerError, "internal", "internal error", 0)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

var ipSalt = func() []byte {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return b
}()

// hashIP keeps access logs useful for spotting abuse without storing visitor addresses.
func hashIP(ip string) string {
	h := sha256.Sum256(append(append([]byte{}, ipSalt...), ip...))
	return hex.EncodeToString(h[:6])
}

func withAccessLog(listener string, log *slog.Logger, m *observability.Metrics) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r)
			route := chi.RouteContext(r.Context()).RoutePattern()
			if route == "" {
				route = "unmatched"
			}
			status := ww.Status()
			if status == 0 {
				status = http.StatusOK
			}
			d := time.Since(start)
			m.HTTPRequests.WithLabelValues(listener, route, r.Method, strconv.Itoa(status/100)+"xx").Inc()
			if !strings.Contains(route, "/chat/") && !strings.Contains(route, "/worker/") {
				m.HTTPDuration.WithLabelValues(listener, route).Observe(d.Seconds())
			}
			log.Info("http", "listener", listener, "requestId", RequestID(r), "method", r.Method, "route", route,
				"status", status, "bytes", ww.BytesWritten(), "durationMs", d.Milliseconds(), "client", hashIP(ClientIP(r)))
		})
	}
}

func withSecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
		h.Set("Cross-Origin-Resource-Policy", "cross-origin")
		h.Set("Permissions-Policy", "interest-cohort=()")
		next.ServeHTTP(w, r)
	})
}

func withCORS(allowed []string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			h := w.Header()
			h.Add("Vary", "Origin")
			if origin != "" && slices.Contains(allowed, origin) {
				h.Set("Access-Control-Allow-Origin", origin)
				h.Set("Access-Control-Expose-Headers", "X-Request-Id, Retry-After, RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset")
				if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
					h.Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
					h.Set("Access-Control-Allow-Headers", "Content-Type, X-Request-Id")
					h.Set("Access-Control-Max-Age", "600")
					w.WriteHeader(http.StatusNoContent)
					return
				}
			} else if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

func withBodyLimit(n int64) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			r.Body = http.MaxBytesReader(w, r.Body, n)
			next.ServeHTTP(w, r)
		})
	}
}

// withDeadline bounds handler work and the response write for non-streaming routes.
func withDeadline(d time.Duration) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx, cancel := context.WithTimeout(r.Context(), d)
			defer cancel()
			_ = http.NewResponseController(w).SetWriteDeadline(time.Now().Add(d + 5*time.Second))
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
