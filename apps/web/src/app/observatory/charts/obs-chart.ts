import type { ElementRef } from '@angular/core';
import {
  Component,
  DestroyRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import type { EChartsCoreOption, EChartsType } from 'echarts/core';
import { LayoutService } from '../../shell/layout.service';
import { init } from './echarts-obs';

@Component({
  selector: 'cd-obs-chart',
  template: `<div #plot class="plot" role="img" [attr.aria-label]="label()"></div>`,
  styles: `
    :host {
      display: block;
    }
    .plot {
      width: 100%;
      height: var(--chart-h, 220px);
      contain: strict;
    }
  `,
})
export class ObsChart {
  readonly option = input.required<EChartsCoreOption | null>();
  readonly label = input.required<string>();

  private readonly plot = viewChild.required<ElementRef<HTMLDivElement>>('plot');
  private readonly reduced = inject(LayoutService).reducedMotion;
  private chart: EChartsType | null = null;

  constructor() {
    let observer: ResizeObserver | undefined;
    afterNextRender(() => {
      const el = this.plot().nativeElement;
      this.chart = init(el, undefined, { renderer: 'canvas' });
      observer = new ResizeObserver(() => this.chart?.resize());
      observer.observe(el);
      this.apply();
    });
    effect(() => {
      this.option();
      this.apply();
    });
    inject(DestroyRef).onDestroy(() => {
      observer?.disconnect();
      this.chart?.dispose();
      this.chart = null;
    });
  }

  private apply(): void {
    const option = this.option();
    if (!this.chart || !option) return;
    this.chart.setOption({ animation: !this.reduced, ...option }, true);
  }
}
