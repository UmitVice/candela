package snapshot

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"
)

type fundRow struct {
	symbol, period, fp, end, filed string
	fy                             int
	values                         [12]float64
}

type rawFact struct {
	cik, accession, kind, form, fp string
	fy                             int
	end, filed                     int32
	accepted                       int64
	values                         [12]float64
	costOfRevenue                  float64
}

var fundValueColumns = [12]string{"revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
	"operating_cash_flow", "capital_expenditure", "total_assets", "total_liabilities", "cash_and_equivalents",
	"long_term_debt", "shares_outstanding"}

func epochDate(days int32) string {
	return time.Unix(int64(days)*86400, 0).UTC().Format(dateLayout)
}

func fundamentals(ctx context.Context, info datasetInfo, u map[string]*member, minYear int, log *slog.Logger) ([]fundRow, error) {
	byCIK := map[string][]string{}
	for s, m := range u {
		if m.cik != "" && m.kind == "stock" {
			byCIK[m.cik] = append(byCIK[m.cik], s)
		}
	}
	var files []string
	var total int64
	for _, s := range info.Siblings {
		rest, ok := strings.CutPrefix(s.RFilename, "data/fundamentals_wide/period_year=")
		if !ok || !strings.HasSuffix(rest, ".parquet") {
			continue
		}
		year, err := strconv.Atoi(strings.SplitN(rest, "/", 2)[0])
		if err != nil || year < minYear {
			continue
		}
		files = append(files, s.RFilename)
		total += s.Size
	}
	slices.Sort(files)
	log.Info("reading fundamentals", "dataset", fundDataset, "files", len(files), "sizeMB", total>>20, "companies", len(byCIK))

	var facts []rawFact
	ownEnd := map[string]int32{}
	var downloaded int64
	for i, path := range files {
		f, rf, err := openParquet(ctx, fileURL(fundDataset, info.SHA, path), sizeOf(info, path))
		if err != nil {
			return nil, err
		}
		cols := map[string]int{}
		names := append([]string{"cik", "accession_number", "period_end", "period_kind", "form", "fiscal_year",
			"fiscal_period", "filed_date", "accepted_at", "currency", "cost_of_revenue"}, fundValueColumns[:]...)
		for _, c := range names {
			if cols[c], err = columnIndex(f, c); err != nil {
				return nil, fmt.Errorf("%s: %w", path, err)
			}
		}
		for _, rg := range f.RowGroups() {
			ciks, err := stringColumn(rg, cols["cik"])
			if err != nil {
				return nil, err
			}
			keep := make([]bool, len(ciks))
			any := false
			for r, c := range ciks {
				if _, ok := byCIK[c]; ok {
					keep[r], any = true, true
				}
			}
			if !any {
				continue
			}
			str := map[string][]string{}
			for _, c := range []string{"accession_number", "period_kind", "form", "fiscal_period", "currency"} {
				if str[c], err = stringColumn(rg, cols[c]); err != nil {
					return nil, err
				}
			}
			num := map[string][]int64{}
			for _, c := range []string{"period_end", "fiscal_year", "filed_date", "accepted_at"} {
				if num[c], err = ints(rg, cols[c], keep); err != nil {
					return nil, err
				}
			}
			var vals [12][]float64
			for k, c := range fundValueColumns {
				if vals[k], err = numbers(rg, cols[c], 0, keep); err != nil {
					return nil, err
				}
			}
			cost, err := numbers(rg, cols["cost_of_revenue"], 0, keep)
			if err != nil {
				return nil, err
			}
			for r := range ciks {
				if !keep[r] {
					continue
				}
				acc, end := str["accession_number"][r], int32(num["period_end"][r])
				if end > ownEnd[acc] {
					ownEnd[acc] = end
				}
				kind, form, cur := str["period_kind"][r], str["form"][r], str["currency"][r]
				if (kind != "year" && kind != "quarter") || (cur != "" && cur != "USD") ||
					(!strings.HasPrefix(form, "10-K") && !strings.HasPrefix(form, "10-Q")) {
					continue
				}
				fact := rawFact{cik: ciks[r], accession: acc, kind: kind, form: form, fp: str["fiscal_period"][r],
					fy: int(num["fiscal_year"][r]), end: end, filed: int32(num["filed_date"][r]), accepted: num["accepted_at"][r],
					costOfRevenue: cost[r]}
				for k := range vals {
					fact.values[k] = vals[k][r]
				}
				facts = append(facts, fact)
			}
		}
		downloaded += rf.read
		if (i+1)%20 == 0 {
			log.Info("fundamentals progress", "files", i+1, "of", len(files), "downloadedMB", downloaded>>20)
		}
	}

	type key struct {
		cik, kind string
		end       int32
	}
	groups := map[key][]rawFact{}
	for _, f := range facts {
		k := key{f.cik, f.kind, f.end}
		groups[k] = append(groups[k], f)
	}
	perSymbol := map[string][]fundRow{}
	for k, rows := range groups {
		slices.SortFunc(rows, func(a, b rawFact) int { return int(a.accepted - b.accepted) })
		first := rows[0]
		years := int(math.Round(float64(ownEnd[first.accession]-first.end) / 365.25))
		row := fundRow{fy: first.fy - years, end: epochDate(k.end), filed: epochDate(first.filed), period: "annual", fp: "FY"}
		if k.kind == "quarter" {
			row.period, row.fp = "quarterly", first.fp
			if row.fp == "FY" || row.fp == "" {
				row.fp = "Q4"
			}
		}
		for i := range row.values {
			row.values[i] = nan
			for j := len(rows) - 1; j >= 0; j-- {
				if v := rows[j].values[i]; !math.IsNaN(v) {
					row.values[i] = v
					break
				}
			}
		}
		if math.IsNaN(row.values[1]) && !math.IsNaN(row.values[0]) {
			for j := len(rows) - 1; j >= 0; j-- {
				if c := rows[j].costOfRevenue; !math.IsNaN(c) {
					row.values[1] = row.values[0] - c
					break
				}
			}
		}
		for _, sym := range byCIK[k.cik] {
			r := row
			r.symbol = sym
			perSymbol[sym+"|"+row.period] = append(perSymbol[sym+"|"+row.period], r)
		}
	}
	var out []fundRow
	for k, rows := range perSymbol {
		slices.SortFunc(rows, func(a, b fundRow) int { return strings.Compare(b.end, a.end) })
		limit := 10
		if strings.HasSuffix(k, "|quarterly") {
			limit = 12
		}
		out = append(out, rows[:min(limit, len(rows))]...)
	}
	log.Info("fundamentals loaded", "rows", len(out), "facts", len(facts), "downloadedMB", downloaded>>20)
	return out, nil
}
