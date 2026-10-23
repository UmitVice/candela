import { LiveAnnouncer } from '@angular/cdk/a11y';
import { Injectable, computed, inject, signal } from '@angular/core';
import type { ChatMessage, ChatRequest, ChatStreamEvent } from '../api/types';
import { GatewayService } from '../gateway/gateway.service';
import { MarketService } from '../gateway/market.service';
import type { AssistantTurn, Conversation } from '../state/conversation.model';
import { answerText } from '../state/conversation.model';
import { ConversationsStore } from '../state/conversations.store';
import { PreferencesStore } from '../state/preferences.store';
import { uuid } from '../util/ids';
import { errorEvent } from './chat-transport';
import { applyStreamEvent } from './turn-reducer';

const MAX_MESSAGES = 40;
const MAX_CONTENT = 8000;

interface ActiveRun {
  conversationId: string;
  turnId: string;
  controller: AbortController;
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly store = inject(ConversationsStore);
  private readonly gateway = inject(GatewayService);
  private readonly market = inject(MarketService);
  private readonly prefs = inject(PreferencesStore);
  private readonly announcer = inject(LiveAnnouncer);
  private readonly run = signal<ActiveRun | null>(null);

  readonly busy = computed(() => this.run() !== null);
  readonly activeTurnId = computed(() => this.run()?.turnId ?? null);
  readonly lastUsage = signal<{ tokensPerSecond: number; modelId: string } | null>(null);

  async send(content: string, command?: string): Promise<void> {
    const text = content.trim().slice(0, MAX_CONTENT);
    if (!text || this.busy()) return;
    const conversationId = this.store.ensureActive();
    this.store.addTurn(conversationId, {
      kind: 'user',
      id: uuid(),
      content: text,
      ...(command ? { command } : {}),
      createdAt: new Date().toISOString(),
    });
    await this.respond(conversationId);
  }

  async regenerate(turnId: string): Promise<void> {
    const conversation = this.store.active();
    if (!conversation || this.busy()) return;
    this.store.removeTurnsFrom(conversation.id, turnId);
    await this.respond(conversation.id);
  }

  stop(): void {
    this.run()?.controller.abort();
  }

  rate(turnId: string, rating: 1 | -1): void {
    const conversation = this.store.active();
    if (!conversation) return;
    const turn = conversation.turns.find(
      (t): t is AssistantTurn => t.id === turnId && t.kind === 'assistant',
    );
    if (!turn) return;
    const next = turn.feedback === rating ? undefined : rating;
    this.store.updateAssistant(conversation.id, turnId, (t) => ({ ...t, feedback: next }), true);
    if (next && turn.messageId) {
      void this.market.feedback({
        conversationId: conversation.id,
        messageId: turn.messageId,
        rating: next,
        consentToStore: false,
      });
    }
  }

  private buildRequest(conversation: Conversation): ChatRequest {
    const messages: ChatMessage[] = [];
    for (const turn of conversation.turns) {
      if (turn.kind === 'user')
        messages.push({ role: 'user', content: turn.content.slice(0, MAX_CONTENT) });
      else if (turn.kind === 'assistant' && turn.status === 'done') {
        const content = answerText(turn).trim();
        if (content) messages.push({ role: 'assistant', content: content.slice(0, MAX_CONTENT) });
      }
    }
    let trimmed = messages.slice(-MAX_MESSAGES);
    while (trimmed[0] && trimmed[0].role !== 'user') trimmed = trimmed.slice(1);
    return {
      conversationId: conversation.id,
      messages: trimmed,
      model: this.prefs.model(),
      options: { reasoning: this.prefs.reasoning() },
    };
  }

  private async respond(conversationId: string): Promise<void> {
    await this.gateway.connect();
    const conversation = this.store.conversations().find((c) => c.id === conversationId);
    if (!conversation) return;
    const request = this.buildRequest(conversation);
    if (request.messages.at(-1)?.role !== 'user') return;

    const transport = this.gateway.transport();
    const turnId = uuid();
    const controller = new AbortController();
    this.store.addTurn(conversationId, {
      kind: 'assistant',
      id: turnId,
      createdAt: new Date().toISOString(),
      status: 'pending',
      transport: transport.kind,
      segments: [],
    });
    this.run.set({ conversationId, turnId, controller });

    const apply = (event: ChatStreamEvent) =>
      this.store.updateAssistant(conversationId, turnId, (t) => applyStreamEvent(t, event));

    let terminal: ChatStreamEvent | null = null;
    try {
      for await (const event of transport.stream(request, controller.signal)) {
        apply(event);
        if (event.event === 'usage' && event.data.tokensPerSecond > 0) {
          const model = this.store
            .conversations()
            .find((c) => c.id === conversationId)
            ?.turns.find((t) => t.id === turnId);
          this.lastUsage.set({
            tokensPerSecond: event.data.tokensPerSecond,
            modelId: model?.kind === 'assistant' ? (model.model?.id ?? '') : '',
          });
        }
        if (event.event === 'done' || event.event === 'error') {
          terminal = event;
          break;
        }
      }
    } catch {
      terminal = errorEvent('internal', 'The client failed while reading the stream.');
      apply(terminal);
    }
    if (!terminal) {
      terminal = controller.signal.aborted
        ? { event: 'done', data: { finishReason: 'cancelled' } }
        : errorEvent('upstream_unavailable', 'The stream ended before completion.');
      apply(terminal);
    }
    this.store.touch(conversationId);
    this.run.set(null);
    this.announce(conversationId, turnId);
  }

  private announce(conversationId: string, turnId: string): void {
    const turn = this.store
      .conversations()
      .find((c) => c.id === conversationId)
      ?.turns.find((t): t is AssistantTurn => t.id === turnId && t.kind === 'assistant');
    if (!turn) return;
    if (turn.status === 'error') {
      void this.announcer.announce(
        `Candela error: ${turn.error?.message ?? 'request failed'}`,
        'assertive',
      );
      return;
    }
    if (turn.status === 'cancelled') {
      void this.announcer.announce('Generation stopped.', 'polite');
      return;
    }
    const text = answerText(turn)
      .replace(/[*_`#>|]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    void this.announcer.announce(
      `Candela answered: ${text.slice(0, 220)}${text.length > 220 ? '…' : ''}`,
      'polite',
    );
  }
}
