package chat

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/llm"
	"github.com/UmitVice/candela/services/gateway/internal/observability"
	"github.com/UmitVice/candela/services/gateway/internal/workerhub"
)

var (
	ErrOverloaded   = errors.New("overloaded")
	ErrUnavailable  = errors.New("no model upstream is available")
	ErrUnknownModel = errors.New("unknown model")
)

type Fallback struct {
	Model       llm.ModelInfo
	Upstream    llm.Upstream
	Concurrency int
	Healthy     func() bool
}

type target struct {
	key      string
	route    string
	model    llm.ModelInfo
	upstream llm.Upstream
	capacity int
}

type Lease struct {
	Route    string
	Model    llm.ModelInfo
	Upstream llm.Upstream
	release  func()
}

func (l *Lease) Release() {
	if l != nil && l.release != nil {
		l.release()
		l.release = nil
	}
}

type waiter struct {
	route   string
	modelID string
	ready   chan *Lease
	pos     chan int
	fail    chan error
}

type Scheduler struct {
	hub       *workerhub.Hub
	fallback  *Fallback
	globalCap int
	maxDepth  int
	metrics   *observability.Metrics

	mu       sync.Mutex
	inflight map[string]int
	total    int
	queue    []*waiter
	avgGenMs float64
}

func NewScheduler(hub *workerhub.Hub, fb *Fallback, globalCap, maxDepth int, m *observability.Metrics) *Scheduler {
	s := &Scheduler{hub: hub, fallback: fb, globalCap: globalCap, maxDepth: maxDepth, metrics: m,
		inflight: map[string]int{}, avgGenMs: 20000}
	hub.OnChange(s.dispatch)
	return s
}

func (s *Scheduler) targets() []target {
	var out []target
	for _, w := range s.hub.Workers() {
		if !w.Healthy() {
			continue
		}
		for _, m := range w.Models {
			out = append(out, target{key: "worker:" + w.SessionID, route: "worker", model: m, upstream: w, capacity: w.MaxConcurrency})
		}
	}
	if s.fallback != nil && s.fallback.Concurrency > 0 && s.fallback.Healthy() {
		out = append(out, target{key: "fallback", route: "fallback", model: s.fallback.Model, upstream: s.fallback.Upstream, capacity: s.fallback.Concurrency})
	}
	return out
}

func (s *Scheduler) capacityLimit() int {
	if s.globalCap > 0 {
		return s.globalCap
	}
	return 1 << 30
}

func (s *Scheduler) free(t target) bool {
	return s.inflight[t.key] < t.capacity && s.total < s.capacityLimit()
}

// Route answers where a request would go now; 'auto' prefers a healthy idle worker and
// otherwise the fallback, as fixed in docs/plan/p1-gateway.md.
func (s *Scheduler) Route() string {
	route, _, err := s.Resolve("auto")
	if err != nil {
		return "unavailable"
	}
	return route
}

func (s *Scheduler) Resolve(model string) (route string, info llm.ModelInfo, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ts := s.targets()
	if model == "" || model == "auto" {
		var anyWorker *target
		for i, t := range ts {
			if t.route == "worker" {
				if s.free(t) {
					return "worker", t.model, nil
				}
				if anyWorker == nil {
					anyWorker = &ts[i]
				}
			}
		}
		for _, t := range ts {
			if t.route == "fallback" {
				return "fallback", t.model, nil
			}
		}
		if anyWorker != nil {
			return "worker", anyWorker.model, nil
		}
		return "", llm.ModelInfo{}, ErrUnavailable
	}
	for _, t := range ts {
		if t.model.ID == model {
			return t.route, t.model, nil
		}
	}
	if s.fallback != nil && s.fallback.Model.ID == model {
		return "", llm.ModelInfo{}, ErrUnavailable
	}
	return "", llm.ModelInfo{}, ErrUnknownModel
}

func (s *Scheduler) Models() []llm.ModelInfo {
	s.mu.Lock()
	defer s.mu.Unlock()
	seen := map[string]bool{}
	var out []llm.ModelInfo
	for _, t := range s.targets() {
		if !seen[t.model.ID] {
			seen[t.model.ID] = true
			out = append(out, t.model)
		}
	}
	return out
}

func (s *Scheduler) QueueDepth() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.queue)
}

func (s *Scheduler) MaxDepth() int { return s.maxDepth }

func (s *Scheduler) ETA(position int) float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	slots := 0
	for _, t := range s.targets() {
		slots += t.capacity
	}
	slots = max(1, min(slots, s.capacityLimit()))
	return s.avgGenMs * float64(position) / float64(slots)
}

func (s *Scheduler) ObserveDuration(d time.Duration) {
	s.mu.Lock()
	s.avgGenMs = 0.8*s.avgGenMs + 0.2*float64(d.Milliseconds())
	s.mu.Unlock()
}

func (s *Scheduler) matches(w *waiter, t target) bool {
	if t.route != w.route {
		return false
	}
	return w.modelID == "" || t.model.ID == w.modelID
}

func (s *Scheduler) lease(t target) *Lease {
	s.inflight[t.key]++
	s.total++
	var once sync.Once
	return &Lease{Route: t.route, Model: t.model, Upstream: t.upstream, release: func() {
		once.Do(func() {
			s.mu.Lock()
			s.inflight[t.key]--
			if s.inflight[t.key] <= 0 {
				delete(s.inflight, t.key)
			}
			s.total--
			s.mu.Unlock()
			s.dispatch()
		})
	}}
}

// Acquire waits in a bounded FIFO for a slot on the given route; modelID narrows the
// choice to one model. Position updates arrive on onQueue.
func (s *Scheduler) Acquire(ctx context.Context, route, modelID string, onQueue func(position int)) (*Lease, error) {
	s.mu.Lock()
	if len(s.queue) == 0 {
		for _, t := range s.targets() {
			if t.route == route && (modelID == "" || t.model.ID == modelID) && s.free(t) {
				l := s.lease(t)
				s.mu.Unlock()
				return l, nil
			}
		}
	}
	if len(s.queue) >= s.maxDepth {
		s.mu.Unlock()
		return nil, ErrOverloaded
	}
	w := &waiter{route: route, modelID: modelID, ready: make(chan *Lease, 1), pos: make(chan int, 1), fail: make(chan error, 1)}
	s.queue = append(s.queue, w)
	s.metrics.QueueDepth.Set(float64(len(s.queue)))
	s.notifyPositions()
	s.mu.Unlock()
	s.dispatch()

	for {
		select {
		case l := <-w.ready:
			return l, nil
		case p := <-w.pos:
			onQueue(p)
		case err := <-w.fail:
			return nil, err
		case <-ctx.Done():
			s.mu.Lock()
			for i, q := range s.queue {
				if q == w {
					s.queue = append(s.queue[:i], s.queue[i+1:]...)
					break
				}
			}
			s.metrics.QueueDepth.Set(float64(len(s.queue)))
			s.notifyPositions()
			s.mu.Unlock()
			select {
			case l := <-w.ready:
				l.Release()
			default:
			}
			return nil, ctx.Err()
		}
	}
}

func (s *Scheduler) notifyPositions() {
	for i, w := range s.queue {
		select {
		case <-w.pos:
		default:
		}
		w.pos <- i + 1
	}
}

func (s *Scheduler) dispatch() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.queue) == 0 {
		return
	}
	ts := s.targets()
	changed := false
	for i := 0; i < len(s.queue); {
		w := s.queue[i]
		var picked *target
		exists := false
		for j := range ts {
			if s.matches(w, ts[j]) {
				exists = true
				if s.free(ts[j]) {
					picked = &ts[j]
					break
				}
			}
		}
		if !exists {
			w.fail <- ErrUnavailable
			s.queue = append(s.queue[:i], s.queue[i+1:]...)
			changed = true
			continue
		}
		if picked == nil {
			i++
			continue
		}
		w.ready <- s.lease(*picked)
		s.queue = append(s.queue[:i], s.queue[i+1:]...)
		changed = true
	}
	if changed {
		s.metrics.QueueDepth.Set(float64(len(s.queue)))
		s.notifyPositions()
	}
}

func (s *Scheduler) Refresh() { s.dispatch() }
