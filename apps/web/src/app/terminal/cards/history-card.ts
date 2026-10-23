import { Component, computed, input, signal } from '@angular/core';
import type { PriceHistory } from '../../core/api/types';
import { fmtCompact, fmtPct, fmtPrice, toneOf } from '../../core/util/format';
import { Sparkline } from './sparkline';

@Component({
  selector: 'cd-history-card',
  imports: [Sparkline],
  template: `
    @let s = stats();
    @if (s) {
      <div class="headline">
        <span class="big">{{ history().symbol }} · {{ history().range }}</span>
        <span [class]="toneOf(s.returnPct)">{{ fmtPct(s.returnPct) }}</span>
        <span class="muted"
          >{{ history().bars.length }} daily bars · {{ s.first.t }} → {{ s.last.t }}</span
        >
      </div>
      <cd-sparkline
        [values]="closes()"
        [label]="history().symbol + ' closes over ' + history().range"
      />
      <dl class="grid">
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
          <dd class="down">{{ fmtPct(s.maxDrawdownPct) }}</dd>
        </div>
        <div>
          <dt>Avg volume</dt>
          <dd>{{ fmtCompact(s.avgVolume) }}</dd>
        </div>
      </dl>
      <button
        type="button"
        class="toggle"
        (click)="showBars.set(!showBars())"
        [attr.aria-expanded]="showBars()"
      >
        {{ showBars() ? '▾' : '▸' }} last 10 bars
      </button>
      @if (showBars()) {
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Open</th>
                <th>High</th>
                <th>Low</th>
                <th>Close</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              @for (b of recent(); track b.t) {
                <tr>
                  <td>{{ b.t }}</td>
                  <td>{{ fmtPrice(b.o) }}</td>
                  <td>{{ fmtPrice(b.h) }}</td>
                  <td>{{ fmtPrice(b.l) }}</td>
                  <td>{{ fmtPrice(b.c) }}</td>
                  <td>{{ fmtCompact(b.v) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
      <div class="note">
        {{ history().source }} · as of {{ history().asOf }} · interactive candlesticks arrive in the
        next release
      </div>
    }
  `,
  styleUrl: './cards.css',
  styles: `
    .toggle {
      margin: 10px 0 6px;
      padding: 0;
      border: 0;
      background: none;
      color: var(--fg-1);
      font: inherit;
    }
    .toggle:hover {
      color: var(--fg-0);
    }
  `,
})
export class HistoryCard {
  readonly history = input.required<PriceHistory>();
  protected readonly showBars = signal(false);
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly toneOf = toneOf;

  protected readonly closes = computed(() => this.history().bars.map((b) => b.c));
  protected readonly recent = computed(() => this.history().bars.slice(-10).reverse());
  protected readonly stats = computed(() => {
    const bars = this.history().bars;
    const first = bars[0];
    const last = bars[bars.length - 1];
    if (!first || !last) return null;
    let peak = first.c;
    let dd = 0;
    for (const b of bars) {
      peak = Math.max(peak, b.c);
      dd = Math.min(dd, b.c / peak - 1);
    }
    return {
      first,
      last,
      returnPct: (last.c / first.c - 1) * 100,
      high: Math.max(...bars.map((b) => b.h)),
      low: Math.min(...bars.map((b) => b.l)),
      maxDrawdownPct: dd * 100,
      avgVolume: bars.reduce((s, b) => s + b.v, 0) / bars.length,
    };
  });
}
