import type { ElementRef } from '@angular/core';
import { Component, inject, output, signal, viewChild } from '@angular/core';
import {
  LucideCheck,
  LucideFileDown,
  LucidePencil,
  LucidePlus,
  LucideTrash,
  LucideX,
} from '@lucide/angular';
import { ChatService } from '../core/chat/chat.service';
import type { Conversation } from '../core/state/conversation.model';
import { ConversationsStore } from '../core/state/conversations.store';
import { downloadMarkdown } from '../core/state/export';

function relative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.round(diff / 60000);
  if (min < 1) return 'now';
  if (min < 60) return `${min}m`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h`;
  const d = Math.round(h / 24);
  return d < 30
    ? `${d}d`
    : new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

@Component({
  selector: 'cd-conversation-list',
  imports: [LucideCheck, LucideFileDown, LucidePencil, LucidePlus, LucideTrash, LucideX],
  template: `
    <div class="head">
      <h2 class="label">Sessions</h2>
      <button type="button" class="new" (click)="create()" [disabled]="chat.busy()">
        <svg lucidePlus [size]="12"></svg>
        New
      </button>
    </div>
    <ul class="list" aria-label="Sessions">
      @for (c of store.sorted(); track c.id) {
        <li class="item" [class.active]="c.id === store.activeId()">
          @if (editing() === c.id) {
            <form class="rename" (submit)="commitRename($event, c)">
              <label class="sr-only" [for]="'rename-' + c.id">Session title</label>
              <input
                #renameInput
                [id]="'rename-' + c.id"
                [value]="c.title"
                maxlength="80"
                (keydown.escape)="editing.set(null)"
                (blur)="commitRename($event, c)"
              />
            </form>
          } @else if (confirming() === c.id) {
            <div class="confirm" role="group" [attr.aria-label]="'Delete ' + c.title + '?'">
              <span>Delete?</span>
              <button
                type="button"
                class="act danger"
                aria-label="Confirm delete"
                (click)="remove(c)"
              >
                <svg lucideCheck [size]="13"></svg>
              </button>
              <button
                type="button"
                class="act"
                aria-label="Cancel delete"
                (click)="confirming.set(null)"
              >
                <svg lucideX [size]="13"></svg>
              </button>
            </div>
          } @else {
            <button
              type="button"
              class="open"
              [attr.aria-current]="c.id === store.activeId() ? 'true' : null"
              (click)="open(c)"
              [disabled]="chat.busy() && c.id !== store.activeId()"
            >
              <span class="title">{{ c.title }}</span>
              <span class="time mono">{{ relative(c.updatedAt) }}</span>
            </button>
            <div class="actions">
              <button
                type="button"
                class="act"
                [attr.aria-label]="'Rename ' + c.title"
                (click)="startRename(c)"
              >
                <svg lucidePencil [size]="12"></svg>
              </button>
              <button
                type="button"
                class="act"
                [attr.aria-label]="'Export ' + c.title + ' as Markdown'"
                [disabled]="c.turns.length === 0"
                (click)="exportMd(c)"
              >
                <svg lucideFileDown [size]="12"></svg>
              </button>
              <button
                type="button"
                class="act"
                [attr.aria-label]="'Delete ' + c.title"
                [disabled]="chat.busy() && c.id === store.activeId()"
                (click)="confirming.set(c.id)"
              >
                <svg lucideTrash [size]="12"></svg>
              </button>
            </div>
          }
        </li>
      }
    </ul>
  `,
  styleUrl: './conversation-list.css',
})
export class ConversationList {
  protected readonly store = inject(ConversationsStore);
  protected readonly chat = inject(ChatService);
  readonly picked = output();

  protected readonly editing = signal<string | null>(null);
  protected readonly confirming = signal<string | null>(null);
  protected readonly relative = relative;
  private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');

  protected create(): void {
    this.store.newConversation();
    this.picked.emit();
  }

  protected open(c: Conversation): void {
    this.store.select(c.id);
    this.picked.emit();
  }

  protected startRename(c: Conversation): void {
    this.editing.set(c.id);
    queueMicrotask(() => {
      const el = this.renameInput()?.nativeElement;
      el?.focus();
      el?.select();
    });
  }

  protected commitRename(event: Event, c: Conversation): void {
    event.preventDefault();
    if (this.editing() !== c.id) return;
    const value = this.renameInput()?.nativeElement.value ?? '';
    this.store.rename(c.id, value);
    this.editing.set(null);
  }

  protected remove(c: Conversation): void {
    this.store.remove(c.id);
    this.confirming.set(null);
  }

  protected exportMd(c: Conversation): void {
    downloadMarkdown(c);
  }
}
