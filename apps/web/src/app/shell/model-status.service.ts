import { Injectable, computed, inject } from '@angular/core';
import type { ModelInfo } from '../core/api/types';
import { ChatService } from '../core/chat/chat.service';
import { GatewayService } from '../core/gateway/gateway.service';
import { ConversationsStore } from '../core/state/conversations.store';
import { PreferencesStore } from '../core/state/preferences.store';

@Injectable({ providedIn: 'root' })
export class ModelStatusService {
  private readonly gateway = inject(GatewayService);
  private readonly prefs = inject(PreferencesStore);
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
    const status = this.gateway.status();
    if (!status) return null;
    const pref = this.prefs.model();
    const tier = pref === 'auto' ? (status.route === 'fallback' ? 'lite' : 'pro') : pref;
    return (
      status.models.find((m) => m.tier === tier && m.available) ??
      status.models.find((m) => m.available) ??
      null
    );
  });

  readonly model = computed(() => this.lastModel() ?? this.expectedModel());

  readonly label = computed(() => {
    const m = this.model();
    if (!m) return 'connecting';
    return `${m.tier.toUpperCase()} · ${m.version}`;
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
