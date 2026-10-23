import { DialogRef } from '@angular/cdk/dialog';
import { Component, inject, input, output } from '@angular/core';
import {
  LucideMessageSquare,
  LucidePanelLeft,
  LucidePlus,
  LucideStar,
  LucideX,
} from '@lucide/angular';
import { ChatService } from '../core/chat/chat.service';
import { ConversationsStore } from '../core/state/conversations.store';
import { ConversationList } from './conversation-list';
import { Watchlist } from './watchlist';

@Component({
  selector: 'cd-left-rail',
  imports: [
    ConversationList,
    Watchlist,
    LucideMessageSquare,
    LucidePanelLeft,
    LucidePlus,
    LucideStar,
    LucideX,
  ],
  template: `
    @if (collapsed()) {
      <div class="icons">
        <button
          type="button"
          class="icon-btn"
          aria-label="New session"
          title="New session"
          [disabled]="chat.busy()"
          (click)="store.newConversation()"
        >
          <svg lucidePlus [size]="16"></svg>
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="Watchlist"
          title="Watchlist"
          (click)="expand.emit()"
        >
          <svg lucideStar [size]="16"></svg>
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="Sessions"
          title="Sessions"
          (click)="expand.emit()"
        >
          <svg lucideMessageSquare [size]="16"></svg>
        </button>
        <div class="grow"></div>
        @if (collapsible()) {
          <button
            type="button"
            class="icon-btn"
            aria-label="Expand sidebar"
            title="Expand sidebar"
            (click)="expand.emit()"
          >
            <svg lucidePanelLeft [size]="16"></svg>
          </button>
        }
      </div>
    } @else {
      @if (inSheet) {
        <div class="sheet-head">
          <span class="label">Navigate</span>
          <button type="button" class="icon-btn" aria-label="Close" (click)="close()">
            <svg lucideX [size]="16"></svg>
          </button>
        </div>
      }
      <div class="scroll panel-scroll">
        <cd-watchlist (picked)="close()" />
        <div class="sep"></div>
        <cd-conversation-list (picked)="close()" />
      </div>
      @if (collapsible()) {
        <div class="foot">
          <button
            type="button"
            class="icon-btn"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            (click)="collapse.emit()"
          >
            <svg lucidePanelLeft [size]="16"></svg>
          </button>
        </div>
      }
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      background: var(--bg-1);
    }
    .icons {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      height: 100%;
      padding: 8px 0;
    }
    .grow {
      flex: 1;
    }
    .scroll {
      flex: 1;
      min-height: 0;
    }
    .sep {
      height: 1px;
      margin: 8px 12px;
      background: var(--line);
    }
    .foot {
      display: flex;
      justify-content: flex-end;
      padding: 4px 8px;
      border-top: 1px solid var(--line);
    }
    .sheet-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 8px 0 12px;
    }
  `,
})
export class LeftRail {
  protected readonly store = inject(ConversationsStore);
  protected readonly chat = inject(ChatService);
  private readonly dialogRef = inject(DialogRef, { optional: true });
  protected readonly inSheet = !!this.dialogRef;

  readonly collapsed = input(false);
  readonly collapsible = input(false);
  readonly expand = output();
  readonly collapse = output();

  protected close(): void {
    this.dialogRef?.close();
  }
}
