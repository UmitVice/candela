package market

import (
	"math"
)

func nanSlice(n int) []float64 {
	s := make([]float64, n)
	for i := range s {
		s[i] = math.NaN()
	}
	return s
}

func SMA(x []float64, n int) []float64 {
	out := nanSlice(len(x))
	if n <= 0 || len(x) < n {
		return out
	}
	sum := 0.0
	for i, v := range x {
		sum += v
		if i >= n {
			sum -= x[i-n]
		}
		if i >= n-1 {
			out[i] = sum / float64(n)
		}
	}
	return out
}

// EMA is seeded with the SMA of the first n defined values, as fixed by contracts/api.md.
func EMA(x []float64, n int) []float64 {
	out := nanSlice(len(x))
	start := 0
	for start < len(x) && math.IsNaN(x[start]) {
		start++
	}
	if n <= 0 || len(x)-start < n {
		return out
	}
	alpha := 2.0 / float64(n+1)
	sum := 0.0
	for i := start; i < start+n; i++ {
		sum += x[i]
	}
	prev := sum / float64(n)
	out[start+n-1] = prev
	for i := start + n; i < len(x); i++ {
		prev = alpha*x[i] + (1-alpha)*prev
		out[i] = prev
	}
	return out
}

func RSI(closes []float64, n int) []float64 {
	out := nanSlice(len(closes))
	if len(closes) <= n {
		return out
	}
	var gain, loss float64
	for i := 1; i <= n; i++ {
		d := closes[i] - closes[i-1]
		if d > 0 {
			gain += d
		} else {
			loss -= d
		}
	}
	avgG, avgL := gain/float64(n), loss/float64(n)
	out[n] = rsiValue(avgG, avgL)
	for i := n + 1; i < len(closes); i++ {
		d := closes[i] - closes[i-1]
		g, l := 0.0, 0.0
		if d > 0 {
			g = d
		} else {
			l = -d
		}
		avgG = (avgG*float64(n-1) + g) / float64(n)
		avgL = (avgL*float64(n-1) + l) / float64(n)
		out[i] = rsiValue(avgG, avgL)
	}
	return out
}

func rsiValue(g, l float64) float64 {
	if l == 0 {
		if g == 0 {
			return 50
		}
		return 100
	}
	return 100 - 100/(1+g/l)
}

func ATR(bars []Bar, n int) []float64 {
	out := nanSlice(len(bars))
	if len(bars) <= n {
		return out
	}
	tr := make([]float64, len(bars))
	for i := 1; i < len(bars); i++ {
		b, pc := bars[i], bars[i-1].C
		tr[i] = math.Max(b.H-b.L, math.Max(math.Abs(b.H-pc), math.Abs(b.L-pc)))
	}
	sum := 0.0
	for i := 1; i <= n; i++ {
		sum += tr[i]
	}
	prev := sum / float64(n)
	out[n] = prev
	for i := n + 1; i < len(bars); i++ {
		prev = (prev*float64(n-1) + tr[i]) / float64(n)
		out[i] = prev
	}
	return out
}

func Bollinger(closes []float64, n int, k float64) (upper, middle, lower []float64) {
	middle = SMA(closes, n)
	upper, lower = nanSlice(len(closes)), nanSlice(len(closes))
	for i := n - 1; i < len(closes); i++ {
		if math.IsNaN(middle[i]) {
			continue
		}
		var ss float64
		for j := i - n + 1; j <= i; j++ {
			d := closes[j] - middle[i]
			ss += d * d
		}
		sd := math.Sqrt(ss / float64(n))
		upper[i], lower[i] = middle[i]+k*sd, middle[i]-k*sd
	}
	return
}

func MACD(closes []float64) (macd, signal, hist []float64) {
	e12, e26 := EMA(closes, 12), EMA(closes, 26)
	macd = nanSlice(len(closes))
	for i := range closes {
		if !math.IsNaN(e12[i]) && !math.IsNaN(e26[i]) {
			macd[i] = e12[i] - e26[i]
		}
	}
	signal = EMA(macd, 9)
	hist = nanSlice(len(closes))
	for i := range closes {
		if !math.IsNaN(signal[i]) {
			hist[i] = macd[i] - signal[i]
		}
	}
	return
}

func popStd(x []float64) float64 {
	if len(x) == 0 {
		return math.NaN()
	}
	m := 0.0
	for _, v := range x {
		m += v
	}
	m /= float64(len(x))
	ss := 0.0
	for _, v := range x {
		ss += (v - m) * (v - m)
	}
	return math.Sqrt(ss / float64(len(x)))
}

func AnnualizedVolatility(bars []Bar) float64 {
	if len(bars) < 3 {
		return math.NaN()
	}
	r := make([]float64, 0, len(bars)-1)
	for i := 1; i < len(bars); i++ {
		if bars[i-1].C > 0 && bars[i].C > 0 {
			r = append(r, math.Log(bars[i].C/bars[i-1].C))
		}
	}
	return popStd(r) * math.Sqrt(252)
}

func MaxDrawdown(bars []Bar) float64 {
	peak, mdd := math.Inf(-1), 0.0
	for _, b := range bars {
		peak = math.Max(peak, b.C)
		if peak > 0 {
			mdd = math.Min(mdd, b.C/peak-1)
		}
	}
	return mdd
}

type indicatorSeries struct {
	sma20, sma50, sma200, ema12, ema26, rsi14, macd, macdSignal, macdHist, bbUpper, bbMiddle, bbLower, atr14 []float64
}

func computeSeries(bars []Bar) indicatorSeries {
	closes := make([]float64, len(bars))
	for i, b := range bars {
		closes[i] = b.C
	}
	var s indicatorSeries
	s.sma20, s.sma50, s.sma200 = SMA(closes, 20), SMA(closes, 50), SMA(closes, 200)
	s.ema12, s.ema26 = EMA(closes, 12), EMA(closes, 26)
	s.rsi14 = RSI(closes, 14)
	s.macd, s.macdSignal, s.macdHist = MACD(closes)
	s.bbUpper, s.bbMiddle, s.bbLower = Bollinger(closes, 20, 2)
	s.atr14 = ATR(bars, 14)
	return s
}

func ptr(v float64, dp int) *float64 {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return nil
	}
	r := Round(v, dp)
	return &r
}

func (s indicatorSeries) point(i int, t string) IndicatorPoint {
	return IndicatorPoint{
		T: t, SMA20: ptr(s.sma20[i], 4), SMA50: ptr(s.sma50[i], 4), SMA200: ptr(s.sma200[i], 4),
		EMA12: ptr(s.ema12[i], 4), EMA26: ptr(s.ema26[i], 4), RSI14: ptr(s.rsi14[i], 2),
		MACD: ptr(s.macd[i], 4), MACDSignal: ptr(s.macdSignal[i], 4), MACDHist: ptr(s.macdHist[i], 4),
		BBUpper: ptr(s.bbUpper[i], 4), BBMiddle: ptr(s.bbMiddle[i], 4), BBLower: ptr(s.bbLower[i], 4),
		ATR14: ptr(s.atr14[i], 4),
	}
}

func Round(v float64, dp int) float64 {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return v
	}
	p := math.Pow10(dp)
	r := math.Round(v*p) / p
	if r == 0 {
		return 0
	}
	return r
}
