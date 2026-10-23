import { Component, input } from '@angular/core';
import type { Quote } from '../../core/api/types';
import { fmtCompact, fmtPct, fmtPrice, toneOf } from '../../core/util/format';

@Component({
  selector: 'cd-quote-card',
  template: `
    @let q = quote();
    <div class="headline">
      <span class="big">{{ q.symbol }}</span>
      <span class="big">{{ fmtPrice(q.close) }}</span>
      <span [class]="toneOf(q.change)"
        >{{ q.change > 0 ? '+' : '' }}{{ fmtPrice(q.change) }} ({{ fmtPct(q.changePct) }})</span
      >
      <span class="muted">{{ q.name }} · {{ q.exchange }}</span>
    </div>
    <dl class="grid">
      <div>
        <dt>Open</dt>
        <dd>{{ fmtPrice(q.open) }}</dd>
      </div>
      <div>
        <dt>High / Low</dt>
        <dd>{{ fmtPrice(q.high) }} / {{ fmtPrice(q.low) }}</dd>
      </div>
      <div>
        <dt>Prev close</dt>
        <dd>{{ fmtPrice(q.previousClose) }}</dd>
      </div>
      <div>
        <dt>Volume</dt>
        <dd>{{ fmtCompact(q.volume) }}</dd>
      </div>
      <div>
        <dt>Avg vol 30d</dt>
        <dd>{{ fmtCompact(q.avgVolume30d) }}</dd>
      </div>
      <div>
        <dt>52W range</dt>
        <dd>{{ fmtPrice(q.fiftyTwoWeekLow) }}–{{ fmtPrice(q.fiftyTwoWeekHigh) }}</dd>
      </div>
    </dl>
    <div class="note">
      {{ q.source }}{{ q.delayed ? ' · delayed' : '' }} · as of {{ q.asOf }} · {{ q.currency }}
    </div>
  `,
  styleUrl: './cards.css',
})
export class QuoteCard {
  readonly quote = input.required<Quote>();
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly toneOf = toneOf;
}
