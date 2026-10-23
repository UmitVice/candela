package market

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/store"
	"github.com/UmitVice/candela/services/gateway/internal/store/db"
)

type PriceProvider interface {
	ID() string
	Status() ProviderStatus
	Bars(ctx context.Context, symbol string) ([]Bar, error)
}

type FundamentalsProvider interface {
	Status() ProviderStatus
	Fundamentals(ctx context.Context, symbol, period string, limit int) ([]FundamentalPeriod, string, error)
	Source() string
}

type disabledProvider struct{ id, statusID string }

func (d disabledProvider) ID() string { return d.id }
func (d disabledProvider) Status() ProviderStatus {
	return ProviderStatus{ID: d.statusID, Status: "disabled"}
}
func (d disabledProvider) Bars(context.Context, string) ([]Bar, error) { return nil, ErrUnavailable }
func (d disabledProvider) Fundamentals(context.Context, string, string, int) ([]FundamentalPeriod, string, error) {
	return nil, "", ErrUnavailable
}
func (d disabledProvider) Source() string { return d.id }

// NewLiveProvider and NewVanirasProvider are the seams for the keyed end-of-day API and
// the owner's Vaniras platform; both stay disabled until those integrations exist.
func NewLiveProvider(apiKey string) PriceProvider {
	return disabledProvider{id: "live", statusID: "live-prices"}
}

func NewVanirasProvider(baseURL string) disabledProvider {
	return disabledProvider{id: "vaniras", statusID: "vaniras"}
}

type snapshotPrices struct{ s *Snapshot }

func (p snapshotPrices) ID() string { return "snapshot" }
func (p snapshotPrices) Status() ProviderStatus {
	if p.s == nil {
		return ProviderStatus{ID: "snapshot", Status: "disabled"}
	}
	return ProviderStatus{ID: "snapshot", Status: "ok", AsOf: p.s.Meta().AsOf}
}
func (p snapshotPrices) Bars(ctx context.Context, sym string) ([]Bar, error) {
	if p.s == nil {
		return nil, ErrUnavailable
	}
	return p.s.Bars(ctx, sym)
}

type snapshotFundamentals struct{ s *Snapshot }

func (p snapshotFundamentals) Source() string { return "sec" }
func (p snapshotFundamentals) Status() ProviderStatus {
	if p.s == nil || !p.s.HasFundamentals() {
		return ProviderStatus{ID: "sec", Status: "disabled"}
	}
	return ProviderStatus{ID: "sec", Status: "ok", AsOf: p.s.FundamentalsAsOf()}
}
func (p snapshotFundamentals) Fundamentals(ctx context.Context, sym, period string, limit int) ([]FundamentalPeriod, string, error) {
	if p.s == nil || !p.s.HasFundamentals() {
		return nil, "", ErrUnavailable
	}
	return p.s.Fundamentals(ctx, sym, period, limit)
}

type Service struct {
	snap     *Snapshot
	dir      *Directory
	store    *store.Store
	cacheTTL time.Duration
	log      *slog.Logger
	prices   []PriceProvider
	funds    []FundamentalsProvider
	vaniras  disabledProvider
}

type Options struct {
	Snapshot   *Snapshot
	Directory  *Directory
	Store      *store.Store
	CacheTTL   time.Duration
	LiveAPIKey string
	VanirasURL string
	Log        *slog.Logger
}

func NewService(o Options) *Service {
	v := NewVanirasProvider(o.VanirasURL)
	return &Service{
		snap: o.Snapshot, dir: o.Directory, store: o.Store, cacheTTL: o.CacheTTL, log: o.Log, vaniras: v,
		prices: []PriceProvider{v, NewLiveProvider(o.LiveAPIKey), snapshotPrices{o.Snapshot}},
		funds:  []FundamentalsProvider{v, snapshotFundamentals{o.Snapshot}},
	}
}

func (s *Service) Directory() *Directory { return s.dir }

func (s *Service) Providers() []ProviderStatus {
	out := []ProviderStatus{snapshotPrices{s.snap}.Status(), s.prices[1].Status(), snapshotFundamentals{s.snap}.Status()}
	bf := ProviderStatus{ID: "baseline-forecast", Status: "disabled"}
	if s.snap != nil {
		bf = ProviderStatus{ID: "baseline-forecast", Status: "ok", AsOf: s.snap.Meta().AsOf}
	}
	return append(out, bf, s.vaniras.Status())
}

func (s *Service) Ready() bool { return s.snap != nil }

func (s *Service) Search(q string, limit int) []SymbolInfo { return s.dir.Search(q, limit) }

func (s *Service) info(sym string) (SymbolInfo, error) {
	if !ValidSymbol(sym) {
		return SymbolInfo{}, ErrInvalid
	}
	if info, ok := s.dir.Lookup(sym); ok {
		return info, nil
	}
	if s.snap != nil {
		if v, ok := s.snap.Symbol(sym); ok {
			return v.SymbolInfo, nil
		}
	}
	return SymbolInfo{}, ErrNotFound
}

type SourceError struct {
	Err error
	Msg string
}

func (e *SourceError) Error() string { return e.Msg }
func (e *SourceError) Unwrap() error { return e.Err }

func (s *Service) bars(ctx context.Context, sym string) (SymbolInfo, []Bar, string, error) {
	info, err := s.info(sym)
	if err != nil {
		return info, nil, "", err
	}
	for _, p := range s.prices {
		if p.Status().Status == "disabled" {
			continue
		}
		bars, err := p.Bars(ctx, sym)
		if err == nil && len(bars) > 0 {
			return info, bars, p.ID(), nil
		}
		if err != nil && !errors.Is(err, ErrNotFound) {
			s.log.Warn("price provider failed", "provider", p.ID(), "symbol", sym, "err", err)
		}
	}
	return info, nil, "", &SourceError{Err: ErrUnavailable, Msg: fmt.Sprintf("no price data for %s in the current data sources", sym)}
}

func cached[T any](ctx context.Context, s *Service, key string, compute func() (T, error)) (T, error) {
	var zero T
	now := time.Now()
	if s.store != nil {
		raw, err := s.store.Q.GetCache(ctx, db.GetCacheParams{Key: key, ExpiresAt: now.Unix()})
		if err == nil {
			var v T
			if json.Unmarshal(raw, &v) == nil {
				return v, nil
			}
		} else if !errors.Is(err, sql.ErrNoRows) {
			s.log.Warn("market cache read", "err", err)
		}
	}
	v, err := compute()
	if err != nil {
		return zero, err
	}
	if s.store != nil {
		if raw, err := json.Marshal(v); err == nil {
			if err := s.store.Q.PutCache(ctx, db.PutCacheParams{Key: key, Value: raw, ExpiresAt: now.Add(s.cacheTTL).Unix()}); err != nil {
				s.log.Warn("market cache write", "err", err)
			}
		}
	}
	return v, nil
}

func (s *Service) Quote(ctx context.Context, sym string) (Quote, error) {
	info, bars, src, err := s.bars(ctx, sym)
	if err != nil {
		return Quote{}, err
	}
	return BuildQuote(info, bars, src), nil
}

func (s *Service) History(ctx context.Context, sym, r string) (PriceHistory, error) {
	if !ValidHistoryRange(r) {
		return PriceHistory{}, ErrInvalid
	}
	_, bars, src, err := s.bars(ctx, sym)
	if err != nil {
		return PriceHistory{}, err
	}
	return BuildHistory(sym, bars, r, src), nil
}

func (s *Service) Indicators(ctx context.Context, sym, r string) (IndicatorSet, error) {
	if !ValidIndicatorRange(r) {
		return IndicatorSet{}, ErrInvalid
	}
	_, bars, src, err := s.bars(ctx, sym)
	if err != nil {
		return IndicatorSet{}, err
	}
	key := fmt.Sprintf("v1|ind|%s|%s|%s|%s", src, sym, r, bars[len(bars)-1].T)
	return cached(ctx, s, key, func() (IndicatorSet, error) { return BuildIndicators(sym, bars, r), nil })
}

func (s *Service) Forecast(ctx context.Context, sym string) (Forecast, error) {
	_, bars, src, err := s.bars(ctx, sym)
	if err != nil {
		return Forecast{}, err
	}
	key := fmt.Sprintf("v1|fc|%s|%s|%s", src, sym, bars[len(bars)-1].T)
	return cached(ctx, s, key, func() (Forecast, error) { return BuildForecast(sym, bars), nil })
}

func (s *Service) Fundamentals(ctx context.Context, sym, period string, limit int) (Fundamentals, error) {
	if period != "annual" && period != "quarterly" {
		return Fundamentals{}, ErrInvalid
	}
	if limit < 1 || limit > 8 {
		return Fundamentals{}, ErrInvalid
	}
	info, err := s.info(sym)
	if err != nil {
		return Fundamentals{}, err
	}
	extra := 1
	if period == "quarterly" {
		extra = 4
	}
	for _, p := range s.funds {
		if p.Status().Status == "disabled" {
			continue
		}
		periods, asOf, err := p.Fundamentals(ctx, sym, period, limit+extra)
		if err != nil || len(periods) == 0 {
			if err != nil && !errors.Is(err, ErrUnavailable) {
				s.log.Warn("fundamentals provider failed", "symbol", sym, "err", err)
			}
			continue
		}
		out := Fundamentals{Symbol: sym, Name: info.Name, Period: period, Currency: "USD", Source: p.Source(), AsOf: asOf}
		out.Ratios = ratios(periods)
		out.Periods = periods[:min(limit, len(periods))]
		return out, nil
	}
	return Fundamentals{}, &SourceError{Err: ErrUnavailable, Msg: fmt.Sprintf("no reported financial statements for %s in the current data sources", sym)}
}

func ratios(p []FundamentalPeriod) Ratios {
	var r Ratios
	cur := p[0]
	pct := func(a, b *float64) *float64 {
		if a == nil || b == nil || *b == 0 {
			return nil
		}
		v := Round(*a / *b * 100, 2)
		return &v
	}
	r.GrossMarginPct = pct(cur.GrossProfit, cur.Revenue)
	r.OperatingMarginPct = pct(cur.OperatingIncome, cur.Revenue)
	r.NetMarginPct = pct(cur.NetIncome, cur.Revenue)
	r.FCFMarginPct = pct(cur.FreeCashFlow, cur.Revenue)
	if cur.LongTermDebt != nil && cur.TotalAssets != nil && *cur.TotalAssets != 0 {
		v := Round(*cur.LongTermDebt / *cur.TotalAssets, 3)
		r.DebtToAssets = &v
	}
	for _, prev := range p[1:] {
		if prev.FiscalPeriod == cur.FiscalPeriod && prev.FiscalYear == cur.FiscalYear-1 {
			r.RevenueGrowthPct = growth(cur.Revenue, prev.Revenue)
			r.EPSGrowthPct = growth(cur.EPSDiluted, prev.EPSDiluted)
			break
		}
	}
	return r
}

func growth(cur, prev *float64) *float64 {
	if cur == nil || prev == nil || *prev == 0 {
		return nil
	}
	v := Round((*cur-*prev)/math.Abs(*prev)*100, 2)
	return &v
}
