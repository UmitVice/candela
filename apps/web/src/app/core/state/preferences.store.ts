import { Injectable, effect, signal } from '@angular/core';
import type { ModelPreference } from '../api/types';

const KEY = 'candela.preferences';
const HISTORY_KEY = 'candela.promptHistory';
const MAX_HISTORY = 100;
const DEFAULT_WATCHLIST = ['NVDA', 'AAPL', 'MSFT', 'AMD', 'TSLA', 'GOOGL'];

interface StoredPreferences {
  model: ModelPreference;
  reasoning: boolean;
  railCollapsed: boolean;
  contextOpen: boolean;
  watchlist: string[];
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...(JSON.parse(raw) as object) } : fallback;
  } catch {
    return fallback;
  }
}

function readList(key: string): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) ?? '[]') as unknown;
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage may be full or disabled */
  }
}

@Injectable({ providedIn: 'root' })
export class PreferencesStore {
  private readonly initial = read<StoredPreferences>(KEY, {
    model: 'auto',
    reasoning: true,
    railCollapsed: false,
    contextOpen: true,
    watchlist: DEFAULT_WATCHLIST,
  });

  readonly model = signal<ModelPreference>(
    ['auto', 'pro', 'lite'].includes(this.initial.model) ? this.initial.model : 'auto',
  );
  readonly reasoning = signal(this.initial.reasoning !== false);
  readonly railCollapsed = signal(!!this.initial.railCollapsed);
  readonly contextOpen = signal(this.initial.contextOpen !== false);
  readonly watchlist = signal<string[]>(
    Array.isArray(this.initial.watchlist) ? this.initial.watchlist.slice(0, 30) : DEFAULT_WATCHLIST,
  );
  readonly promptHistory = signal<string[]>(readList(HISTORY_KEY));

  constructor() {
    effect(() =>
      write(KEY, {
        model: this.model(),
        reasoning: this.reasoning(),
        railCollapsed: this.railCollapsed(),
        contextOpen: this.contextOpen(),
        watchlist: this.watchlist(),
      } satisfies StoredPreferences),
    );
    effect(() => write(HISTORY_KEY, this.promptHistory()));
  }

  watch(symbol: string): boolean {
    const s = symbol.toUpperCase();
    if (this.watchlist().includes(s)) return false;
    this.watchlist.update((list) => [...list, s].slice(-30));
    return true;
  }

  unwatch(symbol: string): boolean {
    const s = symbol.toUpperCase();
    if (!this.watchlist().includes(s)) return false;
    this.watchlist.update((list) => list.filter((x) => x !== s));
    return true;
  }

  remember(prompt: string): void {
    const clean = prompt.trim();
    if (!clean) return;
    this.promptHistory.update((list) =>
      [...list.filter((p) => p !== clean), clean].slice(-MAX_HISTORY),
    );
  }
}
