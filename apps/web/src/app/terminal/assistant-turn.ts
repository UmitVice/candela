import { Clipboard } from '@angular/cdk/clipboard';
import { Component, computed, inject, input, output, signal } from '@angular/core';
import {
  LucideCheck,
  LucideCopy,
  LucideRotateCcw,
  LucideThumbsDown,
  LucideThumbsUp,
} from '@lucide/angular';
import type {
  AssistantTurn,
  ReasoningSegment,
  ToolSegment,
} from '../core/state/conversation.model';
import { answerText } from '../core/state/conversation.model';
import { fmtClock } from '../core/util/format';
import { ErrorBlock } from './error-block';
import { MarkdownView } from './markdown-view';
import { ReasoningBlock } from './reasoning-block';
import { ToolLine } from './tool-line';

@Component({
  selector: 'cd-assistant-turn',
  imports: [
    ReasoningBlock,
    ToolLine,
    MarkdownView,
    ErrorBlock,
    LucideCopy,
    LucideCheck,
    LucideThumbsUp,
    LucideThumbsDown,
    LucideRotateCcw,
  ],
  templateUrl: './assistant-turn.html',
  styleUrl: './assistant-turn.css',
})
export class AssistantTurnView {
  private readonly clipboard = inject(Clipboard);
  readonly turn = input.required<AssistantTurn>();
  readonly isLast = input(false);
  readonly busy = input(false);
  readonly rate = output<1 | -1>();
  readonly regenerate = output();
  readonly feedback = output<{
    reason: string;
    consentToStore: boolean;
    done: (ok: boolean) => void;
  }>();

  protected readonly reason = signal('');
  protected readonly consent = signal(false);
  protected readonly sending = signal(false);
  protected readonly feedbackDismissed = signal(false);
  protected readonly feedbackError = signal('');

  protected readonly copied = signal(false);
  protected readonly fmtClock = fmtClock;

  protected readonly streaming = computed(() => {
    const s = this.turn().status;
    return s === 'pending' || s === 'queued' || s === 'streaming';
  });
  protected readonly answerStarted = computed(() =>
    this.turn().segments.some((s) => s.type === 'answer'),
  );
  protected readonly lastAnswerIndex = computed(() => {
    const segs = this.turn().segments;
    for (let i = segs.length - 1; i >= 0; i--) if (segs[i]?.type === 'answer') return i;
    return -1;
  });
  protected readonly header = computed(() => {
    const m = this.turn().model;
    return m ? `${m.version} · ${m.tier.toUpperCase()}` : '';
  });
  protected readonly hasAnswer = computed(() => answerText(this.turn()).trim().length > 0);

  protected asReasoning(segment: unknown): ReasoningSegment {
    return segment as ReasoningSegment;
  }

  protected asTool(segment: unknown): ToolSegment {
    return segment as ToolSegment;
  }

  protected reasoningAnswerStarted(index: number): boolean {
    return this.turn()
      .segments.slice(index + 1)
      .some((s) => s.type === 'answer' || s.type === 'tool');
  }

  protected sendFeedback(event: Event): void {
    event.preventDefault();
    if (this.sending()) return;
    this.sending.set(true);
    this.feedbackError.set('');
    this.feedback.emit({
      reason: this.reason(),
      consentToStore: this.consent(),
      done: (ok) => {
        this.sending.set(false);
        if (!ok) this.feedbackError.set('Could not send feedback. Try again later.');
      },
    });
  }

  protected copy(): void {
    if (this.clipboard.copy(answerText(this.turn()).trim())) {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    }
  }
}
