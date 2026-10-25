import { DialogRef } from '@angular/cdk/dialog';
import { Component, computed, inject, resource } from '@angular/core';
import { LucideX } from '@lucide/angular';
import { GatewayService } from '../core/gateway/gateway.service';
import { MarketService } from '../core/gateway/market.service';
import { arrowOf, fmtCompact, fmtNumber, fmtPct, fmtPrice, toneOf } from '../core/util/format';
import { CanvasSpark } from '../ui/canvas-spark';
import { ShellStateService } from './shell-state.service';
import { StatusDetails } from './status-details';

@Component({
  selector: 'cd-context-panel',
  imports: [StatusDetails, LucideX, CanvasSpark],
  templateUrl: './context-panel.html',
  styleUrl: './context-panel.css',
  host: { role: 'complementary', 'aria-label': 'Context' },
})
export class ContextPanel {
  protected readonly shell = inject(ShellStateService);
  private readonly market = inject(MarketService);
  private readonly gateway = inject(GatewayService);
  private readonly dialogRef = inject(DialogRef, { optional: true });
  protected readonly inSheet = !!this.dialogRef;
  protected readonly variant =
    (this.dialogRef?.config.data as { variant?: 'status' } | undefined)?.variant ?? 'context';

  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly toneOf = toneOf;
  protected readonly arrowOf = arrowOf;
  protected readonly fmtNumber = fmtNumber;

  private readonly focus = computed(() => ({
    symbol: this.variant === 'context' ? this.shell.focusSymbol() : null,
    mode: this.gateway.connection().mode,
    baseUrl: this.gateway.connection().baseUrl,
  }));

  protected readonly quote = resource({
    params: this.focus,
    loader: ({ params }) =>
      params.symbol ? this.market.quote(params.symbol) : Promise.resolve(null),
  });

  protected readonly history = resource({
    params: this.focus,
    loader: ({ params }) =>
      params.symbol ? this.market.history(params.symbol, '3M') : Promise.resolve(null),
  });

  protected readonly indicators = resource({
    params: this.focus,
    loader: ({ params }) =>
      params.symbol ? this.market.indicators(params.symbol, '6M') : Promise.resolve(null),
  });

  protected readonly forecast = resource({
    params: this.focus,
    loader: ({ params }) =>
      params.symbol ? this.market.forecast(params.symbol) : Promise.resolve(null),
  });

  protected readonly closes = computed(() =>
    this.history.hasValue() ? (this.history.value()?.bars.map((b) => b.c) ?? []) : [],
  );

  protected readonly keyIndicators = computed(() => {
    const set = this.indicators.hasValue() ? this.indicators.value() : null;
    if (!set) return null;
    const l = set.latest;
    const rel = (v: number | undefined) =>
      v === undefined || v === 0 ? undefined : ((l.close - v) / v) * 100;
    return {
      rsi: l.rsi14,
      rsiNote:
        l.rsi14 === undefined
          ? ''
          : l.rsi14 > 70
            ? 'overbought'
            : l.rsi14 < 30
              ? 'oversold'
              : 'neutral',
      vs50: rel(l.sma50),
      vs200: rel(l.sma200),
      macdHist: l.macdHist,
      signals: set.signals.slice(0, 4),
      asOf: set.asOf,
    };
  });

  protected readonly fan = computed(() => {
    const f = this.forecast.hasValue() ? this.forecast.value() : null;
    if (!f) return null;
    const lo = Math.min(f.basePrice, ...f.horizons.map((h) => h.p10));
    const hi = Math.max(f.basePrice, ...f.horizons.map((h) => h.p90));
    const span = hi - lo || 1;
    const pos = (v: number) => ((v - lo) / span) * 100;
    return {
      source: f.source === 'baseline' ? 'Statistical baseline' : 'Vaniras',
      asOf: f.asOf,
      base: pos(f.basePrice),
      rows: f.horizons.map((h) => ({
        months: h.months,
        left: pos(h.p10),
        width: pos(h.p90) - pos(h.p10),
        mid: pos(h.p50),
        p50: h.p50,
        delta: (h.p50 / f.basePrice - 1) * 100,
      })),
    };
  });

  protected readonly rangePct = computed(() => {
    const q = this.quote.hasValue() ? this.quote.value() : null;
    if (!q) return 50;
    const span = q.fiftyTwoWeekHigh - q.fiftyTwoWeekLow;
    return span > 0 ? Math.min(100, Math.max(0, ((q.close - q.fiftyTwoWeekLow) / span) * 100)) : 50;
  });

  protected close(): void {
    this.dialogRef?.close();
  }

  protected analyze(symbol: string): void {
    this.shell.insert(`/analyze ${symbol}`);
    this.close();
  }
}
