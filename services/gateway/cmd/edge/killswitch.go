package main

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const scrapeEvery = 15 * time.Second

type abuseSample struct {
	at     time.Time
	counts map[string]float64
}

type killSwitch struct {
	url        string
	token      string
	window     time.Duration
	thresholds map[string]float64
	client     *http.Client
	samples    []abuseSample
}

func newKillSwitch(cfg *config) *killSwitch {
	return &killSwitch{
		url: "http://" + internalAddr + "/metrics", token: cfg.MetricsToken, window: cfg.KillWindow,
		thresholds: map[string]float64{
			"rate_limited": cfg.KillRateLimited, "oversized": cfg.KillOversized, "origin": cfg.KillOrigin,
			"protocol": cfg.KillProtocol, "invalid": cfg.KillInvalid,
		},
		client: &http.Client{Timeout: 5 * time.Second},
	}
}

// scrape reads the gateway's abuse counters from the internal listener.
func (k *killSwitch) scrape(ctx context.Context) (map[string]float64, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, k.url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+k.token)
	resp, err := k.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("metrics: HTTP %d", resp.StatusCode)
	}
	counts := map[string]float64{}
	sc := bufio.NewScanner(io.LimitReader(resp.Body, 4<<20))
	sc.Buffer(make([]byte, 64<<10), 64<<10)
	for sc.Scan() {
		line := sc.Text()
		var kind string
		switch {
		case strings.HasPrefix(line, "candela_rate_limited_total{"):
			kind = "rate_limited"
		case strings.HasPrefix(line, `candela_abuse_total{kind="`):
			kind = strings.TrimPrefix(line, `candela_abuse_total{kind="`)
			kind, _, _ = strings.Cut(kind, `"`)
		default:
			continue
		}
		v, err := strconv.ParseFloat(line[strings.LastIndexByte(line, ' ')+1:], 64)
		if err == nil {
			counts[kind] += v
		}
	}
	return counts, sc.Err()
}

// observe records a sample and returns the first counter whose increase over the window
// exceeds its threshold. A counter that went down means the gateway restarted.
func (k *killSwitch) observe(now time.Time, counts map[string]float64) (string, float64) {
	if n := len(k.samples); n > 0 {
		for kind, v := range k.samples[n-1].counts {
			if counts[kind] < v {
				k.samples = nil
				break
			}
		}
	}
	k.samples = append(k.samples, abuseSample{at: now, counts: counts})
	cut := 0
	for cut < len(k.samples)-1 && now.Sub(k.samples[cut+1].at) >= k.window {
		cut++
	}
	k.samples = k.samples[cut:]
	base := k.samples[0]
	for kind, limit := range k.thresholds {
		if d := counts[kind] - base.counts[kind]; limit > 0 && d > limit {
			return kind, d
		}
	}
	return "", 0
}

func (k *killSwitch) reset() { k.samples = nil }
