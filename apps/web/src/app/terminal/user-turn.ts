import { Component, input } from '@angular/core';
import type { UserTurn } from '../core/state/conversation.model';
import { fmtClock } from '../core/util/format';

@Component({
  selector: 'cd-user-turn',
  template: `
    @let t = turn();
    <div class="turn mono">
      <span class="glyph" aria-hidden="true">❯</span>
      <span class="text"><span class="sr-only">You: </span>{{ t.command ?? t.content }}</span>
      <time class="time" [attr.datetime]="t.createdAt">{{ fmtClock(t.createdAt) }}</time>
    </div>
  `,
  styles: `
    .turn {
      display: flex;
      align-items: baseline;
      gap: 10px;
      padding: 4px 0;
      font-size: var(--term-size);
      line-height: var(--term-leading);
    }
    .glyph {
      color: var(--accent);
      font-weight: 700;
    }
    .text {
      flex: 1;
      min-width: 0;
      color: var(--fg-0);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .time {
      font-size: 11px;
      color: var(--fg-2);
    }
  `,
})
export class UserTurnView {
  readonly turn = input.required<UserTurn>();
  protected readonly fmtClock = fmtClock;
}
