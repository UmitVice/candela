package ratelimit

import (
	"math"
	"sync"
	"time"

	lru "github.com/hashicorp/golang-lru/v2"
	"golang.org/x/time/rate"
)

type Limiter struct {
	name    string
	perMin  float64
	burst   int
	mu      sync.Mutex
	clients *lru.Cache[string, *rate.Limiter]
}

type Decision struct {
	Allowed    bool
	Limit      int
	Remaining  int
	ResetSec   int
	RetryAfter time.Duration
}

func New(name string, perMinute float64, burst, maxClients int) *Limiter {
	c, _ := lru.New[string, *rate.Limiter](maxClients)
	return &Limiter{name: name, perMin: perMinute, burst: burst, clients: c}
}

func (l *Limiter) Name() string { return l.name }

func (l *Limiter) Allow(key string) Decision {
	now := time.Now()
	l.mu.Lock()
	lim, ok := l.clients.Get(key)
	if !ok {
		lim = rate.NewLimiter(rate.Limit(l.perMin/60), l.burst)
		l.clients.Add(key, lim)
	}
	l.mu.Unlock()

	r := lim.ReserveN(now, 1)
	d := Decision{Limit: int(l.perMin)}
	delay := r.DelayFrom(now)
	if delay > 0 {
		r.CancelAt(now)
		d.RetryAfter = delay
		d.ResetSec = int(math.Ceil(delay.Seconds()))
		return d
	}
	d.Allowed = true
	tokens := lim.TokensAt(now)
	d.Remaining = max(0, int(math.Floor(tokens)))
	missing := float64(l.burst) - tokens
	d.ResetSec = int(math.Ceil(missing / (l.perMin / 60)))
	return d
}
