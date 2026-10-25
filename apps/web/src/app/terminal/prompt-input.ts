import type { ElementRef } from '@angular/core';
import {
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { LucideArrowUp, LucideSquare } from '@lucide/angular';
import type { SymbolMatch } from '../core/api/types';
import type { CommandSpec } from '../core/commands/commands';
import { matchCommands } from '../core/commands/commands';
import { MarketService } from '../core/gateway/market.service';
import { PreferencesStore } from '../core/state/preferences.store';
import { LayoutService } from '../shell/layout.service';
import { ShellStateService } from '../shell/shell-state.service';

const SYMBOL_TOKEN = /(?:^|\s)\$([A-Za-z][A-Za-z0-9.-]{0,9})$/;
const COMMAND_SYMBOL =
  /^\/(?:analyze|compare|chart|fundamentals|forecast|watch|unwatch)\s+(?:\S+\s+)*([A-Za-z][A-Za-z0-9.-]{0,9})$/i;
const SEARCH_DEBOUNCE_MS = 160;

interface SymbolToken {
  query: string;
  start: number;
  end: number;
  dollar: boolean;
}

const CHIPS = [
  '/analyze NVDA',
  '/compare AAPL MSFT',
  '/chart TSLA 1Y',
  '/forecast AMD',
  '/fundamentals AAPL',
  '/watch META',
  '/help',
];

@Component({
  selector: 'cd-prompt-input',
  imports: [LucideArrowUp, LucideSquare],
  templateUrl: './prompt-input.html',
  styleUrl: './prompt-input.css',
})
export class PromptInput {
  private readonly prefs = inject(PreferencesStore);
  private readonly market = inject(MarketService);
  private readonly shell = inject(ShellStateService);
  protected readonly layout = inject(LayoutService);

  readonly busy = input(false);
  readonly submitted = output<string>();
  readonly stop = output();

  private readonly textarea = viewChild.required<ElementRef<HTMLTextAreaElement>>('field');
  protected readonly value = signal('');
  protected readonly selected = signal(0);
  protected readonly dismissed = signal(false);
  private historyIndex = -1;
  private stash = '';
  protected readonly chips = CHIPS;

  protected readonly suggestions = computed<CommandSpec[]>(() =>
    this.dismissed() ? [] : matchCommands(this.value()),
  );
  private readonly caret = signal(0);
  protected readonly symbolResults = signal<SymbolMatch[]>([]);
  protected readonly symbolSelected = signal(0);
  private readonly token = computed<SymbolToken | null>(() => {
    if (this.dismissed()) return null;
    const value = this.value();
    const caret = this.caret();
    const after = value.slice(caret);
    if (after && !/^\s/.test(after)) return null;
    const before = value.slice(0, caret);
    const dollar = SYMBOL_TOKEN.exec(before);
    if (dollar?.[1]) {
      return { query: dollar[1], start: caret - dollar[1].length - 1, end: caret, dollar: true };
    }
    if (before.includes('\n')) return null;
    const command = COMMAND_SYMBOL.exec(before);
    if (command?.[1]) {
      return { query: command[1], start: caret - command[1].length, end: caret, dollar: false };
    }
    return null;
  });
  protected readonly symbolSuggestions = computed(() => (this.token() ? this.symbolResults() : []));
  protected readonly canSend = computed(() => this.value().trim().length > 0 && !this.busy());

  constructor() {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let seq = 0;
    effect((onCleanup) => {
      const token = this.token();
      const id = ++seq;
      if (!token) {
        this.symbolResults.set([]);
        return;
      }
      timer = setTimeout(async () => {
        const results = await this.market.search(token.query, 6);
        if (id !== seq) return;
        const exact = results.length === 1 && results[0]?.symbol === token.query.toUpperCase();
        this.symbolResults.set(exact ? [] : results);
        this.symbolSelected.set(0);
      }, SEARCH_DEBOUNCE_MS);
      onCleanup(() => clearTimeout(timer));
    });
    effect(() => {
      const draft = this.shell.draft();
      if (!draft) return;
      this.setValue(draft.text);
      this.focus();
    });
  }

  focus(): void {
    const el = this.textarea().nativeElement;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }

  protected trackCaret(): void {
    this.caret.set(this.textarea().nativeElement.selectionStart ?? this.value().length);
  }

  protected onInput(value: string): void {
    this.value.set(value);
    this.trackCaret();
    this.selected.set(0);
    this.dismissed.set(false);
    this.historyIndex = -1;
    this.autosize();
  }

  private setValue(value: string, caret = value.length): void {
    this.value.set(value);
    const el = this.textarea().nativeElement;
    el.value = value;
    el.setSelectionRange(caret, caret);
    this.caret.set(caret);
    this.autosize();
  }

  protected pickSymbol(match: SymbolMatch): void {
    const token = this.token();
    if (!token) return;
    const value = this.value();
    const insert = `${token.dollar ? '$' : ''}${match.symbol} `;
    const rest = value.slice(token.end).replace(/^\s+/, '');
    const next = value.slice(0, token.start) + insert + rest;
    this.symbolResults.set([]);
    this.setValue(next, token.start + insert.length);
    this.textarea().nativeElement.focus();
  }

  private autosize(): void {
    const el = this.textarea().nativeElement;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.isComposing) return;
    const suggestions = this.suggestions();
    const el = this.textarea().nativeElement;
    const symbols = this.symbolSuggestions();

    if (symbols.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        this.symbolSelected.update((i) => (i + delta + symbols.length) % symbols.length);
        return;
      }
      if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
        const pick = symbols[this.symbolSelected()];
        if (pick) {
          event.preventDefault();
          this.pickSymbol(pick);
          return;
        }
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.symbolResults.set([]);
        return;
      }
    }

    if (suggestions.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        this.selected.update((i) => (i + delta + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
        const pick = suggestions[this.selected()];
        const exact = this.value().slice(1).toLowerCase() === pick?.name;
        if (pick && !(event.key === 'Enter' && exact && !this.needsArgs(pick))) {
          event.preventDefault();
          this.complete(pick);
          return;
        }
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        this.dismissed.set(true);
        return;
      }
    }

    if (event.key === 'Escape' && this.busy()) {
      event.preventDefault();
      this.stop.emit();
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
      return;
    }
    if (event.key === 'ArrowUp' && !el.value.slice(0, el.selectionStart).includes('\n')) {
      const history = this.prefs.promptHistory();
      if (!history.length) return;
      event.preventDefault();
      if (this.historyIndex === -1) this.stash = this.value();
      this.historyIndex = Math.min(this.historyIndex + 1, history.length - 1);
      this.setValue(history[history.length - 1 - this.historyIndex] ?? '');
      return;
    }
    if (
      event.key === 'ArrowDown' &&
      this.historyIndex >= 0 &&
      !el.value.slice(el.selectionEnd).includes('\n')
    ) {
      event.preventDefault();
      this.historyIndex -= 1;
      const history = this.prefs.promptHistory();
      this.setValue(
        this.historyIndex >= 0
          ? (history[history.length - 1 - this.historyIndex] ?? '')
          : this.stash,
      );
    }
  }

  private needsArgs(spec: CommandSpec): boolean {
    return spec.usage.includes('<') || spec.usage.includes('|');
  }

  protected complete(spec: CommandSpec): void {
    if (this.needsArgs(spec)) {
      this.setValue(`/${spec.name} `);
      this.dismissed.set(true);
      this.focus();
    } else {
      this.setValue(`/${spec.name}`);
      this.send();
    }
  }

  protected useChip(chip: string): void {
    if (this.busy()) return;
    this.setValue(chip);
    this.send();
  }

  protected send(): void {
    const text = this.value().trim();
    if (!text || this.busy()) return;
    this.prefs.remember(text);
    this.historyIndex = -1;
    this.stash = '';
    this.setValue('');
    this.dismissed.set(false);
    this.submitted.emit(text);
  }
}
