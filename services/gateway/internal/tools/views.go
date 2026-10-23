package tools

import (
	"context"
	"fmt"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/market"
)

func signed(v float64) string {
	s := formatNum(v, 2)
	if v > 0 {
		return "+" + s
	}
	return s
}

func (r *Registry) searchSymbols(_ context.Context, args map[string]any) (Result, error) {
	q, limit := argString(args, "query"), argInt(args, "limit")
	results := r.market.Search(q, limit)
	build := func(keep int) []byte {
		items := make([][]byte, 0, keep)
		for _, s := range results[:keep] {
			items = append(items, newObj().str("symbol", s.Symbol).str("name", s.Name).str("exchange", s.Exchange).bytes())
		}
		return newObj().str("query", q).raw("results", array(items)).bytes()
	}
	return Result{
		ModelView: fit(build, len(results)),
		UIView:    map[string]any{"kind": "symbols", "results": results},
		Summary:   fmt.Sprintf("%d match(es) for %q", len(results), q),
	}, nil
}

func (r *Registry) getQuote(ctx context.Context, args map[string]any) (Result, error) {
	q, err := r.market.Quote(ctx, argString(args, "symbol"))
	if err != nil {
		return Result{}, err
	}
	mv := newObj().str("symbol", q.Symbol).str("name", q.Name).str("asOf", q.AsOf).
		num("close", q.Close, 2).num("changePct", q.ChangePct, 2).num("open", q.Open, 2).
		num("high", q.High, 2).num("low", q.Low, 2).integer("volume", q.Volume).
		num("fiftyTwoWeekHigh", q.FiftyTwoWeekHigh, 2).num("fiftyTwoWeekLow", q.FiftyTwoWeekLow, 2).
		integer("avgVolume30d", q.AvgVolume30d).str("source", q.Source).boolean("delayed", q.Delayed).bytes()
	return Result{
		ModelView: string(mv),
		UIView:    map[string]any{"kind": "quote", "quote": q},
		Summary:   fmt.Sprintf("%s %s (%s%%) · %s", q.Symbol, formatNum(q.Close, 2), signed(q.ChangePct), q.AsOf),
	}, nil
}

func periodCloses(bars []market.Bar, monthly bool) []float64 {
	var out []float64
	lastKey := ""
	for _, b := range bars {
		t, err := time.Parse("2006-01-02", b.T)
		if err != nil {
			continue
		}
		var key string
		if monthly {
			key = b.T[:7]
		} else {
			y, w := t.ISOWeek()
			key = fmt.Sprintf("%d-%02d", y, w)
		}
		if key == lastKey && len(out) > 0 {
			out[len(out)-1] = b.C
		} else {
			out = append(out, b.C)
		}
		lastKey = key
	}
	return out
}

func (r *Registry) getPriceHistory(ctx context.Context, args map[string]any) (Result, error) {
	h, err := r.market.History(ctx, argString(args, "symbol"), argString(args, "range"))
	if err != nil {
		return Result{}, err
	}
	bars := h.Bars
	if len(bars) == 0 {
		return Result{}, &market.SourceError{Err: market.ErrUnavailable, Msg: "no bars in the requested range"}
	}
	first, last := bars[0], bars[len(bars)-1]
	hi, lo := bars[0], bars[0]
	vol := 0.0
	for _, b := range bars {
		if b.H > hi.H {
			hi = b
		}
		if b.L < lo.L {
			lo = b
		}
		vol += b.V
	}
	ret := 0.0
	if first.C != 0 {
		ret = (last.C/first.C - 1) * 100
	}
	monthly := h.Range == "2Y" || h.Range == "5Y"
	closes := periodCloses(bars, monthly)
	if len(closes) > 60 {
		closes = closes[len(closes)-60:]
	}
	key := "weeklyCloses"
	if monthly {
		key = "monthlyCloses"
	}
	volPct := market.AnnualizedVolatility(bars) * 100
	mdd := market.MaxDrawdown(bars) * 100
	build := func(keep int) []byte {
		return newObj().str("symbol", h.Symbol).str("range", h.Range).str("asOf", h.AsOf).
			raw("start", newObj().str("t", first.T).num("c", first.C, 2).bytes()).
			raw("end", newObj().str("t", last.T).num("c", last.C, 2).bytes()).
			num("returnPct", ret, 2).
			raw("high", newObj().str("t", hi.T).num("h", hi.H, 2).bytes()).
			raw("low", newObj().str("t", lo.T).num("l", lo.L, 2).bytes()).
			num("volatilityAnnualizedPct", volPct, 2).num("maxDrawdownPct", mdd, 2).
			integer("avgVolume", vol/float64(len(bars))).
			raw(key, numArray(closes[len(closes)-keep:], 2)).
			str("source", h.Source).bytes()
	}
	return Result{
		ModelView: fit(build, len(closes)),
		UIView:    map[string]any{"kind": "price_history", "history": h},
		Summary:   fmt.Sprintf("%s %s: %s%% · volatility %s%%", h.Symbol, h.Range, signed(ret), formatNum(volPct, 1)),
	}, nil
}

func (r *Registry) getIndicators(ctx context.Context, args map[string]any) (Result, error) {
	sym, rng := argString(args, "symbol"), argString(args, "range")
	ind, err := r.market.Indicators(ctx, sym, rng)
	if err != nil {
		return Result{}, err
	}
	h, err := r.market.History(ctx, sym, rng)
	if err != nil {
		return Result{}, err
	}
	l := ind.Latest
	var pctB, atrPct *float64
	if l.BBUpper != nil && l.BBLower != nil && *l.BBUpper != *l.BBLower {
		v := (l.Close - *l.BBLower) / (*l.BBUpper - *l.BBLower)
		pctB = &v
	}
	if l.ATR14 != nil && l.Close != 0 {
		v := *l.ATR14 / l.Close * 100
		atrPct = &v
	}
	build := func(keep int) []byte {
		sigs := make([][]byte, 0, keep)
		for _, s := range ind.Signals[:keep] {
			sigs = append(sigs, newObj().str("id", s.ID).str("tone", s.Tone).str("detail", s.Detail).bytes())
		}
		return newObj().str("symbol", ind.Symbol).str("asOf", ind.AsOf).num("close", l.Close, 2).
			optNum("sma20", l.SMA20, 2).optNum("sma50", l.SMA50, 2).optNum("sma200", l.SMA200, 2).
			optNum("ema12", l.EMA12, 2).optNum("ema26", l.EMA26, 2).optNum("rsi14", l.RSI14, 2).
			optNum("macd", l.MACD, 2).optNum("macdSignal", l.MACDSignal, 2).optNum("macdHist", l.MACDHist, 2).
			optNum("bbUpper", l.BBUpper, 2).optNum("bbMiddle", l.BBMiddle, 2).optNum("bbLower", l.BBLower, 2).
			optNum("bbPercentB", pctB, 3).optNum("atr14", l.ATR14, 2).optNum("atrPct", atrPct, 2).
			raw("signals", array(sigs)).str("source", h.Source).bytes()
	}
	rsi := "n/a"
	if l.RSI14 != nil {
		rsi = formatNum(*l.RSI14, 1)
	}
	return Result{
		ModelView: fit(build, len(ind.Signals)),
		UIView:    map[string]any{"kind": "indicators", "indicators": ind, "history": h},
		Summary:   fmt.Sprintf("%s RSI14 %s · %d signal(s) · %s", ind.Symbol, rsi, len(ind.Signals), ind.AsOf),
	}, nil
}

func (r *Registry) getFundamentals(ctx context.Context, args map[string]any) (Result, error) {
	f, err := r.market.Fundamentals(ctx, argString(args, "symbol"), argString(args, "period"), argInt(args, "limit"))
	if err != nil {
		return Result{}, err
	}
	rt := f.Ratios
	ratios := newObj().optNum("grossMarginPct", rt.GrossMarginPct, 2).optNum("operatingMarginPct", rt.OperatingMarginPct, 2).
		optNum("netMarginPct", rt.NetMarginPct, 2).optNum("fcfMarginPct", rt.FCFMarginPct, 2).
		optNum("revenueGrowthPct", rt.RevenueGrowthPct, 2).optNum("epsGrowthPct", rt.EPSGrowthPct, 2).
		optNum("debtToAssets", rt.DebtToAssets, 3).bytes()
	build := func(keep int) []byte {
		items := make([][]byte, 0, keep)
		for _, p := range f.Periods[:keep] {
			items = append(items, newObj().integer("fy", float64(p.FiscalYear)).str("fp", p.FiscalPeriod).str("end", p.PeriodEnd).
				optInt("revenue", p.Revenue).optInt("grossProfit", p.GrossProfit).optInt("operatingIncome", p.OperatingIncome).
				optInt("netIncome", p.NetIncome).optNum("epsDiluted", p.EPSDiluted, 2).optInt("operatingCashFlow", p.OperatingCashFlow).
				optInt("freeCashFlow", p.FreeCashFlow).optInt("totalAssets", p.TotalAssets).optInt("totalLiabilities", p.TotalLiabilities).
				optInt("cash", p.CashAndEquivalents).optInt("longTermDebt", p.LongTermDebt).bytes())
		}
		return newObj().str("symbol", f.Symbol).str("name", f.Name).str("period", f.Period).str("currency", f.Currency).
			raw("periods", array(items)).raw("ratios", ratios).str("source", f.Source).str("asOf", f.AsOf).bytes()
	}
	newest := ""
	if len(f.Periods) > 0 {
		newest = fmt.Sprintf(" · newest %s %d", f.Periods[0].FiscalPeriod, f.Periods[0].FiscalYear)
	}
	return Result{
		ModelView: fit(build, len(f.Periods)),
		UIView:    map[string]any{"kind": "fundamentals", "fundamentals": f},
		Summary:   fmt.Sprintf("%s %s · %d period(s)%s", f.Symbol, f.Period, len(f.Periods), newest),
	}, nil
}

func (r *Registry) getForecast(ctx context.Context, args map[string]any) (Result, error) {
	fc, err := r.market.Forecast(ctx, argString(args, "symbol"))
	if err != nil {
		return Result{}, err
	}
	hs := make([][]byte, 0, len(fc.Horizons))
	for _, h := range fc.Horizons {
		hs = append(hs, newObj().integer("m", float64(h.Months)).num("p10", h.P10, 2).num("p50", h.P50, 2).num("p90", h.P90, 2).bytes())
	}
	mv := newObj().str("symbol", fc.Symbol).str("asOf", fc.AsOf).num("basePrice", fc.BasePrice, 2).
		str("source", fc.Source).str("method", fc.Method).raw("horizons", array(hs)).bytes()
	summary := fc.Symbol + " baseline forecast"
	if n := len(fc.Horizons); n > 0 {
		h := fc.Horizons[n-1]
		summary = fmt.Sprintf("%s %dM P50 %s (P10 %s · P90 %s)", fc.Symbol, h.Months, formatNum(h.P50, 2), formatNum(h.P10, 2), formatNum(h.P90, 2))
	}
	return Result{ModelView: string(mv), UIView: map[string]any{"kind": "forecast", "forecast": fc}, Summary: summary}, nil
}
