package market

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"time"

	lru "github.com/hashicorp/golang-lru/v2"
	_ "modernc.org/sqlite"
)

type SnapshotMeta struct {
	AsOf     string
	Source   string
	License  string
	BuiltAt  string
	FundAsOf string
}

type SnapshotSymbol struct {
	SymbolInfo
	Kind   string
	Source string
}

type Snapshot struct {
	db      *sql.DB
	meta    SnapshotMeta
	symbols map[string]SnapshotSymbol
	bars    *lru.Cache[string, []Bar]
	hasFund bool
}

func EnsureSnapshot(ctx context.Context, path, rawURL string, log *slog.Logger) error {
	if _, err := os.Stat(path); err == nil || rawURL == "" {
		return nil
	}
	u, err := url.Parse(rawURL)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") {
		return fmt.Errorf("CANDELA_SNAPSHOT_URL must be an http(s) URL")
	}
	log.Info("downloading market snapshot", "host", u.Host)
	ctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("snapshot download: HTTP %d", resp.StatusCode)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".snapshot-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, io.LimitReader(resp.Body, 2<<30)); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

func OpenSnapshot(ctx context.Context, path string) (*Snapshot, error) {
	if _, err := os.Stat(path); err != nil {
		return nil, fmt.Errorf("snapshot %s: %w", path, err)
	}
	conn, err := sql.Open("sqlite", "file:"+path+"?mode=ro&immutable=1")
	if err != nil {
		return nil, err
	}
	s := &Snapshot{db: conn, symbols: map[string]SnapshotSymbol{}}
	s.bars, _ = lru.New[string, []Bar](96)
	rows, err := conn.QueryContext(ctx, `SELECT key, value FROM meta`)
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("snapshot meta: %w", err)
	}
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			_ = rows.Close()
			_ = conn.Close()
			return nil, err
		}
		switch k {
		case "asOf":
			s.meta.AsOf = v
		case "source":
			s.meta.Source = v
		case "license":
			s.meta.License = v
		case "builtAt":
			s.meta.BuiltAt = v
		case "fundamentalsAsOf":
			s.meta.FundAsOf = v
		}
	}
	_ = rows.Close()
	rows, err = conn.QueryContext(ctx, `SELECT symbol, name, exchange, kind, source FROM symbols`)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sym SnapshotSymbol
		if err := rows.Scan(&sym.Symbol, &sym.Name, &sym.Exchange, &sym.Kind, &sym.Source); err != nil {
			_ = conn.Close()
			return nil, err
		}
		s.symbols[sym.Symbol] = sym
	}
	var n int
	if err := conn.QueryRowContext(ctx, `SELECT COUNT(*) FROM fundamentals`).Scan(&n); err == nil && n > 0 {
		s.hasFund = true
	}
	return s, rows.Err()
}

func (s *Snapshot) Meta() SnapshotMeta { return s.meta }

func (s *Snapshot) HasFundamentals() bool { return s.hasFund }

func (s *Snapshot) FundamentalsAsOf() string { return s.meta.FundAsOf }

func (s *Snapshot) Symbol(sym string) (SnapshotSymbol, bool) {
	v, ok := s.symbols[sym]
	return v, ok
}

func (s *Snapshot) Symbols() []SnapshotSymbol {
	out := make([]SnapshotSymbol, 0, len(s.symbols))
	for _, v := range s.symbols {
		out = append(out, v)
	}
	return out
}

func (s *Snapshot) Bars(ctx context.Context, sym string) ([]Bar, error) {
	if b, ok := s.bars.Get(sym); ok {
		return b, nil
	}
	if _, ok := s.symbols[sym]; !ok {
		return nil, ErrNotFound
	}
	rows, err := s.db.QueryContext(ctx, `SELECT t, o, h, l, c, v FROM bars WHERE symbol = ? ORDER BY t`, sym)
	if err != nil {
		return nil, errors.Join(ErrUnavailable, err)
	}
	defer rows.Close()
	bars := make([]Bar, 0, 1600)
	for rows.Next() {
		var b Bar
		if err := rows.Scan(&b.T, &b.O, &b.H, &b.L, &b.C, &b.V); err != nil {
			return nil, errors.Join(ErrUnavailable, err)
		}
		bars = append(bars, b)
	}
	if err := rows.Err(); err != nil {
		return nil, errors.Join(ErrUnavailable, err)
	}
	if len(bars) == 0 {
		return nil, ErrNotFound
	}
	s.bars.Add(sym, bars)
	return bars, nil
}

func (s *Snapshot) Fundamentals(ctx context.Context, sym, period string, limit int) ([]FundamentalPeriod, string, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT fiscal_year, fiscal_period, period_end, filed,
		revenue, gross_profit, operating_income, net_income, eps_diluted, operating_cash_flow, capital_expenditure,
		total_assets, total_liabilities, cash, long_term_debt, shares_outstanding
		FROM fundamentals WHERE symbol = ? AND period = ? ORDER BY period_end DESC LIMIT ?`, sym, period, limit)
	if err != nil {
		return nil, "", errors.Join(ErrUnavailable, err)
	}
	defer rows.Close()
	var out []FundamentalPeriod
	asOf := ""
	for rows.Next() {
		var p FundamentalPeriod
		var filed string
		var vals [12]sql.NullFloat64
		if err := rows.Scan(&p.FiscalYear, &p.FiscalPeriod, &p.PeriodEnd, &filed,
			&vals[0], &vals[1], &vals[2], &vals[3], &vals[4], &vals[5], &vals[6], &vals[7], &vals[8], &vals[9], &vals[10], &vals[11]); err != nil {
			return nil, "", errors.Join(ErrUnavailable, err)
		}
		f := func(i int) *float64 {
			if !vals[i].Valid {
				return nil
			}
			v := vals[i].Float64
			return &v
		}
		p.Revenue, p.GrossProfit, p.OperatingIncome, p.NetIncome = f(0), f(1), f(2), f(3)
		p.EPSDiluted, p.OperatingCashFlow, p.CapitalExpenditure = f(4), f(5), f(6)
		p.TotalAssets, p.TotalLiabilities, p.CashAndEquivalents, p.LongTermDebt, p.SharesOutstanding = f(7), f(8), f(9), f(10), f(11)
		if p.OperatingCashFlow != nil && p.CapitalExpenditure != nil {
			v := *p.OperatingCashFlow - *p.CapitalExpenditure
			p.FreeCashFlow = &v
		}
		if filed > asOf {
			asOf = filed
		}
		out = append(out, p)
	}
	return out, asOf, rows.Err()
}

func (s *Snapshot) Close() error { return s.db.Close() }
