package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/UmitVice/candela/services/gateway/internal/observability"
	"github.com/UmitVice/candela/services/gateway/internal/snapshot"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	out := flag.String("out", env("CANDELA_SNAPSHOT_PATH", "services/gateway/data/market.sqlite"), "output SQLite path")
	years := flag.Int("years", 6, "years of daily bars to keep")
	fundYears := flag.Int("fund-years", 10, "years of financial statements to keep")
	symbols := flag.String("symbols-url", env("CANDELA_SYMBOLS_BASE_URL", "https://www.nasdaqtrader.com/dynamic/SymDir"), "Nasdaq Trader symbol directory base URL")
	flag.Parse()

	log := observability.NewLogger(env("CANDELA_LOG_LEVEL", "info"))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, 2*time.Hour)
	defer cancel()

	start := time.Now()
	sum, err := snapshot.Build(ctx, snapshot.Options{Out: *out, Years: *years, FundYears: *fundYears, SymbolsBaseURL: *symbols, Log: log})
	if err != nil {
		fmt.Fprintln(os.Stderr, "snapshot:", err)
		os.Exit(1)
	}
	log.Info("snapshot written", "path", *out, "asOf", sum.AsOf, "symbols", sum.Symbols, "fiveYearCoverage", sum.FiveYearCoverage,
		"fundamentalRows", sum.Fundamentals, "missing", sum.Missing, "duration", time.Since(start).Round(time.Second).String())
}
