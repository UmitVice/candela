import { Component, computed, input } from '@angular/core';
import type { Quote } from '../../core/api/types';
import { arrowOf, fmtCompact, fmtPct, fmtPrice, toneOf } from '../../core/util/format';

function position(value: number, low: number, high: number): number {
  const span = high - low;
  return span > 0 ? Math.min(100, Math.max(0, ((value - low) / span) * 100)) : 50;
}

@Component({
  selector: 'cd-quote-card',
  template: `
    @let q = quote();
    <div class="headline">
      <span class="big">{{ q.symbol }}</span>
      <span class="big">{{ fmtPrice(q.close) }}</span>
      <span [class]="toneOf(q.change)"
        >{{ arrowOf(q.change) }} {{ q.change > 0 ? '+' : '' }}{{ fmtPrice(q.change) }} ({{
          fmtPct(q.changePct)
        }})</span
      >
      <span class="muted">{{ q.name }} · {{ q.exchange }}</span>
    </div>
    <div class="ranges">
      <div
        class="range-row"
        [attr.aria-label]="'Day range ' + fmtPrice(q.low) + ' to ' + fmtPrice(q.high)"
      >
        <span class="range-label">Day</span>
        <span class="range-lo">{{ fmtPrice(q.low) }}</span>
        <div class="track" aria-hidden="true">
          <div
            class="span"
            [style.left.%]="day().open"
            [style.width.%]="day().width"
            [class]="toneOf(q.close - q.open)"
          ></div>
          <div class="marker" [style.left.%]="day().close"></div>
        </div>
        <span class="range-hi">{{ fmtPrice(q.high) }}</span>
      </div>
      <div
        class="range-row"
        [attr.aria-label]="
          '52-week range ' + fmtPrice(q.fiftyTwoWeekLow) + ' to ' + fmtPrice(q.fiftyTwoWeekHigh)
        "
      >
        <span class="range-label">52W</span>
        <span class="range-lo">{{ fmtPrice(q.fiftyTwoWeekLow) }}</span>
        <div class="track" aria-hidden="true">
          <div class="marker" [style.left.%]="year()"></div>
        </div>
        <span class="range-hi">{{ fmtPrice(q.fiftyTwoWeekHigh) }}</span>
      </div>
      <div
        class="range-row"
        [attr.aria-label]="
          'Volume ' +
          fmtCompact(q.volume) +
          ', ' +
          volumeRatio().toFixed(2) +
          ' times the 30-day average'
        "
      >
        <span class="range-label">Vol</span>
        <span class="range-lo">{{ fmtCompact(q.volume) }}</span>
        <div class="track" aria-hidden="true">
          <div
            class="fill"
            [style.width.%]="volumeWidth()"
            [class.hot]="volumeRatio() >= 1.5"
          ></div>
          <div class="avg" style="left: 50%"></div>
        </div>
        <span class="range-hi">{{ volumeRatio().toFixed(2) }}× avg</span>
      </div>
    </div>
    <dl class="grid">
      <div>
        <dt>Open</dt>
        <dd>{{ fmtPrice(q.open) }}</dd>
      </div>
      <div>
        <dt>Prev close</dt>
        <dd>{{ fmtPrice(q.previousClose) }}</dd>
      </div>
      <div>
        <dt>Avg vol 30d</dt>
        <dd>{{ fmtCompact(q.avgVolume30d) }}</dd>
      </div>
      <div>
        <dt>From 52W high</dt>
        <dd [class]="toneOf(fromHigh())">{{ arrowOf(fromHigh()) }} {{ fmtPct(fromHigh()) }}</dd>
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
  protected readonly arrowOf = arrowOf;

  protected readonly day = computed(() => {
    const q = this.quote();
    const open = position(q.open, q.low, q.high);
    const close = position(q.close, q.low, q.high);
    return { open: Math.min(open, close), width: Math.abs(close - open), close };
  });
  protected readonly year = computed(() => {
    const q = this.quote();
    return position(q.close, q.fiftyTwoWeekLow, q.fiftyTwoWeekHigh);
  });
  protected readonly volumeRatio = computed(() => {
    const q = this.quote();
    return q.avgVolume30d > 0 ? q.volume / q.avgVolume30d : 0;
  });
  protected readonly volumeWidth = computed(() => Math.min(100, this.volumeRatio() * 50));
  protected readonly fromHigh = computed(() => {
    const q = this.quote();
    return q.fiftyTwoWeekHigh > 0 ? (q.close / q.fiftyTwoWeekHigh - 1) * 100 : undefined;
  });
}
