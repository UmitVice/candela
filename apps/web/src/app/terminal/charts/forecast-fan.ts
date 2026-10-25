import type { ElementRef } from '@angular/core';
import {
  Component,
  DestroyRef,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import type { EChartsType } from 'echarts/core';
import type { Forecast } from '../../core/api/types';
import { fmtPrice } from '../../core/util/format';
import { chartTheme, withAlpha } from './chart-theme';

@Component({
  selector: 'cd-forecast-fan',
  template: `
    <div class="bar">
      <div class="badges">
        <span class="badge source">{{ sourceLabel() }}</span>
        <span class="badge">{{ forecast().method }}</span>
      </div>
      <span class="legend mono">
        <span><i class="key" [style.background]="bandColor"></i>P10–P90</span>
        <span><i class="key" [style.background]="midColor"></i>P50</span>
      </span>
    </div>
    <div #host class="plot" role="img" [attr.aria-label]="ariaLabel()"></div>
  `,
  styleUrl: './charts.css',
})
export class ForecastFan {
  readonly forecast = input.required<Forecast>();
  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');
  private readonly theme = chartTheme();
  protected readonly bandColor = withAlpha(this.theme.accent, 0.35);
  protected readonly midColor = this.theme.accent;

  protected readonly sourceLabel = computed(() =>
    this.forecast().source === 'baseline' ? 'Statistical baseline' : 'Vaniras forecast',
  );

  protected readonly ariaLabel = computed(() => {
    const f = this.forecast();
    const parts = f.horizons.map(
      (h) =>
        `${h.months} months: ${fmtPrice(h.p10)} to ${fmtPrice(h.p90)}, median ${fmtPrice(h.p50)}`,
    );
    return `${f.symbol} forecast fan from base ${fmtPrice(f.basePrice)}. ${parts.join('; ')}`;
  });

  private chart: EChartsType | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);
    let observer: ResizeObserver | undefined;
    afterNextRender(() => {
      void import('./echarts-setup').then((echarts) => {
        if (destroyRef.destroyed) return;
        const el = this.host().nativeElement;
        this.chart = echarts.init(el, null, { renderer: 'canvas' });
        observer = new ResizeObserver(() => this.chart?.resize());
        observer.observe(el);
        this.render(this.forecast());
      });
    });
    destroyRef.onDestroy(() => {
      observer?.disconnect();
      this.chart?.dispose();
      this.chart = null;
    });
    effect(() => this.render(this.forecast()));
  }

  private render(f: Forecast): void {
    if (!this.chart) return;
    const t = this.theme;
    const labels = [`now\n${f.asOf}`, ...f.horizons.map((h) => `${h.months}M\n${h.targetDate}`)];
    const p10 = [f.basePrice, ...f.horizons.map((h) => h.p10)];
    const p50 = [f.basePrice, ...f.horizons.map((h) => h.p50)];
    const p90 = [f.basePrice, ...f.horizons.map((h) => h.p90)];
    const spread = p90.map((v, i) => +(v - (p10[i] ?? 0)).toFixed(4));
    const text = { color: t.fg2, fontFamily: t.mono, fontSize: 10 };
    this.chart.setOption(
      {
        animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
        grid: { left: 8, right: 64, top: 12, bottom: 8, containLabel: true },
        tooltip: {
          trigger: 'axis',
          renderMode: 'richText',
          backgroundColor: t.bg,
          borderColor: t.lineStrong,
          textStyle: { color: t.fg0, fontFamily: t.mono, fontSize: 11 },
          formatter: (params: unknown) => {
            const index = (params as { dataIndex: number }[])[0]?.dataIndex ?? 0;
            const label = labels[index]?.replace('\n', ' · ') ?? '';
            return `${label}\nP90 ${fmtPrice(p90[index])}\nP50 ${fmtPrice(p50[index])}\nP10 ${fmtPrice(p10[index])}`;
          },
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: labels,
          axisLine: { lineStyle: { color: t.line } },
          axisTick: { show: false },
          axisLabel: { ...text, lineHeight: 13 },
        },
        yAxis: {
          type: 'value',
          scale: true,
          position: 'right',
          splitLine: { lineStyle: { color: withAlpha(t.line, 0.6) } },
          axisLabel: text,
        },
        series: [
          {
            name: 'P10',
            type: 'line',
            data: p10,
            stack: 'band',
            symbol: 'none',
            lineStyle: { width: 1, color: withAlpha(t.down, 0.6) },
          },
          {
            name: 'P10–P90',
            type: 'line',
            data: spread,
            stack: 'band',
            symbol: 'none',
            lineStyle: { width: 1, color: withAlpha(t.up, 0.6) },
            areaStyle: { color: this.bandColor },
            tooltip: { show: false },
          },
          {
            name: 'P50',
            type: 'line',
            data: p50,
            symbol: 'circle',
            symbolSize: 5,
            lineStyle: { width: 2, color: t.accent },
            itemStyle: { color: t.accent },
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: t.fg2, type: 'dashed', width: 1 },
              label: { ...text, formatter: `base ${fmtPrice(f.basePrice)}`, position: 'end' },
              data: [{ yAxis: f.basePrice }],
            },
          },
        ],
      },
      true,
    );
  }
}
