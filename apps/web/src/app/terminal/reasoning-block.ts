import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import type { ReasoningSegment } from '../core/state/conversation.model';

@Component({
  selector: 'cd-reasoning-block',
  template: `
    <button
      type="button"
      class="head mono"
      [attr.aria-expanded]="expanded()"
      (click)="override.set(!expanded())"
    >
      <span aria-hidden="true">{{ expanded() ? '▾' : '▸' }}</span>
      thinking · {{ seconds() }} s
      @if (live()) {
        <span class="pulse" aria-hidden="true">●</span>
      }
    </button>
    @if (expanded()) {
      <div class="body mono">
        <span class="txt">{{ segment().text.trim() }}</span>
        @if (live()) {
          <span class="cursor" aria-hidden="true">▋</span>
        }
      </div>
    }
  `,
  styles: `
    :host {
      display: block;
      margin: 2px 0;
    }
    .head {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 0;
      border: 0;
      background: transparent;
      color: var(--reason);
      font-size: var(--term-size);
      line-height: var(--term-leading);
    }
    .head:hover {
      color: #c4b5fd;
    }
    .pulse {
      font-size: 8px;
      animation: pulse 1s ease-in-out infinite;
    }
    .body {
      margin: 2px 0 6px;
      padding: 2px 0 2px 12px;
      border-left: 1px solid rgb(167 139 250 / 0.35);
      color: #a99bd6;
      font-size: calc(var(--term-size) - 0.5px);
      line-height: var(--term-leading);
      overflow-wrap: anywhere;
    }
    .txt {
      white-space: pre-wrap;
    }
    .cursor {
      margin-left: 1px;
      color: var(--reason);
      animation: blink 1s steps(1) infinite;
    }
    @keyframes blink {
      50% {
        opacity: 0;
      }
    }
    @keyframes pulse {
      50% {
        opacity: 0.25;
      }
    }
  `,
})
export class ReasoningBlock {
  readonly segment = input.required<ReasoningSegment>();
  readonly answerStarted = input(false);
  protected readonly override = signal<boolean | null>(null);
  private readonly now = signal(Date.now());

  protected readonly live = computed(
    () => this.segment().endedAt === undefined && !this.answerStarted(),
  );
  protected readonly expanded = computed(() => this.override() ?? this.live());
  protected readonly seconds = computed(() => {
    const s = this.segment();
    const end = s.endedAt ?? this.now();
    return Math.max(0, (end - s.startedAt) / 1000).toFixed(1);
  });

  constructor() {
    let timer: ReturnType<typeof setInterval> | undefined;
    effect(() => {
      clearInterval(timer);
      if (this.segment().endedAt === undefined)
        timer = setInterval(() => this.now.set(Date.now()), 100);
    });
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
}
