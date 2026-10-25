import { Component, computed, input } from '@angular/core';
import type { Forecast } from '../../core/api/types';
import { arrowOf, fmtPct, fmtPrice } from '../../core/util/format';
import { ForecastFan } from '../charts/forecast-fan';

@Component({
  selector: 'cd-forecast-card',
  imports: [ForecastFan],
  template: `
    @let f = forecast();
    <div class="headline">
      <span class="big">{{ f.symbol }} · forecast</span>
      <span class="muted">base {{ fmtPrice(f.basePrice) }} · as of {{ f.asOf }}</span>
    </div>
    <cd-forecast-fan [forecast]="f" />
    <div class="table-wrap" style="margin-top: 10px">
      <table>
        <thead>
          <tr>
            <th>Horizon</th>
            <th>P10</th>
            <th>P50</th>
            <th>P90</th>
            <th>P50 vs base</th>
            <th class="bar-cell">Band</th>
          </tr>
        </thead>
        <tbody>
          @for (h of rows(); track h.months) {
            <tr>
              <td>{{ h.months }}M · {{ h.targetDate }}</td>
              <td>{{ fmtPrice(h.p10) }}</td>
              <td>{{ fmtPrice(h.p50) }}</td>
              <td>{{ fmtPrice(h.p90) }}</td>
              <td [class]="h.delta >= 0 ? 'up' : 'down'">
                {{ arrowOf(h.delta) }} {{ fmtPct(h.delta) }}
              </td>
              <td class="bar-cell">
                <div class="fan" [attr.aria-label]="'P10 to P90 band for ' + h.months + ' months'">
                  <div class="fan-band" [style.left.%]="h.left" [style.width.%]="h.width"></div>
                  <div class="fan-base" [style.left.%]="h.base"></div>
                  <div class="fan-mid" [style.left.%]="h.mid"></div>
                </div>
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
    <div class="note">{{ f.method }}. {{ f.disclaimer }}</div>
  `,
  styleUrl: './cards.css',
})
export class ForecastCard {
  readonly forecast = input.required<Forecast>();
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly arrowOf = arrowOf;

  protected readonly rows = computed(() => {
    const f = this.forecast();
    const lo = Math.min(f.basePrice, ...f.horizons.map((h) => h.p10));
    const hi = Math.max(f.basePrice, ...f.horizons.map((h) => h.p90));
    const span = hi - lo || 1;
    const pos = (v: number) => ((v - lo) / span) * 100;
    return f.horizons.map((h) => ({
      ...h,
      delta: (h.p50 / f.basePrice - 1) * 100,
      left: pos(h.p10),
      width: pos(h.p90) - pos(h.p10),
      mid: pos(h.p50),
      base: pos(f.basePrice),
    }));
  });
}
