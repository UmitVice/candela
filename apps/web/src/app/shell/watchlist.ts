import type { ElementRef } from '@angular/core';
import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  output,
  signal,
  untracked,
  viewChildren,
} from '@angular/core';
import { LucidePlus, LucideX } from '@lucide/angular';
import type { Quote } from '../core/api/types';
import { GatewayService } from '../core/gateway/gateway.service';
import { MarketService } from '../core/gateway/market.service';
import { PreferencesStore } from '../core/state/preferences.store';
import { arrowOf, fmtPct, fmtPrice, toneOf } from '../core/util/format';
import { CanvasSpark } from '../ui/canvas-spark';
import { ShellStateService } from './shell-state.service';

const REFRESH_MS = 300_000;
const BACKOFF_START_MS = 15_000;
const BACKOFF_MAX_MS = 600_000;

@Component({
  selector: 'cd-watchlist',
  imports: [LucidePlus, LucideX, CanvasSpark],
  template: `
    <div class="head">
      <h2 class="label" id="watchlist-label">Watchlist</h2>
      <span class="count mono">{{ prefs.watchlist().length }}</span>
    </div>
    <ul class="rows" aria-labelledby="watchlist-label" aria-describedby="watchlist-keys">
      @for (symbol of prefs.watchlist(); track symbol; let i = $index) {
        @let q = quotes().get(symbol);
        <li class="row" [class.focused]="shell.focusSymbol() === symbol">
          <button
            #rowButton
            type="button"
            class="row-main"
            [tabindex]="i === active() ? 0 : -1"
            (click)="pick(symbol)"
            (focus)="active.set(i)"
            (keydown)="onKeydown($event)"
            aria-keyshortcuts="Delete"
            [attr.aria-label]="
              symbol +
              (q
                ? ', ' +
                  fmtPrice(q.close) +
                  ', ' +
                  (q.changePct >= 0 ? 'up ' : 'down ') +
                  fmtPct(q.changePct)
                : '') +
              '. Prefill analyze'
            "
          >
            <span class="sym mono">{{ symbol }}</span>
            <span class="spark">
              @if (closes().get(symbol); as values) {
                <cd-canvas-spark [values]="values" />
              }
            </span>
            <span class="name">{{ q?.name ?? '' }}</span>
            <span class="px mono">{{ q ? fmtPrice(q.close) : loading() ? '…' : '—' }}</span>
            <span class="chg mono" [class]="toneOf(q?.changePct)">{{
              q ? arrowOf(q.changePct) + ' ' + fmtPct(q.changePct) : ''
            }}</span>
          </button>
          <button
            type="button"
            class="remove"
            tabindex="-1"
            [attr.aria-label]="'Remove ' + symbol + ' from watchlist'"
            (click)="remove(symbol)"
          >
            <svg lucideX [size]="12"></svg>
          </button>
        </li>
      } @empty {
        <li class="empty">Add a ticker below or type <code>/watch NVDA</code>.</li>
      }
    </ul>
    <p id="watchlist-keys" class="sr-only">
      Use arrow keys to move, Enter to prefill analyze, Delete to remove.
    </p>
    @if (stale()) {
      <p class="stale mono" role="status">quotes delayed · retrying</p>
    }
    <form class="add" (submit)="add($event)">
      <label class="sr-only" for="watch-add">Add ticker</label>
      <svg lucidePlus [size]="12" class="add-icon"></svg>
      <input
        id="watch-add"
        class="mono"
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        maxlength="10"
        placeholder="Add ticker"
        [value]="draft()"
        (input)="draft.set($any($event.target).value)"
      />
    </form>
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }
  `,
  styleUrl: './watchlist.css',
})
export class Watchlist {
  protected readonly prefs = inject(PreferencesStore);
  protected readonly shell = inject(ShellStateService);
  private readonly market = inject(MarketService);
  private readonly gateway = inject(GatewayService);
  private readonly rowButtons = viewChildren<ElementRef<HTMLButtonElement>>('rowButton');

  readonly picked = output<string>();

  protected readonly draft = signal('');
  protected readonly error = signal('');
  protected readonly active = signal(0);
  protected readonly quotes = signal(new Map<string, Quote | null>());
  protected readonly closes = signal(new Map<string, number[]>());
  protected readonly loading = signal(true);
  protected readonly stale = signal(false);
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly toneOf = toneOf;
  protected readonly arrowOf = arrowOf;

  private timer: ReturnType<typeof setTimeout> | undefined;
  private backoff = BACKOFF_START_MS;
  private generation = 0;

  constructor() {
    const source = computed(() => ({
      symbols: this.prefs.watchlist(),
      mode: this.gateway.connection().mode,
      baseUrl: this.gateway.connection().baseUrl,
    }));
    effect(() => {
      const { symbols } = source();
      untracked(() => {
        this.backoff = BACKOFF_START_MS;
        void this.refresh(symbols);
        void this.loadSparks(symbols);
      });
    });
    inject(DestroyRef).onDestroy(() => {
      this.generation++;
      clearTimeout(this.timer);
    });
  }

  // One batch per cycle; failed batches (throttling, gateway hiccups) retry with exponential
  // backoff while successful ones wait for the quote cache lifetime.
  private async refresh(symbols: readonly string[]): Promise<void> {
    clearTimeout(this.timer);
    const generation = ++this.generation;
    const { quotes, failed } = await this.market.quotes(symbols);
    if (generation !== this.generation) return;
    this.quotes.update((previous) => {
      const next = new Map(quotes);
      for (const [symbol, quote] of next) {
        if (!quote && failed && previous.get(symbol))
          next.set(symbol, previous.get(symbol) ?? null);
      }
      return next;
    });
    this.loading.set(false);
    this.stale.set(failed);
    const delay = failed ? this.backoff : REFRESH_MS;
    this.backoff = failed ? Math.min(this.backoff * 2, BACKOFF_MAX_MS) : BACKOFF_START_MS;
    this.timer = setTimeout(() => void this.refresh(this.prefs.watchlist()), delay);
  }

  private async loadSparks(symbols: readonly string[]): Promise<void> {
    for (const symbol of symbols) {
      if (this.closes().has(symbol)) continue;
      const history = await this.market.history(symbol, '1M');
      if (history?.bars.length) {
        this.closes.update((m) =>
          new Map(m).set(
            symbol,
            history.bars.map((b) => b.c),
          ),
        );
      }
    }
  }

  protected onKeydown(event: KeyboardEvent): void {
    const list = this.prefs.watchlist();
    if (!list.length) return;
    const index = this.active();
    let next: number;
    switch (event.key) {
      case 'ArrowDown':
        next = (index + 1) % list.length;
        break;
      case 'ArrowUp':
        next = (index - 1 + list.length) % list.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = list.length - 1;
        break;
      case 'Delete':
      case 'Backspace': {
        const symbol = list[index];
        if (!symbol) return;
        event.preventDefault();
        this.remove(symbol);
        this.focusRow(Math.min(index, this.prefs.watchlist().length - 1));
        return;
      }
      default:
        return;
    }
    event.preventDefault();
    this.focusRow(next);
  }

  private focusRow(index: number): void {
    this.active.set(Math.max(0, index));
    queueMicrotask(() => this.rowButtons()[this.active()]?.nativeElement.focus());
  }

  protected remove(symbol: string): void {
    this.prefs.unwatch(symbol);
    this.active.update((i) => Math.min(i, Math.max(0, this.prefs.watchlist().length - 1)));
  }

  protected pick(symbol: string): void {
    this.shell.pinnedSymbol.set(symbol);
    this.shell.insert(`/analyze ${symbol}`);
    this.picked.emit(symbol);
  }

  protected add(event: Event): void {
    event.preventDefault();
    const symbol = this.draft().trim().replace(/^\$/, '').toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol)) {
      this.error.set('Enter a ticker such as NVDA or BRK.B.');
      return;
    }
    this.error.set('');
    this.prefs.watch(symbol);
    this.draft.set('');
  }
}
