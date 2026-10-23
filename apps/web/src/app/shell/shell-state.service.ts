import { Injectable, computed, inject, signal } from '@angular/core';
import { ConversationsStore } from '../core/state/conversations.store';
import { PreferencesStore } from '../core/state/preferences.store';

@Injectable({ providedIn: 'root' })
export class ShellStateService {
  private readonly store = inject(ConversationsStore);
  private readonly prefs = inject(PreferencesStore);

  readonly draft = signal<{ text: string; nonce: number } | null>(null);
  readonly pinnedSymbol = signal<string | null>(null);

  readonly lastToolSymbol = computed(() => {
    const turns = this.store.active()?.turns ?? [];
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn?.kind !== 'assistant') continue;
      for (let j = turn.segments.length - 1; j >= 0; j--) {
        const segment = turn.segments[j];
        if (
          segment?.type === 'tool' &&
          segment.status === 'ok' &&
          typeof segment.args['symbol'] === 'string'
        ) {
          return segment.args['symbol'];
        }
      }
    }
    return null;
  });

  readonly focusSymbol = computed(
    () => this.pinnedSymbol() ?? this.lastToolSymbol() ?? this.prefs.watchlist()[0] ?? null,
  );

  insert(text: string): void {
    this.draft.set({ text, nonce: Date.now() });
  }
}
