import { Component, computed, input } from '@angular/core';

@Component({
  selector: 'cd-sparkline',
  template: `
    <svg
      class="spark"
      viewBox="0 0 400 72"
      preserveAspectRatio="none"
      role="img"
      [attr.aria-label]="label()"
    >
      <defs>
        <linearGradient [attr.id]="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" [attr.stop-color]="color()" stop-opacity="0.28" />
          <stop offset="1" [attr.stop-color]="color()" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path [attr.d]="area()" [attr.fill]="'url(#' + gradientId + ')'" />
      <path
        [attr.d]="line()"
        fill="none"
        [attr.stroke]="color()"
        stroke-width="1.5"
        vector-effect="non-scaling-stroke"
      />
    </svg>
  `,
  styleUrl: './cards.css',
})
export class Sparkline {
  readonly values = input.required<number[]>();
  readonly label = input('Price sparkline');
  protected readonly gradientId = `spark-${Math.random().toString(36).slice(2, 9)}`;

  private readonly points = computed(() => {
    const v = this.values();
    if (v.length < 2) return [] as [number, number][];
    const min = Math.min(...v);
    const max = Math.max(...v);
    const span = max - min || 1;
    return v.map((y, i): [number, number] => [
      (i / (v.length - 1)) * 400,
      66 - ((y - min) / span) * 60,
    ]);
  });

  protected readonly line = computed(() =>
    this.points()
      .map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(''),
  );
  protected readonly area = computed(() =>
    this.points().length ? `${this.line()}L400,72L0,72Z` : '',
  );
  protected readonly color = computed(() => {
    const v = this.values();
    return (v[v.length - 1] ?? 0) >= (v[0] ?? 0) ? '#2ebd85' : '#f6465d';
  });
}
