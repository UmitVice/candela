import { Component, computed, input, linkedSignal } from '@angular/core';
import type { ToolSegment } from '../core/state/conversation.model';
import { fmtDuration } from '../core/util/format';
import { ResultCard } from './cards/result-card';

// Approximate rendered card heights so lazily loaded cards do not shift the scrollback.
const PLACEHOLDER_HEIGHTS: Record<string, number> = {
  quote: 252,
  price_history: 470,
  indicators: 860,
  fundamentals: 420,
  forecast: 560,
  symbols: 110,
};

@Component({
  selector: 'cd-tool-line',
  imports: [ResultCard],
  template: `
    @let s = segment();
    <button
      type="button"
      class="line mono"
      [class.running]="s.status === 'running'"
      [class.failed]="s.status === 'error'"
      [attr.aria-expanded]="expandable() ? open() : null"
      [disabled]="!expandable()"
      (click)="open.set(!open())"
    >
      <span class="gear" aria-hidden="true">⚙</span>
      <span class="name">{{ s.name }}</span>
      @if (args()) {
        <span class="args">{{ args() }}</span>
      }
      <span class="result">
        @switch (s.status) {
          @case ('running') {
            <span class="spin" aria-hidden="true"></span><span class="sr-only">running</span>
          }
          @case ('ok') {
            <span class="ok">✓</span> {{ s.summary }}
          }
          @default {
            <span class="bad">✗</span> {{ s.summary ?? 'failed' }}
          }
        }
        @if (s.durationMs !== undefined) {
          <span class="dur">· {{ fmtDuration(s.durationMs) }}</span>
        }
      </span>
      @if (expandable()) {
        <span class="caret" aria-hidden="true">{{ open() ? '▾' : '▸' }}</span>
      }
    </button>
    @if (open() && expandable()) {
      @defer (on viewport) {
        <cd-result-card [segment]="s" />
      } @placeholder {
        <div class="placeholder" [style.height.px]="placeholderHeight()" aria-hidden="true"></div>
      }
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .placeholder {
      margin: 4px 0 8px 18px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--bg-1);
    }
    .line {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      column-gap: 8px;
      width: 100%;
      padding: 2px 0;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--tool);
      font-size: var(--term-size);
      line-height: var(--term-leading);
      text-align: left;
    }
    .line:not(:disabled):hover {
      background: rgb(45 212 191 / 0.06);
    }
    .line:disabled {
      cursor: default;
    }
    .gear {
      width: 14px;
    }
    .name {
      font-weight: 500;
    }
    .args {
      color: var(--fg-1);
    }
    .result {
      color: var(--fg-1);
    }
    .ok {
      color: var(--up);
    }
    .bad,
    .failed .result {
      color: var(--down);
    }
    .dur {
      color: var(--fg-2);
    }
    .caret {
      color: var(--fg-2);
    }
    .spin {
      display: inline-block;
      width: 10px;
      height: 10px;
      border: 1.5px solid var(--tool);
      border-right-color: transparent;
      border-radius: 50%;
      vertical-align: -1px;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
    @media (max-width: 767.98px) {
      .line {
        min-height: 36px;
        align-content: center;
      }
    }
  `,
})
export class ToolLine {
  readonly segment = input.required<ToolSegment>();
  protected readonly open = linkedSignal(() => this.expandable() && !!this.segment().data);
  protected readonly fmtDuration = fmtDuration;
  protected readonly expandable = computed(() => {
    const s = this.segment();
    return s.status !== 'running' && (!!s.data || !!s.error);
  });
  protected readonly placeholderHeight = computed(
    () => PLACEHOLDER_HEIGHTS[this.segment().data?.kind ?? ''] ?? 120,
  );
  protected readonly args = computed(() =>
    Object.entries(this.segment().args)
      .filter(([key]) => key !== 'limit')
      .map(([, value]) => (typeof value === 'string' ? value : JSON.stringify(value)))
      .join(' · '),
  );
}
