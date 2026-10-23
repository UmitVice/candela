import { Injectable, computed, inject } from '@angular/core';
import type { ModelInfo } from '../core/api/types';
import { ChatService } from '../core/chat/chat.service';
import { GatewayService } from '../core/gateway/gateway.service';
import { ConversationsStore } from '../core/state/conversations.store';

@Injectable({ providedIn: 'root' })
export class ModelStatusService {
  private readonly gateway = inject(GatewayService);
  private readonly store = inject(ConversationsStore);
  private readonly chat = inject(ChatService);

  readonly lastModel = computed<ModelInfo | null>(() => {
    const turns = this.store.active()?.turns ?? [];
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn?.kind === 'assistant' && turn.model) return turn.model;
    }
    return null;
  });

  readonly expectedModel = computed<ModelInfo | null>(() => {
    const models = this.gateway.status()?.models ?? [];
    return (
      models.find((m) => m.tier === 'pro' && m.available) ?? models.find((m) => m.available) ?? null
    );
  });

  readonly model = computed(() => this.lastModel() ?? this.expectedModel());

  readonly state = computed<'connecting' | 'live' | 'busy' | 'replay' | 'offline'>(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting';
    if (c.mode === 'replay') return c.state === 'offline' ? 'offline' : 'replay';
    const status = this.gateway.status();
    const idle = status?.workers.some((w) => w.state === 'idle') ?? false;
    return !status || status.route === 'unavailable' || (status.workers.length > 0 && !idle)
      ? 'busy'
      : 'live';
  });

  readonly detail = computed(() => {
    const m = this.model();
    if (!m) return 'model unknown';
    return `PRO · ${m.displayName} ${m.version} · ${m.host === 'local-gpu-worker' ? 'GPU' : 'CPU'}`;
  });

  readonly label = computed(() => {
    switch (this.state()) {
      case 'connecting':
        return 'CONNECTING';
      case 'busy':
        return 'BUSY';
      case 'replay':
        return 'REPLAY';
      case 'offline':
        return 'OFFLINE';
      case 'live':
        return this.detail();
    }
  });

  readonly tokensPerSecond = computed(() => {
    const live = this.chat.lastUsage()?.tokensPerSecond;
    if (live) return live;
    const turns = this.store.active()?.turns ?? [];
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn?.kind === 'assistant' && turn.usage) return turn.usage.tokensPerSecond;
    }
    return null;
  });
}
