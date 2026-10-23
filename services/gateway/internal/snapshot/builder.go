package snapshot

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"io"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	_ "modernc.org/sqlite"

	"github.com/UmitVice/candela/services/gateway/internal/market"
)

//go:embed universe/*.txt
var universeFS embed.FS

var nan = math.NaN()

const (
	pricesDataset = "defeatbeta/yahoo-finance-data"
	etfDataset    = "AlphaDojo/dojo_stock_kline"
	fundDataset   = "ZipLime/company-fundamentals"
	dateLayout    = "2006-01-02"
)

type Options struct {
	Out            string
	Years          int
	FundYears      int
	SymbolsBaseURL string
	Log            *slog.Logger
}

type member struct {
	symbol   string
	name     string
	exchange string
	kind     string
	cik      string
	source   string
	bars     []market.Bar
}

type Summary struct {
	AsOf             string
	Symbols          int
	FiveYearCoverage int
	Fundamentals     int
	Missing          []string
}

func sourceSymbol(s string) string { return strings.ReplaceAll(s, ".", "-") }

func loadUniverse() (map[string]*member, error) {
	u := map[string]*member{}
	for _, f := range []string{"sp500.txt", "ndx100.txt"} {
		b, err := universeFS.ReadFile("universe/" + f)
		if err != nil {
			return nil, err
		}
		for line := range strings.SplitSeq(string(b), "\n") {
			if s := strings.TrimSpace(line); s != "" && market.ValidSymbol(s) {
				u[s] = &member{symbol: s, kind: "stock"}
			}
		}
	}
	b, err := universeFS.ReadFile("universe/etfs.txt")
	if err != nil {
		return nil, err
	}
	for line := range strings.SplitSeq(string(b), "\n") {
		parts := strings.Split(strings.TrimSpace(line), "|")
		if len(parts) == 3 {
			u[parts[0]] = &member{symbol: parts[0], name: parts[1], exchange: parts[2], kind: "etf"}
		}
	}
	return u, nil
}

func Build(ctx context.Context, o Options) (Summary, error) {
	log := o.Log
	var sum Summary
	universe, err := loadUniverse()
	if err != nil {
		return sum, err
	}
	log.Info("universe loaded", "symbols", len(universe))
	directoryNames(ctx, o.SymbolsBaseURL, universe, log)

	priceInfo, err := dataset(ctx, pricesDataset, "main")
	if err != nil {
		return sum, fmt.Errorf("%s: %w", pricesDataset, err)
	}
	if err := companyTickers(ctx, priceInfo, universe); err != nil {
		return sum, err
	}
	now := time.Now().UTC()
	cutoff := now.AddDate(-o.Years, 0, -10).Format(dateLayout)
	if err := primaryPrices(ctx, priceInfo, universe, cutoff, log); err != nil {
		return sum, err
	}
	asOf := ""
	for _, m := range universe {
		if n := len(m.bars); n > 0 && m.bars[n-1].T > asOf {
			asOf = m.bars[n-1].T
		}
	}
	if asOf == "" {
		return sum, fmt.Errorf("no price data found")
	}
	staleBefore := mustDate(asOf).AddDate(0, 0, -7).Format(dateLayout)
	fill := map[string]*member{}
	for s, m := range universe {
		if len(m.bars) == 0 || m.bars[len(m.bars)-1].T < staleBefore {
			fill[sourceSymbol(s)] = m
		}
	}
	etfInfo, err := dataset(ctx, etfDataset, "main")
	if err != nil {
		return sum, fmt.Errorf("%s: %w", etfDataset, err)
	}
	if len(fill) > 0 {
		log.Info("filling missing or stale symbols from secondary source", "dataset", etfDataset, "symbols", len(fill))
		if err := secondaryPrices(ctx, etfInfo, fill, cutoff, log); err != nil {
			return sum, err
		}
	}
	for _, m := range universe {
		if n := len(m.bars); n > 0 && m.bars[n-1].T > asOf {
			asOf = m.bars[n-1].T
		}
	}

	fundInfo, err := dataset(ctx, fundDataset, "main")
	if err != nil {
		return sum, fmt.Errorf("%s: %w", fundDataset, err)
	}
	funds, err := fundamentals(ctx, fundInfo, universe, mustDate(asOf).Year()-o.FundYears, log)
	if err != nil {
		return sum, err
	}

	fiveYears := mustDate(asOf).AddDate(-5, 0, 7).Format(dateLayout)
	for _, m := range universe {
		if len(m.bars) == 0 {
			sum.Missing = append(sum.Missing, m.symbol)
			continue
		}
		sum.Symbols++
		if m.bars[0].T <= fiveYears {
			sum.FiveYearCoverage++
		}
	}
	sort.Strings(sum.Missing)
	sum.AsOf = asOf
	fundAsOf := ""
	for _, f := range funds {
		if f.filed > fundAsOf {
			fundAsOf = f.filed
		}
	}
	sum.Fundamentals = len(funds)

	meta := map[string]string{
		"asOf":             asOf,
		"source":           fmt.Sprintf("%s@%s (prices); %s@%s (ETF gaps); %s@%s (fundamentals)", pricesDataset, priceInfo.SHA[:12], etfDataset, etfInfo.SHA[:12], fundDataset, fundInfo.SHA[:12]),
		"license":          fmt.Sprintf("%s: %s; %s: %s; %s: %s", pricesDataset, licenseOf(priceInfo), etfDataset, licenseOf(etfInfo), fundDataset, licenseOf(fundInfo)),
		"builtAt":          now.Format(time.RFC3339),
		"fundamentalsAsOf": fundAsOf,
		"universe":         "S&P 500 and Nasdaq-100 constituents (Wikipedia, 2026-10-23) plus SPY, QQQ, DIA, IWM and the 11 Select Sector SPDR ETFs",
	}
	if err := write(ctx, o.Out, meta, universe, funds); err != nil {
		return sum, err
	}
	return sum, nil
}

func mustDate(s string) time.Time {
	t, err := time.Parse(dateLayout, s)
	if err != nil {
		return time.Now().UTC()
	}
	return t
}

func directoryNames(ctx context.Context, base string, u map[string]*member, log *slog.Logger) {
	for _, f := range []string{"nasdaqlisted.txt", "otherlisted.txt"} {
		resp, err := get(ctx, strings.TrimRight(base, "/")+"/"+f, nil)
		if err != nil {
			log.Warn("symbol directory unavailable; names fall back to SEC titles", "file", f, "err", err)
			continue
		}
		rows, err := market.ParseDirectory(io.LimitReader(resp.Body, 16<<20), f == "otherlisted.txt")
		_ = resp.Body.Close()
		if err != nil {
			log.Warn("symbol directory parse failed", "file", f, "err", err)
			continue
		}
		for _, r := range rows {
			if m, ok := u[r.Symbol]; ok {
				if m.kind != "etf" || m.name == "" {
					m.name = r.Name
				}
				m.exchange = r.Exchange
			}
		}
	}
}

func companyTickers(ctx context.Context, info datasetInfo, u map[string]*member) error {
	var raw map[string]struct {
		CIK    int64  `json:"cik_str"`
		Ticker string `json:"ticker"`
		Title  string `json:"title"`
	}
	if err := getJSON(ctx, fileURL(pricesDataset, info.SHA, "data/US/company_tickers.json"), &raw); err != nil {
		return fmt.Errorf("company tickers: %w", err)
	}
	for _, e := range raw {
		sym := strings.ReplaceAll(strings.ToUpper(e.Ticker), "-", ".")
		if m, ok := u[sym]; ok {
			if m.cik == "" {
				m.cik = fmt.Sprintf("%010d", e.CIK)
			}
			if m.name == "" {
				m.name = e.Title
			}
		}
	}
	return nil
}

func sizeOf(info datasetInfo, path string) int64 {
	for _, s := range info.Siblings {
		if s.RFilename == path {
			return s.Size
		}
	}
	return 0
}

func primaryPrices(ctx context.Context, info datasetInfo, u map[string]*member, cutoff string, log *slog.Logger) error {
	const path = "data/US/stock_prices.parquet"
	size := sizeOf(info, path)
	if size == 0 {
		return fmt.Errorf("%s: %s not found", pricesDataset, path)
	}
	f, rf, err := openParquet(ctx, fileURL(pricesDataset, info.SHA, path), size)
	if err != nil {
		return err
	}
	want := map[string]*member{}
	keys := make([]string, 0, len(u))
	for s, m := range u {
		want[sourceSymbol(s)] = m
		keys = append(keys, sourceSymbol(s))
	}
	sort.Strings(keys)
	cols := map[string]int{}
	for _, c := range []string{"symbol", "report_date", "open", "close", "high", "low", "volume"} {
		if cols[c], err = columnIndex(f, c); err != nil {
			return err
		}
	}
	scale := decimalScale(f, "close")
	meta := f.Metadata()
	used := 0
	for gi, rg := range f.RowGroups() {
		st := meta.RowGroups[gi].Columns[cols["symbol"]].MetaData.Statistics
		lo, hi := string(st.MinValue), string(st.MaxValue)
		if lo == "" && hi == "" {
			lo, hi = string(st.Min), string(st.Max)
		}
		i := sort.SearchStrings(keys, lo)
		if hi != "" && (i >= len(keys) || keys[i] > hi) {
			continue
		}
		used++
		syms, err := stringColumn(rg, cols["symbol"])
		if err != nil {
			return err
		}
		dates, err := stringColumn(rg, cols["report_date"])
		if err != nil {
			return err
		}
		keep := make([]bool, len(syms))
		any := false
		for r, s := range syms {
			if _, ok := want[s]; ok && dates[r] >= cutoff {
				keep[r], any = true, true
			}
		}
		if !any {
			continue
		}
		var vals [4][]float64
		for k, c := range []string{"open", "high", "low", "close"} {
			if vals[k], err = numbers(rg, cols[c], scale, keep); err != nil {
				return err
			}
		}
		vol, err := ints(rg, cols["volume"], keep)
		if err != nil {
			return err
		}
		for r := range syms {
			if !keep[r] {
				continue
			}
			want[syms[r]].bars = append(want[syms[r]].bars, market.Bar{T: dates[r], O: vals[0][r], H: vals[1][r], L: vals[2][r], C: vals[3][r], V: float64(vol[r])})
		}
		if used%25 == 0 {
			log.Info("primary prices progress", "rowGroups", used, "downloadedMB", rf.read>>20)
		}
	}
	for _, m := range u {
		m.bars = cleanBars(m.bars)
		if len(m.bars) > 0 {
			m.source = "defeatbeta"
		}
	}
	log.Info("primary prices loaded", "rowGroupsRead", used, "rowGroups", len(f.RowGroups()), "downloadedMB", rf.read>>20)
	return nil
}

func secondaryPrices(ctx context.Context, info datasetInfo, fill map[string]*member, cutoff string, log *slog.Logger) error {
	const path = "data.parquet"
	size := sizeOf(info, path)
	if size == 0 {
		return fmt.Errorf("%s: %s not found", etfDataset, path)
	}
	f, rf, err := openParquet(ctx, fileURL(etfDataset, info.SHA, path), size)
	if err != nil {
		return err
	}
	cols := map[string]int{}
	for _, c := range []string{"symbol", "kline_t", "bar_time", "open", "high", "low", "close", "vol"} {
		if cols[c], err = columnIndex(f, c); err != nil {
			return err
		}
	}
	extra := map[string][]market.Bar{}
	for _, rg := range f.RowGroups() {
		syms, err := stringColumn(rg, cols["symbol"])
		if err != nil {
			return err
		}
		keep := make([]bool, len(syms))
		any := false
		for r, s := range syms {
			if _, ok := fill[s]; ok {
				keep[r], any = true, true
			}
		}
		if !any {
			continue
		}
		kinds, err := stringColumn(rg, cols["kline_t"])
		if err != nil {
			return err
		}
		ts, err := ints(rg, cols["bar_time"], keep)
		if err != nil {
			return err
		}
		var vals [5][]float64
		for k, c := range []string{"open", "high", "low", "close", "vol"} {
			if vals[k], err = numbers(rg, cols[c], 0, keep); err != nil {
				return err
			}
		}
		for r := range syms {
			if !keep[r] || kinds[r] != "1D" {
				continue
			}
			t := time.Unix(0, ts[r]).UTC().Format(dateLayout)
			if t < cutoff {
				continue
			}
			extra[syms[r]] = append(extra[syms[r]], market.Bar{T: t, O: vals[0][r], H: vals[1][r], L: vals[2][r], C: vals[3][r], V: vals[4][r]})
		}
	}
	for sym, bars := range extra {
		m := fill[sym]
		bars = cleanBars(bars)
		if len(m.bars) == 0 {
			m.bars, m.source = bars, "alphadojo"
			continue
		}
		last := m.bars[len(m.bars)-1].T
		for _, b := range bars {
			if b.T > last {
				m.bars = append(m.bars, b)
			}
		}
		m.source = "defeatbeta+alphadojo"
	}
	log.Info("secondary prices loaded", "symbols", len(extra), "downloadedMB", rf.read>>20)
	return nil
}

func cleanBars(bars []market.Bar) []market.Bar {
	slices.SortStableFunc(bars, func(a, b market.Bar) int { return strings.Compare(a.T, b.T) })
	out := bars[:0]
	for _, b := range bars {
		if math.IsNaN(b.C) || b.C <= 0 || math.IsNaN(b.O) || math.IsNaN(b.H) || math.IsNaN(b.L) {
			continue
		}
		if n := len(out); n > 0 && out[n-1].T == b.T {
			out[n-1] = b
			continue
		}
		b.H = math.Max(b.H, math.Max(b.O, b.C))
		b.L = math.Min(b.L, math.Min(b.O, b.C))
		if math.IsNaN(b.V) || b.V < 0 {
			b.V = 0
		}
		out = append(out, b)
	}
	return out
}

func write(ctx context.Context, out string, meta map[string]string, u map[string]*member, funds []fundRow) error {
	if err := os.MkdirAll(filepath.Dir(out), 0o750); err != nil {
		return err
	}
	tmp := out + ".tmp"
	_ = os.Remove(tmp)
	db, err := sql.Open("sqlite", "file:"+tmp+"?_pragma=journal_mode(OFF)&_pragma=synchronous(OFF)")
	if err != nil {
		return err
	}
	defer db.Close()
	schema := []string{
		`CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID`,
		`CREATE TABLE symbols (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, exchange TEXT NOT NULL, kind TEXT NOT NULL,
			source TEXT NOT NULL, cik TEXT, first_date TEXT NOT NULL, last_date TEXT NOT NULL, bars INTEGER NOT NULL) WITHOUT ROWID`,
		`CREATE TABLE bars (symbol TEXT NOT NULL, t TEXT NOT NULL, o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL,
			c REAL NOT NULL, v REAL NOT NULL, PRIMARY KEY (symbol, t)) WITHOUT ROWID`,
		`CREATE TABLE fundamentals (symbol TEXT NOT NULL, period TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
			fiscal_period TEXT NOT NULL, period_end TEXT NOT NULL, filed TEXT NOT NULL,
			revenue REAL, gross_profit REAL, operating_income REAL, net_income REAL, eps_diluted REAL,
			operating_cash_flow REAL, capital_expenditure REAL, total_assets REAL, total_liabilities REAL,
			cash REAL, long_term_debt REAL, shares_outstanding REAL,
			PRIMARY KEY (symbol, period, period_end)) WITHOUT ROWID`,
	}
	for _, s := range schema {
		if _, err := db.ExecContext(ctx, s); err != nil {
			return err
		}
	}
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	for k, v := range meta {
		if _, err := tx.ExecContext(ctx, `INSERT INTO meta VALUES (?, ?)`, k, v); err != nil {
			return err
		}
	}
	barStmt, err := tx.PrepareContext(ctx, `INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)`)
	if err != nil {
		return err
	}
	for _, m := range u {
		if len(m.bars) == 0 {
			continue
		}
		name, exch := m.name, m.exchange
		if name == "" {
			name = m.symbol
		}
		if exch == "" {
			exch = "US"
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`, m.symbol, name, exch, m.kind,
			m.source, nullable(m.cik), m.bars[0].T, m.bars[len(m.bars)-1].T, len(m.bars)); err != nil {
			return err
		}
		for _, b := range m.bars {
			if _, err := barStmt.ExecContext(ctx, m.symbol, b.T, market.Round(b.O, 4), market.Round(b.H, 4), market.Round(b.L, 4), market.Round(b.C, 4), math.Round(b.V)); err != nil {
				return err
			}
		}
	}
	fundStmt, err := tx.PrepareContext(ctx, `INSERT INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
	if err != nil {
		return err
	}
	for _, f := range funds {
		args := []any{f.symbol, f.period, f.fy, f.fp, f.end, f.filed}
		for _, v := range f.values {
			args = append(args, nullFloat(v))
		}
		if _, err := fundStmt.ExecContext(ctx, args...); err != nil {
			return err
		}
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, `ANALYZE`); err != nil {
		return err
	}
	if err := db.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, out)
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func nullFloat(v float64) any {
	if math.IsNaN(v) {
		return nil
	}
	return v
}
