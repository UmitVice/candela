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
  signal,
  viewChild,
} from '@angular/core';
import type { IChartApi, ISeriesApi, MouseEventParams, SeriesType } from 'lightweight-charts';
import type { IndicatorPoint, IndicatorSet, PriceHistory } from '../../core/api/types';
import type { IndicatorRange } from '../../core/gateway/market.service';
import { MarketService } from '../../core/gateway/market.service';
import { fmtNumber, fmtPrice } from '../../core/util/format';
import { chartTheme, lightweightBase, withAlpha } from './chart-theme';

type LineKey =
  'sma20' | 'sma50' | 'sma200' | 'bbUpper' | 'bbLower' | 'rsi14' | 'macd' | 'macdSignal';

interface Hover {
  t: string;
  close?: number;
  point?: IndicatorPoint;
}

const RANGES: readonly IndicatorRange[] = ['6M', '1Y', '2Y'];

@Component({
  selector: 'cd-indicators-chart',
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
          <span>C {{ fmtPrice(l.close) }}</span>
          <span
            ><i class="key" [style.background]="colors.sma20"></i>20
            {{ fmtPrice(l.point?.sma20) }}</span
          >
          <span
            ><i class="key" [style.background]="colors.sma50"></i>50
            {{ fmtPrice(l.point?.sma50) }}</span
          >
          <span
            ><i class="key" [style.background]="colors.sma200"></i>200
            {{ fmtPrice(l.point?.sma200) }}</span
          >
          <span>RSI {{ fmtNumber(l.point?.rsi14, 1) }}</span>
          <span>MACD {{ fmtNumber(l.point?.macd) }} / {{ fmtNumber(l.point?.macdSignal) }}</span>
        </div>
      }
    </div>
    <div #host class="plot tall" role="img" [attr.aria-label]="ariaLabel()"></div>
    <div class="note">
      Price with SMA 20/50/200 and Bollinger 20,2 · RSI 14 (30/70) · MACD 12,26,9 · chart by
      <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer"
        >TradingView Lightweight Charts™</a
      >
    </div>
  `,
  styleUrl: './charts.css',
})
export class IndicatorsChart {
  private readonly market = inject(MarketService);
  readonly indicators = input.required<IndicatorSet>();
  readonly history = input<PriceHistory>();

  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');
  protected readonly ranges = RANGES;
  protected readonly data = linkedSignal(() => ({
    indicators: this.indicators(),
    history: this.history() ?? null,
  }));
  protected readonly range = linkedSignal(() => this.indicators().range as IndicatorRange);
  protected readonly loading = signal(false);
  protected readonly hover = signal<Hover | null>(null);
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtNumber = fmtNumber;

  private readonly theme = chartTheme();
  protected readonly colors = {
    sma20: this.theme.info,
    sma50: this.theme.accent,
    sma200: this.theme.reason,
    bb: withAlpha(this.theme.fg2, 0.7),
    rsi: this.theme.tool,
    macd: this.theme.info,
    signal: this.theme.accent,
  };

  private readonly closes = computed(() => {
    const map = new Map<string, number>();
    for (const b of this.data().history?.bars ?? []) map.set(b.t, b.c);
    return map;
  });

  protected readonly legend = computed<Hover | null>(() => {
    const hovered = this.hover();
    if (hovered) return hovered;
    const set = this.data().indicators;
    return { t: set.latest.t, close: set.latest.close, point: set.latest };
  });

  protected readonly ariaLabel = computed(() => {
    const l = this.data().indicators.latest;
    return `${this.data().indicators.symbol} technical chart: close ${fmtPrice(l.close)}, SMA 50 ${fmtPrice(l.sma50)}, SMA 200 ${fmtPrice(l.sma200)}, RSI ${fmtNumber(l.rsi14, 1)}, MACD histogram ${fmtNumber(l.macdHist)}`;
  });

  private chart: IChartApi | null = null;
  private price: ISeriesApi<'Candlestick'> | null = null;
  private lines = new Map<LineKey, ISeriesApi<SeriesType>>();
  private hist: ISeriesApi<'Histogram'> | null = null;

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
    effect(() => this.render(this.data().indicators, this.data().history));
  }

  private async mount(): Promise<void> {
    const lw = await import('lightweight-charts');
    const t = this.theme;
    const base = lightweightBase(t, false);
    const chart = lw.createChart(this.host().nativeElement, {
      ...base,
      layout: { ...base.layout, attributionLogo: false },
    });
    const quiet = {
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    };
    this.price = chart.addSeries(lw.CandlestickSeries, {
      upColor: t.up,
      downColor: t.down,
      borderVisible: false,
      wickUpColor: t.up,
      wickDownColor: t.down,
      priceLineColor: t.fg2,
    });
    const line = (key: LineKey, color: string, pane: number, dashed = false) =>
      this.lines.set(
        key,
        chart.addSeries(
          lw.LineSeries,
          {
            ...quiet,
            color,
            lineWidth: 1,
            lineStyle: dashed ? lw.LineStyle.Dashed : lw.LineStyle.Solid,
          },
          pane,
        ),
      );
    line('bbUpper', this.colors.bb, 0, true);
    line('bbLower', this.colors.bb, 0, true);
    line('sma20', this.colors.sma20, 0);
    line('sma50', this.colors.sma50, 0);
    line('sma200', this.colors.sma200, 0);
    line('rsi14', this.colors.rsi, 1);
    const rsi = this.lines.get('rsi14');
    for (const level of [70, 30]) {
      rsi?.createPriceLine({
        price: level,
        color: withAlpha(level > 50 ? t.down : t.up, 0.6),
        lineWidth: 1,
        lineStyle: lw.LineStyle.Dotted,
        axisLabelVisible: true,
        title: '',
      });
    }
    this.hist = chart.addSeries(lw.HistogramSeries, { ...quiet }, 2);
    line('macd', this.colors.macd, 2);
    line('macdSignal', this.colors.signal, 2);

    const panes = chart.panes();
    panes[0]?.setStretchFactor(3);
    panes[1]?.setStretchFactor(1);
    panes[2]?.setStretchFactor(1);

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      const time = typeof param.time === 'string' ? param.time : null;
      if (!time) {
        this.hover.set(null);
        return;
      }
      const point = this.data().indicators.series.find((p) => p.t === time);
      this.hover.set({ t: time, close: this.closes().get(time), point });
    });
    this.chart = chart;
    this.render(this.data().indicators, this.data().history);
  }

  private render(set: IndicatorSet, history: PriceHistory | null): void {
    if (!this.chart || !this.price || !this.hist) return;
    const t = this.theme;
    const first = set.series[0]?.t ?? '';
    this.price.setData(
      (history?.bars ?? [])
        .filter((b) => b.t >= first)
        .map((b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c })),
    );
    for (const [key, series] of this.lines) {
      series.setData(
        set.series.flatMap((p) => {
          const value = p[key];
          return value === undefined ? [] : [{ time: p.t, value }];
        }),
      );
    }
    this.hist.setData(
      set.series.flatMap((p) =>
        p.macdHist === undefined
          ? []
          : [
              {
                time: p.t,
                value: p.macdHist,
                color: withAlpha(p.macdHist >= 0 ? t.up : t.down, 0.55),
              },
            ],
      ),
    );
    this.chart.timeScale().fitContent();
  }

  protected async pick(range: IndicatorRange): Promise<void> {
    if (range === this.range()) return;
    const symbol = this.data().indicators.symbol;
    this.range.set(range);
    this.loading.set(true);
    const historyRange = range === '6M' ? '1Y' : range === '1Y' ? '2Y' : '5Y';
    const [indicators, history] = await Promise.all([
      this.market.indicators(symbol, range),
      this.market.history(symbol, historyRange),
    ]);
    this.loading.set(false);
    if (indicators) this.data.set({ indicators, history: history ?? this.data().history });
  }
}
