import { computed, inject } from '@angular/core';
import {
  patchState,
  signalStore,
  withComputed,
  withHooks,
  withMethods,
  withState,
} from '@ngrx/signals';
import { uuid } from '../util/ids';
import type { AssistantTurn, Conversation, Turn } from './conversation.model';
import { titleFrom } from './conversation.model';
import { ConversationRepository } from './conversation.repository';

interface ConversationsState {
  conversations: Conversation[];
  activeId: string | null;
  loaded: boolean;
}

const ACTIVE_KEY = 'candela.activeConversation';
const SAVE_DEBOUNCE_MS = 400;

// A reload mid-stream leaves turns that will never receive their terminal event.
function settleInterrupted(conversation: Conversation): Conversation {
  if (
    !conversation.turns.some(
      (t) => t.kind === 'assistant' && ['pending', 'queued', 'streaming'].includes(t.status),
    )
  ) {
    return conversation;
  }
  return {
    ...conversation,
    turns: conversation.turns.map((t) =>
      t.kind === 'assistant' && ['pending', 'queued', 'streaming'].includes(t.status)
        ? {
            ...t,
            status: 'cancelled',
            finishReason: 'cancelled',
            segments: t.segments.map((s) =>
              s.type === 'reasoning' && s.endedAt === undefined
                ? { ...s, endedAt: s.startedAt }
                : s.type === 'tool' && s.status === 'running'
                  ? { ...s, status: 'error', summary: 'interrupted' }
                  : s,
            ),
          }
        : t,
    ),
  };
}

function blank(): Conversation {
  const now = new Date().toISOString();
  return { id: uuid(), title: 'New session', createdAt: now, updatedAt: now, turns: [] };
}

export const ConversationsStore = signalStore(
  { providedIn: 'root' },
  withState<ConversationsState>({ conversations: [], activeId: null, loaded: false }),
  withComputed(({ conversations, activeId }) => ({
    active: computed(() => conversations().find((c) => c.id === activeId()) ?? null),
    sorted: computed(() =>
      [...conversations()]
        .filter((c) => c.turns.length > 0 || c.id === activeId())
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    ),
  })),
  withMethods((store) => {
    const repo = inject(ConversationRepository);
    const dirty = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const flush = () => {
      timer = undefined;
      for (const id of dirty) {
        const conversation = store.conversations().find((c) => c.id === id);
        if (conversation && conversation.turns.length > 0) void repo.save(conversation);
      }
      dirty.clear();
    };
    const markDirty = (id: string, immediate = false) => {
      dirty.add(id);
      if (immediate) {
        clearTimeout(timer);
        flush();
      } else {
        timer ??= setTimeout(flush, SAVE_DEBOUNCE_MS);
      }
    };
    const update = (id: string, fn: (c: Conversation) => Conversation, immediate = false) => {
      patchState(store, (state) => ({
        conversations: state.conversations.map((c) => (c.id === id ? fn(c) : c)),
      }));
      markDirty(id, immediate);
    };
    const setActive = (id: string | null) => {
      patchState(store, { activeId: id });
      try {
        if (id) localStorage.setItem(ACTIVE_KEY, id);
        else localStorage.removeItem(ACTIVE_KEY);
      } catch {
        /* storage may be unavailable in private browsing */
      }
    };

    return {
      async load(): Promise<void> {
        const stored = (await repo.loadAll()).map(settleInterrupted);
        let storedActiveId: string | null = null;
        try {
          storedActiveId = localStorage.getItem(ACTIVE_KEY);
        } catch {
          storedActiveId = null;
        }
        const early = store.conversations().filter((c) => !stored.some((s) => s.id === c.id));
        const merged = [...early, ...stored];
        const active =
          merged.find((c) => c.id === store.activeId()) ??
          merged.find((c) => c.id === storedActiveId) ??
          merged[0];
        const list = active ? merged : [blank(), ...merged];
        patchState(store, { conversations: list, loaded: true });
        setActive(active?.id ?? list[0]?.id ?? null);
      },

      ensureActive(): string {
        const current = store.active();
        if (current) return current.id;
        const conversation = blank();
        patchState(store, (s) => ({ conversations: [conversation, ...s.conversations] }));
        setActive(conversation.id);
        return conversation.id;
      },

      newConversation(): string {
        const current = store.active();
        if (current?.turns.length === 0) return current.id;
        const conversation = blank();
        patchState(store, (s) => ({ conversations: [conversation, ...s.conversations] }));
        setActive(conversation.id);
        return conversation.id;
      },

      select(id: string): void {
        if (store.conversations().some((c) => c.id === id)) setActive(id);
      },

      rename(id: string, title: string): void {
        const clean = title.replace(/\s+/g, ' ').trim().slice(0, 80);
        if (!clean) return;
        update(id, (c) => ({ ...c, title: clean }), true);
      },

      remove(id: string): void {
        const remaining = store.conversations().filter((c) => c.id !== id);
        patchState(store, { conversations: remaining });
        dirty.delete(id);
        void repo.remove(id);
        if (store.activeId() === id) {
          const next = [...remaining].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0];
          if (next) setActive(next.id);
          else {
            const conversation = blank();
            patchState(store, { conversations: [conversation] });
            setActive(conversation.id);
          }
        }
      },

      clear(id: string): void {
        update(id, (c) => ({ ...c, turns: [], updatedAt: new Date().toISOString() }), true);
      },

      addTurn(id: string, turn: Turn): void {
        update(id, (c) => ({
          ...c,
          title:
            c.turns.length === 0 && turn.kind === 'user'
              ? titleFrom(turn.command?.replace(/^\//, '') ?? turn.content)
              : c.title,
          updatedAt: new Date().toISOString(),
          turns: [...c.turns, turn],
        }));
      },

      removeTurnsFrom(id: string, turnId: string): void {
        update(id, (c) => {
          const index = c.turns.findIndex((t) => t.id === turnId);
          return index === -1 ? c : { ...c, turns: c.turns.slice(0, index) };
        });
      },

      updateAssistant(
        id: string,
        turnId: string,
        fn: (turn: AssistantTurn) => AssistantTurn,
        immediate = false,
      ): void {
        update(
          id,
          (c) => ({
            ...c,
            turns: c.turns.map((t) => (t.id === turnId && t.kind === 'assistant' ? fn(t) : t)),
          }),
          immediate,
        );
      },

      touch(id: string): void {
        update(id, (c) => ({ ...c, updatedAt: new Date().toISOString() }), true);
      },
    };
  }),
  withHooks({
    onInit(store) {
      void store.load();
    },
  }),
);
