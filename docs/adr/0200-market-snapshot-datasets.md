# 0200 — Market snapshot datasets

- Status: accepted
- Date: 2026-10-23

## Context

ADR 0007 requires a permissively licensed public Hugging Face dataset for daily prices, read offline into a read-only SQLite snapshot. The brief asks for the S&P 500, the Nasdaq-100 and major ETFs (SPY, QQQ, DIA, IWM, the 11 Select Sector SPDRs) with at least five years of daily OHLCV, and optionally a permissive SEC financial-statements dataset instead of live SEC calls (which need a contact e-mail in the User-Agent). Candidates evaluated on 2026-10-23:

| Dataset | License | Coverage / recency | Verdict |
|---|---|---|---|
| `vessel888/us-stocks-daily-all`, `younginpiniti/us-stocks-daily-all` | none declared | 799 k rows, last update 2026-03/09 | rejected: no license, too small |
| `AYUSHKHAIRE/all-stock-market-data-daily-updates` | CC0-1.0 | 17 k stocks, daily, no ETFs; last bar captured intraday (partial volume) | rejected: no ETFs, incomplete last bar |
| `AmirTrader/YahooFinance` | MIT | 6.8 k stocks, no ETFs | rejected: no ETFs |
| `paperswithbacktest/*-Daily-Price` | other, gated | | rejected: gated, unclear license |
| **`defeatbeta/yahoo-finance-data`** | **ODC-By-1.0** | 37 M rows, US stocks plus SPY/DIA/IWM since the 1990s, updated daily (asOf 2026-10-22, full-day volumes), one parquet sorted by symbol | **prices** |
| **`AlphaDojo/dojo_stock_kline`** | **Apache-2.0** | US/CN/HK daily bars since 2025-01-02 incl. all sector SPDRs and QQQ, split-adjusted | **gap filler** |
| **`ZipLime/company-fundamentals`** | **Apache-2.0** | SEC XBRL as filed, point in time, 2009 → 2026-06-30, with a public pipeline | **fundamentals** |

## Decision

- `cmd/snapshot` reads all three datasets pinned to their current commit (recorded in `meta.source`), with HTTP range requests through the egress-restricted client, so only needed row groups and columns are downloaded (~470 MB of prices, ~70 MB of fundamentals instead of several GB).
- Universe: S&P 500 and Nasdaq-100 constituents taken from Wikipedia on 2026-10-23 (`internal/snapshot/universe/*.txt`) plus the 15 ETFs (533 symbols).
- Prices come from defeatbeta; symbols that are missing or stale there by more than 7 days are filled or extended from AlphaDojo (sector SPDRs, and QQQ after 2026-09-11). Class shares use the contract's dot form (`BRK.B`).
- Fundamentals come from ZipLime `fundamentals_wide` (last 10 years), joined to tickers by CIK through the SEC `company_tickers.json` mirrored in the defeatbeta repository. Annual = `period_kind=year` from 10-K, quarterly = discrete `quarter` rows; restatements are resolved column by column (latest filing wins, earlier filings fill gaps); fiscal labels come from the original filing. The tool reports `source: "sec"` because these are SEC filings as reported. The live SEC company-facts adapter is not implemented: the snapshot replaces it, and `SEC_USER_AGENT` stays unused until a live provider is added.
- The snapshot file stays git-ignored; `CANDELA_SNAPSHOT_URL` can download a prebuilt one.

## Consequences

- Result of the first build: asOf 2026-10-22, 533 symbols, 505 with ≥ 5 years of history; the sector SPDRs have history from 2025-01-02 only (≈ 1.8 years), so their 5Y views are shorter. Fundamentals asOf 2026-09-29 (latest filing), 10 950 statement rows; ETFs have none (`data_unavailable`).
- Period ends in ZipLime are normalised to month ends (Apple FY2025 shows 2025-09-30, not 2025-09-27).
- All three sources ultimately derive from Yahoo Finance (prices) and SEC EDGAR (fundamentals); we rely on the licenses declared by the dataset publishers, attribute them in `meta.license`, and never redistribute the snapshot from this repository.
- Rebuilding takes ~11 minutes on the Mac (`make gateway-snapshot`).

## Alternatives considered

- Stooq and live SEC: blocked (ADR 0007).
- One dataset for everything: none of the candidates had permissive licensing, ETFs, ≥ 5 years and daily freshness at once.
