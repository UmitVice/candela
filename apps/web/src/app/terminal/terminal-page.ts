import { CdkScrollable } from '@angular/cdk/scrolling';
import type { ElementRef } from '@angular/core';
import { Component, computed, effect, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { LucideArrowUp } from '@lucide/angular';
import { ChatService } from '../core/chat/chat.service';
import { CommandService } from '../core/commands/commands';
import { GatewayService } from '../core/gateway/gateway.service';
import { ConversationsStore } from '../core/state/conversations.store';
import { LayoutService } from '../shell/layout.service';
import { AssistantTurnView } from './assistant-turn';
import { BootSequence } from './boot-sequence';
import { PromptInput } from './prompt-input';
import { SystemTurnView } from './system-turn';
import { UserTurnView } from './user-turn';

const SUGGESTIONS = [
  { label: '/analyze NVDA', hint: 'single-stock read with tools' },
  { label: '/compare AAPL MSFT', hint: 'side-by-side metrics' },
  { label: 'how is nvidia doing?', hint: 'resolves a company name' },
  { label: '/forecast TSLA', hint: 'P10 / P50 / P90 bands' },
  { label: '/fundamentals AAPL', hint: 'SEC filings view' },
  { label: '/analyze ZZZZ', hint: 'missing data handling' },
];

@Component({
  selector: 'cd-terminal-page',
  imports: [
    CdkScrollable,
    BootSequence,
    UserTurnView,
    AssistantTurnView,
    SystemTurnView,
    PromptInput,
    LucideArrowUp,
  ],
  templateUrl: './terminal-page.html',
  styleUrl: './terminal-page.css',
})
export class TerminalPage {
  protected readonly store = inject(ConversationsStore);
  protected readonly chat = inject(ChatService);
  protected readonly gateway = inject(GatewayService);
  protected readonly layout = inject(LayoutService);
  private readonly commands = inject(CommandService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly scroller = viewChild.required(CdkScrollable);
  private readonly prompt = viewChild.required(PromptInput);
  private readonly scrollEl = viewChild.required<ElementRef<HTMLElement>>('scrollback');

  protected readonly suggestions = SUGGESTIONS;
  protected readonly booted = signal(false);
  protected readonly stick = signal(true);
  protected readonly turns = computed(() => this.store.active()?.turns ?? []);
  protected readonly lastAssistantId = computed(() => {
    const turns = this.turns();
    for (let i = turns.length - 1; i >= 0; i--) {
      const t = turns[i];
      if (t?.kind === 'assistant') return t.id;
    }
    return null;
  });

  constructor() {
    effect(() => {
      this.turns();
      this.store.activeId();
      if (this.stick()) requestAnimationFrame(() => this.scrollToBottom(false));
    });

    effect(() => {
      this.store.activeId();
      this.stick.set(true);
    });

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      if (params.get('new') === '1') {
        this.store.newConversation();
        void this.router.navigate([], { queryParams: {}, replaceUrl: true });
      }
    });
  }

  protected onScroll(): void {
    const distance = this.scroller().measureScrollOffset('bottom');
    this.stick.set(distance < 48);
  }

  protected scrollToBottom(smooth: boolean): void {
    const el = this.scrollEl().nativeElement;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth && !this.layout.reducedMotion ? 'smooth' : 'auto',
    });
  }

  protected jumpToLatest(): void {
    this.stick.set(true);
    this.scrollToBottom(true);
  }

  protected submit(text: string): void {
    this.stick.set(true);
    if (!this.commands.execute(text)) void this.chat.send(text);
  }

  protected suggest(text: string): void {
    this.submit(text);
    this.prompt().focus();
  }
}
