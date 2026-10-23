import { Component, computed, input, signal } from '@angular/core';
import type { ToolSegment } from '../../core/state/conversation.model';
import { ForecastCard } from './forecast-card';
import { FundamentalsCard } from './fundamentals-card';
import { HistoryCard } from './history-card';
import { IndicatorsCard } from './indicators-card';
import { QuoteCard } from './quote-card';
import { SymbolsCard } from './symbols-card';

@Component({
  selector: 'cd-result-card',
  imports: [QuoteCard, HistoryCard, IndicatorsCard, FundamentalsCard, ForecastCard, SymbolsCard],
  template: `
    @let seg = segment();
    <div class="card">
      <div class="card-head">
        <span class="kind">{{
          seg.data?.kind ?? (seg.status === 'error' ? 'error' : 'result')
        }}</span>
        <button type="button" class="raw" [attr.aria-pressed]="raw()" (click)="raw.set(!raw())">
          {{ '{ }' }} JSON
        </button>
      </div>
      @if (raw()) {
        <pre class="json">{{ json() }}</pre>
      } @else {
        @switch (seg.data?.kind) {
          @case ('quote') {
            <cd-quote-card [quote]="seg.data.quote" />
          }
          @case ('price_history') {
            <cd-history-card [history]="seg.data.history" />
          }
          @case ('indicators') {
            <cd-indicators-card [indicators]="seg.data.indicators" [history]="seg.data.history" />
          }
          @case ('fundamentals') {
            <cd-fundamentals-card [fundamentals]="seg.data.fundamentals" />
          }
          @case ('forecast') {
            <cd-forecast-card [forecast]="seg.data.forecast" />
          }
          @case ('symbols') {
            <cd-symbols-card [results]="seg.data.results" />
          }
          @default {
            @if (seg.error) {
              <div class="err mono">✗ {{ seg.summary }} — {{ seg.error }}</div>
            } @else {
              <pre class="json">{{ json() }}</pre>
            }
          }
        }
      }
    </div>
  `,
  styles: `
    .card {
      margin: 4px 0 8px 18px;
      padding: 10px 12px 12px;
      border: 1px solid var(--line);
      border-left: 2px solid rgb(45 212 191 / 0.5);
      border-radius: 6px;
      background: var(--bg-1);
      animation: open var(--dur) var(--ease-out);
    }
    .card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }
    .kind {
      font-family: var(--font-sans);
      font-size: 10.5px;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--tool);
    }
    .raw {
      padding: 2px 6px;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      background: transparent;
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: 10.5px;
    }
    .raw[aria-pressed='true'],
    .raw:hover {
      color: var(--fg-0);
    }
    .json {
      max-height: 320px;
      margin: 0;
      overflow: auto;
      font-family: var(--font-mono);
      font-size: 11.5px;
      line-height: 1.5;
      color: var(--fg-1);
      white-space: pre;
    }
    .err {
      font-size: 12px;
      color: var(--down);
    }
    @keyframes open {
      from {
        opacity: 0;
        transform: translateY(-4px);
      }
    }
    @media (max-width: 767.98px) {
      .card {
        margin-left: 0;
      }
    }
  `,
})
export class ResultCard {
  readonly segment = input.required<ToolSegment>();
  protected readonly raw = signal(false);
  protected readonly json = computed(() => {
    const s = this.segment();
    return JSON.stringify(s.data ?? { error: s.error, summary: s.summary }, null, 2);
  });
}
