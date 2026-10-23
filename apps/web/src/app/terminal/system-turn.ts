import { Component, input } from '@angular/core';
import type { SystemTurn } from '../core/state/conversation.model';
import { MarkdownView } from './markdown-view';

@Component({
  selector: 'cd-system-turn',
  imports: [MarkdownView],
  template: `
    <div
      class="sys"
      [attr.data-variant]="turn().variant"
      [attr.role]="turn().variant === 'warn' ? 'alert' : null"
    >
      <cd-markdown [source]="turn().content" />
    </div>
  `,
  styles: `
    .sys {
      margin: 4px 0;
      padding: 8px 12px;
      border-left: 2px solid var(--info);
      border-radius: 0 6px 6px 0;
      background: var(--bg-1);
    }
    .sys[data-variant='warn'] {
      border-left-color: var(--warn);
    }
    .sys[data-variant='about'] {
      border-left-color: var(--accent);
    }
  `,
})
export class SystemTurnView {
  readonly turn = input.required<SystemTurn>();
}
