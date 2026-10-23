package market

import (
	"bufio"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/UmitVice/candela/services/gateway/internal/store"
	"github.com/UmitVice/candela/services/gateway/internal/store/db"
)

const directoryRefreshedKey = "symbols.refreshedAt"

type dirEntry struct {
	SymbolInfo
	tokens  []string
	covered bool
}

type Directory struct {
	store   *store.Store
	snap    *Snapshot
	baseURL string
	client  *http.Client
	log     *slog.Logger

	mu      sync.RWMutex
	entries []dirEntry
	bySym   map[string]int
	loaded  time.Time
}

func NewDirectory(st *store.Store, snap *Snapshot, baseURL string, log *slog.Logger) *Directory {
	return &Directory{store: st, snap: snap, baseURL: strings.TrimRight(baseURL, "/"), log: log,
		client: &http.Client{Timeout: 30 * time.Second}, bySym: map[string]int{}}
}

func (d *Directory) Load(ctx context.Context) error {
	rows, err := d.store.Q.ListSymbols(ctx)
	if err != nil {
		return err
	}
	d.rebuild(rows)
	return nil
}

func (d *Directory) rebuild(rows []db.Symbol) {
	entries := make([]dirEntry, 0, len(rows)+64)
	seen := map[string]bool{}
	add := func(info SymbolInfo) {
		if seen[info.Symbol] {
			return
		}
		seen[info.Symbol] = true
		covered := false
		if d.snap != nil {
			_, covered = d.snap.Symbol(info.Symbol)
		}
		entries = append(entries, dirEntry{SymbolInfo: info, tokens: tokenize(info.Name), covered: covered})
	}
	for _, r := range rows {
		add(SymbolInfo{Symbol: r.Symbol, Name: r.Name, Exchange: r.Exchange})
	}
	if d.snap != nil {
		for _, s := range d.snap.Symbols() {
			add(s.SymbolInfo)
		}
	}
	slices.SortFunc(entries, func(a, b dirEntry) int { return strings.Compare(a.Symbol, b.Symbol) })
	idx := make(map[string]int, len(entries))
	for i, e := range entries {
		idx[e.Symbol] = i
	}
	d.mu.Lock()
	d.entries, d.bySym, d.loaded = entries, idx, time.Now()
	d.mu.Unlock()
}

func (d *Directory) Size() int {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return len(d.entries)
}

func (d *Directory) Lookup(sym string) (SymbolInfo, bool) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	i, ok := d.bySym[sym]
	if !ok {
		return SymbolInfo{}, false
	}
	return d.entries[i].SymbolInfo, true
}

func tokenize(s string) []string {
	return strings.FieldsFunc(strings.ToLower(s), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) })
}

func (d *Directory) Search(q string, limit int) []SymbolInfo {
	q = strings.TrimSpace(q)
	upper := strings.ToUpper(q)
	qTokens := tokenize(q)
	type hit struct {
		e    dirEntry
		rank int
	}
	var hits []hit
	d.mu.RLock()
	for _, e := range d.entries {
		switch {
		case e.Symbol == upper:
			hits = append(hits, hit{e, 0})
		case strings.HasPrefix(e.Symbol, upper):
			hits = append(hits, hit{e, 1})
		case len(qTokens) > 0 && matchesTokens(e.tokens, qTokens):
			hits = append(hits, hit{e, 2})
		}
	}
	d.mu.RUnlock()
	slices.SortStableFunc(hits, func(a, b hit) int {
		if a.rank != b.rank {
			return a.rank - b.rank
		}
		if a.e.covered != b.e.covered {
			if a.e.covered {
				return -1
			}
			return 1
		}
		if a.rank == 1 && len(a.e.Symbol) != len(b.e.Symbol) {
			return len(a.e.Symbol) - len(b.e.Symbol)
		}
		if a.rank == 2 && len(a.e.Name) != len(b.e.Name) {
			return len(a.e.Name) - len(b.e.Name)
		}
		return strings.Compare(a.e.Symbol, b.e.Symbol)
	})
	out := make([]SymbolInfo, 0, min(limit, len(hits)))
	for _, h := range hits {
		if len(out) == limit {
			break
		}
		out = append(out, h.e.SymbolInfo)
	}
	return out
}

func matchesTokens(name, q []string) bool {
	for _, t := range q {
		if !slices.ContainsFunc(name, func(n string) bool { return strings.HasPrefix(n, t) }) {
			return false
		}
	}
	return true
}

func (d *Directory) RefreshLoop(ctx context.Context, every time.Duration) {
	d.refreshIfStale(ctx, every)
	t := time.NewTicker(time.Hour)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			d.refreshIfStale(ctx, every)
		}
	}
}

func (d *Directory) refreshIfStale(ctx context.Context, every time.Duration) {
	kv, err := d.store.Q.GetKV(ctx, directoryRefreshedKey)
	if err == nil && time.Since(time.Unix(kv.UpdatedAt, 0)) < every {
		return
	}
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		d.log.Warn("symbol directory state", "err", err)
	}
	if err := d.Refresh(ctx); err != nil {
		d.log.Warn("symbol directory refresh failed", "err", err)
	}
}

func (d *Directory) Refresh(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	var all []db.InsertSymbolParams
	for _, f := range []string{"nasdaqlisted.txt", "otherlisted.txt"} {
		rows, err := d.fetch(ctx, f)
		if err != nil {
			return fmt.Errorf("%s: %w", f, err)
		}
		all = append(all, rows...)
	}
	if len(all) < 1000 {
		return fmt.Errorf("symbol directory suspiciously small (%d rows)", len(all))
	}
	tx, err := d.store.DB.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	q := d.store.Q.WithTx(tx)
	if err := q.DeleteSymbols(ctx); err != nil {
		return err
	}
	for _, r := range all {
		if err := q.InsertSymbol(ctx, r); err != nil {
			return err
		}
	}
	now := time.Now()
	if err := q.SetKV(ctx, db.SetKVParams{Key: directoryRefreshedKey, Value: now.UTC().Format(time.RFC3339), UpdatedAt: now.Unix()}); err != nil {
		return err
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	d.log.Info("symbol directory refreshed", "symbols", len(all))
	return d.Load(ctx)
}

var otherExchanges = map[string]string{"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}

func (d *Directory) fetch(ctx context.Context, file string) ([]db.InsertSymbolParams, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, d.baseURL+"/"+file, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "candela-gateway/1 (+https://github.com/UmitVice/candela)")
	resp, err := d.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return parseDirectory(io.LimitReader(resp.Body, 16<<20), file == "otherlisted.txt")
}

func parseDirectory(r io.Reader, other bool) ([]db.InsertSymbolParams, error) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64<<10), 1<<20)
	var header []string
	var out []db.InsertSymbolParams
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		if header == nil {
			header = strings.Split(line, "|")
			continue
		}
		if strings.HasPrefix(line, "File Creation Time") {
			break
		}
		f := strings.Split(line, "|")
		if len(f) != len(header) {
			continue
		}
		get := func(name string) string {
			if i := slices.Index(header, name); i >= 0 {
				return strings.TrimSpace(f[i])
			}
			return ""
		}
		symCol, exchange := "Symbol", "NASDAQ"
		if other {
			symCol, exchange = "ACT Symbol", otherExchanges[get("Exchange")]
			if exchange == "" {
				exchange = "OTHER"
			}
		}
		sym := get(symCol)
		if get("Test Issue") == "Y" || !ValidSymbol(sym) {
			continue
		}
		etf := int64(0)
		if get("ETF") == "Y" {
			etf = 1
		}
		out = append(out, db.InsertSymbolParams{Symbol: sym, Name: cleanName(get("Security Name")), Exchange: exchange, IsEtf: etf})
	}
	return out, sc.Err()
}

var nameSuffixes = []string{" Common Stock", " Common Shares", " Ordinary Shares", " American Depositary Shares", " Depositary Shares", " Shares"}

func cleanName(s string) string {
	main, rest, found := strings.Cut(s, " - ")
	if found {
		if i := strings.Index(rest, "Class "); i >= 0 && len(rest) >= i+7 {
			main += " " + rest[i:i+7]
		}
	}
	for _, suf := range nameSuffixes {
		main = strings.TrimSuffix(main, suf)
	}
	return strings.TrimSpace(main)
}
