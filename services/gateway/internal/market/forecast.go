package market

import (
	"hash/fnv"
	"math"
	"math/rand/v2"
	"slices"
)

const (
	bootstrapPaths = 5000
	bootstrapBlock = 20
	tradingMonth   = 21
)

// blockBootstrap returns [p10, p50, p90] prices for 3, 6, 9 and 12 months. The seed
// depends only on symbol and asOf so the same snapshot always yields the same bands.
func blockBootstrap(returns []float64, base float64, symbol, asOf string) [4][3]float64 {
	var out [4][3]float64
	if len(returns) < bootstrapBlock*2 || base <= 0 {
		for i := range out {
			out[i] = [3]float64{base, base, base}
		}
		return out
	}
	h := fnv.New64a()
	_, _ = h.Write([]byte(symbol + "|" + asOf))
	seed := h.Sum64()
	rng := rand.New(rand.NewPCG(seed, seed^0x9e3779b97f4a7c15)) //nolint:gosec // reproducible bootstrap, not a security context

	steps := [4]int{3 * tradingMonth, 6 * tradingMonth, 9 * tradingMonth, 12 * tradingMonth}
	finals := [4][]float64{}
	for i := range finals {
		finals[i] = make([]float64, bootstrapPaths)
	}
	maxStart := len(returns) - bootstrapBlock
	for p := range bootstrapPaths {
		cum, t, hi := 0.0, 0, 0
		for hi < len(steps) {
			start := rng.IntN(maxStart + 1)
			for j := start; j < start+bootstrapBlock && hi < len(steps); j++ {
				cum += returns[j]
				t++
				if t == steps[hi] {
					finals[hi][p] = base * math.Exp(cum)
					hi++
				}
			}
		}
	}
	for i := range finals {
		slices.Sort(finals[i])
		out[i] = [3]float64{quantile(finals[i], 0.1), quantile(finals[i], 0.5), quantile(finals[i], 0.9)}
	}
	return out
}

func quantile(sorted []float64, q float64) float64 {
	pos := q * float64(len(sorted)-1)
	lo := int(math.Floor(pos))
	hi := min(lo+1, len(sorted)-1)
	frac := pos - float64(lo)
	return sorted[lo]*(1-frac) + sorted[hi]*frac
}
