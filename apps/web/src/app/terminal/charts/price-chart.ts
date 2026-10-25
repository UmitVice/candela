import type { ElementRef } from '@angular/core';
import {
  Component,
  DestroyRef,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  linkedSignal,
  output,
  signal,
  viewChild,
} from '@angular/core';
import type { CandlestickData, IChartApi, ISeriesApi, MouseEventParams } from 'lightweight-charts';
import type { Bar, PriceHistory } from '../../core/api/types';
import type { HistoryRange } from '../../core/gateway/market.service';
import { HISTORY_RANGES, MarketService } from '../../core/gateway/market.service';
import { arrowOf, fmtCompact, fmtPct, fmtPrice } from '../../core/util/format';
import { chartTheme, lightweightBase, withAlpha } from './chart-theme';

@Component({
  selector: 'cd-price-chart',
  template: `
    <div class="bar">
      <div class="ranges" role="group" aria-label="Range">
        @for (r of ranges; track r) {
          <button
            type="button"
            class="range"
            [attr.aria-pressed]="range() === r"
            [disabled]="loading()"
            (click)="pick(r)"
          >
            {{ r }}
          </button>
        }
      </div>
      @if (legend(); as l) {
        <div class="legend mono" aria-hidden="true">
          <span>{{ l.t }}</span>
          <span>O {{ fmtPrice(l.o) }}</span>
          <span>H {{ fmtPrice(l.h) }}</span>
          <span>L {{ fmtPrice(l.l) }}</span>
          <span>C {{ fmtPrice(l.c) }}</span>
          <span [class]="l.change >= 0 ? 'up' : 'down'">
            {{ arrowOf(l.change) }} {{ fmtPct(l.change) }}
          </span>
          <span>V {{ fmtCompact(l.v) }}</span>
        </div>
      }
    </div>
    <div
      #host
      class="plot"
      [class.compact]="compact()"
      role="img"
      [attr.aria-label]="ariaLabel()"
    ></div>
    @if (error()) {
      <div class="note down">{{ error() }}</div>
    }
    <div class="note">
      {{ data().source }} · as of {{ data().asOf }} · {{ data().bars.length }} daily bars · chart by
      <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer"
        >TradingView Lightweight Charts™</a
      >
    </div>
  `,
  styleUrl: './charts.css',
})
export class PriceChart {
  private readonly market = inject(MarketService);
  readonly history = input.required<PriceHistory>();
  readonly compact = input(false);
  readonly loaded = output<PriceHistory>();

  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');
  protected readonly ranges = HISTORY_RANGES;
  protected readonly data = linkedSignal(() => this.history());
  protected readonly range = linkedSignal(() => this.history().range as HistoryRange);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly hover = signal<Bar | null>(null);

  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly arrowOf = arrowOf;

  protected readonly legend = computed(() => {
    const bars = this.data().bars;
    const bar = this.hover() ?? bars[bars.length - 1];
    if (!bar) return null;
    const index = bars.findIndex((b) => b.t === bar.t);
    const prev = index > 0 ? bars[index - 1] : undefined;
    return { ...bar, change: prev ? (bar.c / prev.c - 1) * 100 : 0 };
  });

  protected readonly ariaLabel = computed(() => {
    const d = this.data();
    const first = d.bars[0];
    const last = d.bars[d.bars.length - 1];
    if (!first || !last) return `${d.symbol} price chart, no data`;
    const ret = (last.c / first.c - 1) * 100;
    return `${d.symbol} daily candlesticks over ${d.range}: from ${fmtPrice(first.c)} on ${first.t} to ${fmtPrice(last.c)} on ${last.t}, ${fmtPct(ret)}`;
  });

  private chart: IChartApi | null = null;
  private candles: ISeriesApi<'Candlestick'> | null = null;
  private volume: ISeriesApi<'Histogram'> | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      void this.mount().then(() => {
        if (destroyRef.destroyed) this.chart?.remove();
      });
    });
    destroyRef.onDestroy(() => {
      this.chart?.remove();
      this.chart = null;
    });
    effect(() => this.render(this.data()));
  }

  private async mount(): Promise<void> {
    const lw = await import('lightweight-charts');
    const theme = chartTheme();
    const chart = lw.createChart(this.host().nativeElement, {
      ...lightweightBase(theme, this.compact()),
      layout: { ...lightweightBase(theme, this.compact()).layout, attributionLogo: false },
    });
    this.candles = chart.addSeries(lw.CandlestickSeries, {
      upColor: theme.up,
      downColor: theme.down,
      borderVisible: false,
      wickUpColor: theme.up,
      wickDownColor: theme.down,
      priceLineColor: theme.accent,
    });
    this.candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.26 } });
    this.volume = chart.addSeries(lw.HistogramSeries, {
      priceScaleId: 'vol',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      const point = this.candles && param.seriesData.get(this.candles);
      const t = typeof param.time === 'string' ? param.time : null;
      if (!point || !t) {
        this.hover.set(null);
        return;
      }
      this.hover.set(this.data().bars.find((b) => b.t === t) ?? null);
    });
    this.chart = chart;
    this.render(this.data());
  }

  private render(history: PriceHistory): void {
    if (!this.chart || !this.candles || !this.volume) return;
    const theme = chartTheme();
    this.candles.setData(
      history.bars.map((b): CandlestickData<string> => ({
        time: b.t,
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
      })),
    );
    this.volume.setData(
      history.bars.map((b) => ({
        time: b.t,
        value: b.v,
        color: withAlpha(b.c >= b.o ? theme.up : theme.down, 0.35),
      })),
    );
    this.chart.timeScale().fitContent();
  }

  protected async pick(range: HistoryRange): Promise<void> {
    if (range === this.range()) return;
    this.range.set(range);
    this.loading.set(true);
    this.error.set('');
    const next = await this.market.history(this.data().symbol, range);
    this.loading.set(false);
    if (next) {
      this.data.set(next);
      this.loaded.emit(next);
    } else this.error.set(`No ${range} history available right now.`);
  }
}
