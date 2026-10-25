import { Component, computed, input, linkedSignal } from '@angular/core';
import type { PriceHistory } from '../../core/api/types';
import { arrowOf, fmtCompact, fmtPct, fmtPrice, toneOf } from '../../core/util/format';
import { PriceChart } from '../charts/price-chart';

@Component({
  selector: 'cd-history-card',
  imports: [PriceChart],
  template: `
    @let s = stats();
    @if (s) {
      <div class="headline">
        <span class="big">{{ current().symbol }} · {{ current().range }}</span>
        <span [class]="toneOf(s.returnPct)"
          >{{ arrowOf(s.returnPct) }} {{ fmtPct(s.returnPct) }}</span
        >
        <span class="muted">{{ s.first.t }} → {{ s.last.t }}</span>
      </div>
      <cd-price-chart [history]="history()" (loaded)="current.set($event)" />
      <dl class="grid stats">
        <div>
          <dt>Start</dt>
          <dd>{{ fmtPrice(s.first.c) }}</dd>
        </div>
        <div>
          <dt>End</dt>
          <dd>{{ fmtPrice(s.last.c) }}</dd>
        </div>
        <div>
          <dt>High</dt>
          <dd>{{ fmtPrice(s.high) }}</dd>
        </div>
        <div>
          <dt>Low</dt>
          <dd>{{ fmtPrice(s.low) }}</dd>
        </div>
        <div>
          <dt>Max drawdown</dt>
          <dd class="down">▼ {{ fmtPct(s.maxDrawdownPct) }}</dd>
        </div>
        <div>
          <dt>Avg volume</dt>
          <dd>{{ fmtCompact(s.avgVolume) }}</dd>
        </div>
      </dl>
    } @else {
      <div class="muted">No price bars returned.</div>
    }
  `,
  styleUrl: './cards.css',
  styles: `
    .stats {
      margin-top: 10px;
    }
  `,
})
export class HistoryCard {
  readonly history = input.required<PriceHistory>();
  protected readonly current = linkedSignal(() => this.history());
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly toneOf = toneOf;
  protected readonly arrowOf = arrowOf;

  protected readonly stats = computed(() => {
    const bars = this.current().bars;
    const first = bars[0];
    const last = bars[bars.length - 1];
    if (!first || !last) return null;
    let peak = first.c;
    let dd = 0;
    let high = -Infinity;
    let low = Infinity;
    let volume = 0;
    for (const b of bars) {
      peak = Math.max(peak, b.c);
      dd = Math.min(dd, b.c / peak - 1);
      high = Math.max(high, b.h);
      low = Math.min(low, b.l);
      volume += b.v;
    }
    return {
      first,
      last,
      returnPct: (last.c / first.c - 1) * 100,
      high,
      low,
      maxDrawdownPct: dd * 100,
      avgVolume: volume / bars.length,
    };
  });
}
