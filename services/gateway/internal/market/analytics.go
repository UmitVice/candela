package market

import (
	"fmt"
	"math"
	"strconv"
	"time"
)

const dateLayout = "2006-01-02"

var historyRanges = map[string]bool{"1M": true, "3M": true, "6M": true, "1Y": true, "2Y": true, "5Y": true}
var indicatorRanges = map[string]bool{"6M": true, "1Y": true, "2Y": true}

func ValidHistoryRange(r string) bool   { return historyRanges[r] }
func ValidIndicatorRange(r string) bool { return indicatorRanges[r] }

func rangeStart(asOf string, r string) string {
	t, err := time.Parse(dateLayout, asOf)
	if err != nil {
		return asOf
	}
	switch r {
	case "1M":
		t = t.AddDate(0, -1, 0)
	case "3M":
		t = t.AddDate(0, -3, 0)
	case "6M":
		t = t.AddDate(0, -6, 0)
	case "1Y":
		t = t.AddDate(-1, 0, 0)
	case "2Y":
		t = t.AddDate(-2, 0, 0)
	case "5Y":
		t = t.AddDate(-5, 0, 0)
	}
	return t.Format(dateLayout)
}

func startIndex(bars []Bar, from string) int {
	for i, b := range bars {
		if b.T >= from {
			return i
		}
	}
	return len(bars)
}

func fmtNum(v float64, dp int) string {
	return strconv.FormatFloat(Round(v, dp), 'f', -1, 64)
}

func BuildQuote(info SymbolInfo, bars []Bar, source string) Quote {
	last := bars[len(bars)-1]
	prev := last.C
	if len(bars) > 1 {
		prev = bars[len(bars)-2].C
	}
	from := rangeStart(last.T, "1Y")
	hi, lo := math.Inf(-1), math.Inf(1)
	for _, b := range bars[startIndex(bars, from):] {
		hi, lo = math.Max(hi, b.H), math.Min(lo, b.L)
	}
	n := min(30, len(bars))
	vol := 0.0
	for _, b := range bars[len(bars)-n:] {
		vol += b.V
	}
	change := last.C - prev
	pct := 0.0
	if prev != 0 {
		pct = change / prev * 100
	}
	return Quote{
		Symbol: info.Symbol, Name: info.Name, Exchange: info.Exchange, Currency: "USD", AsOf: last.T,
		Close: Round(last.C, 4), PreviousClose: Round(prev, 4), Change: Round(change, 4), ChangePct: Round(pct, 2),
		Open: Round(last.O, 4), High: Round(last.H, 4), Low: Round(last.L, 4), Volume: math.Round(last.V),
		FiftyTwoWeekHigh: Round(hi, 4), FiftyTwoWeekLow: Round(lo, 4), AvgVolume30d: math.Round(vol / float64(n)),
		Source: source, Delayed: source != "live",
	}
}

func BuildHistory(symbol string, bars []Bar, r, source string) PriceHistory {
	asOf := bars[len(bars)-1].T
	window := bars[startIndex(bars, rangeStart(asOf, r)):]
	out := make([]Bar, len(window))
	for i, b := range window {
		out[i] = Bar{T: b.T, O: Round(b.O, 4), H: Round(b.H, 4), L: Round(b.L, 4), C: Round(b.C, 4), V: math.Round(b.V)}
	}
	return PriceHistory{Symbol: symbol, Range: r, Interval: "1d", Bars: out, Source: source, AsOf: asOf}
}

func BuildIndicators(symbol string, bars []Bar, r string) IndicatorSet {
	s := computeSeries(bars)
	last := len(bars) - 1
	asOf := bars[last].T
	from := startIndex(bars, rangeStart(asOf, r))
	series := make([]IndicatorPoint, 0, len(bars)-from)
	for i := from; i <= last; i++ {
		series = append(series, s.point(i, bars[i].T))
	}
	return IndicatorSet{
		Symbol:  symbol,
		Range:   r,
		AsOf:    asOf,
		Latest:  LatestIndicators{IndicatorPoint: s.point(last, asOf), Close: Round(bars[last].C, 4)},
		Series:  series,
		Signals: signals(bars, s),
	}
}

func lastCross(a, b []float64, end int) (idx int, up bool, found bool) {
	for i := end; i > 0; i-- {
		if math.IsNaN(a[i]) || math.IsNaN(b[i]) || math.IsNaN(a[i-1]) || math.IsNaN(b[i-1]) {
			return 0, false, false
		}
		prev, cur := a[i-1]-b[i-1], a[i]-b[i]
		if prev <= 0 && cur > 0 {
			return i, true, true
		}
		if prev >= 0 && cur < 0 {
			return i, false, true
		}
	}
	return 0, false, false
}

func firstDefined(a, b []float64, end int) int {
	i := end
	for i > 0 && !math.IsNaN(a[i-1]) && !math.IsNaN(b[i-1]) {
		i--
	}
	return i
}

func signals(bars []Bar, s indicatorSeries) []Signal {
	out := []Signal{}
	n := len(bars) - 1
	c := bars[n].C
	add := func(id, label, tone, detail string) {
		out = append(out, Signal{ID: id, Label: label, Tone: tone, Detail: detail})
	}
	if v := s.rsi14[n]; !math.IsNaN(v) {
		if v > 70 {
			add("rsi_overbought", "RSI overbought", "bearish", "RSI14 at "+fmtNum(v, 2)+" is above 70")
		} else if v < 30 {
			add("rsi_oversold", "RSI oversold", "bullish", "RSI14 at "+fmtNum(v, 2)+" is below 30")
		}
	}
	for _, ma := range []struct {
		name string
		v    float64
	}{{"SMA50", s.sma50[n]}, {"SMA200", s.sma200[n]}} {
		if math.IsNaN(ma.v) || ma.v == 0 {
			continue
		}
		diff := (c - ma.v) / ma.v * 100
		key := "sma50"
		if ma.name == "SMA200" {
			key = "sma200"
		}
		if c >= ma.v {
			add("price_above_"+key, "Above "+ma.name, "bullish", fmt.Sprintf("Close %s is %s%% above %s %s", fmtNum(c, 2), fmtNum(diff, 2), ma.name, fmtNum(ma.v, 2)))
		} else {
			add("price_below_"+key, "Below "+ma.name, "bearish", fmt.Sprintf("Close %s is %s%% below %s %s", fmtNum(c, 2), fmtNum(-diff, 2), ma.name, fmtNum(ma.v, 2)))
		}
	}
	if !math.IsNaN(s.sma50[n]) && !math.IsNaN(s.sma200[n]) {
		idx, up, found := lastCross(s.sma50, s.sma200, n)
		above := s.sma50[n] > s.sma200[n]
		switch {
		case found && n-idx < 20 && up:
			add("golden_cross_recent", "Golden cross", "bullish", "SMA50 crossed above SMA200 on "+bars[idx].T)
		case found && n-idx < 20 && !up:
			add("death_cross_recent", "Death cross", "bearish", "SMA50 crossed below SMA200 on "+bars[idx].T)
		case above:
			since := "since " + bars[firstDefined(s.sma50, s.sma200, n)].T
			if found {
				since = "since " + bars[idx].T
			}
			add("golden_cross_active", "Golden cross active", "bullish", "SMA50 above SMA200 "+since)
		default:
			since := "since " + bars[firstDefined(s.sma50, s.sma200, n)].T
			if found {
				since = "since " + bars[idx].T
			}
			add("death_cross_active", "Death cross active", "bearish", "SMA50 below SMA200 "+since)
		}
	}
	if !math.IsNaN(s.macdSignal[n]) {
		if idx, up, found := lastCross(s.macd, s.macdSignal, n); found && n-idx < 5 {
			if up {
				add("macd_bullish_cross", "MACD bullish cross", "bullish", "MACD crossed above its signal line on "+bars[idx].T)
			} else {
				add("macd_bearish_cross", "MACD bearish cross", "bearish", "MACD crossed below its signal line on "+bars[idx].T)
			}
		}
	}
	if u, l := s.bbUpper[n], s.bbLower[n]; !math.IsNaN(u) {
		if c > u {
			add("bb_upper_break", "Upper band break", "neutral", fmt.Sprintf("Close %s is above the upper Bollinger Band %s", fmtNum(c, 2), fmtNum(u, 2)))
		} else if c < l {
			add("bb_lower_break", "Lower band break", "neutral", fmt.Sprintf("Close %s is below the lower Bollinger Band %s", fmtNum(c, 2), fmtNum(l, 2)))
		}
	}
	if a := s.atr14[n]; !math.IsNaN(a) && c > 0 && a/c*100 > 4 {
		add("high_volatility", "High volatility", "neutral", "ATR14 is "+fmtNum(a/c*100, 2)+"% of the close")
	}
	return out
}

func BuildForecast(symbol string, bars []Bar) Forecast {
	last := bars[len(bars)-1]
	from := startIndex(bars, rangeStart(last.T, "5Y"))
	window := bars[max(0, from-1):]
	returns := make([]float64, 0, len(window))
	for i := 1; i < len(window); i++ {
		if window[i-1].C > 0 && window[i].C > 0 {
			returns = append(returns, math.Log(window[i].C/window[i-1].C))
		}
	}
	asOf, _ := time.Parse(dateLayout, last.T)
	horizons := blockBootstrap(returns, last.C, symbol, last.T)
	out := Forecast{
		Symbol: symbol, AsOf: last.T, BasePrice: Round(last.C, 4), Source: "baseline",
		Method:     "block bootstrap of 5y daily log returns",
		Disclaimer: "Statistical baseline from resampled historical returns. Not an analyst target, not a Vaniras forecast and not investment advice.",
	}
	for i, h := range horizons {
		m := 3 * (i + 1)
		out.Horizons = append(out.Horizons, Horizon{
			Months: m, TargetDate: asOf.AddDate(0, m, 0).Format(dateLayout),
			P10: Round(h[0], 4), P50: Round(h[1], 4), P90: Round(h[2], 4),
		})
	}
	return out
}
