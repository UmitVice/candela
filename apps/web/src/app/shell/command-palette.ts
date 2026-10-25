import { DialogRef } from '@angular/cdk/dialog';
import type { ElementRef } from '@angular/core';
import { Component, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { LucideSearch } from '@lucide/angular';
import type { SymbolMatch } from '../core/api/types';
import { COMMANDS, CommandService } from '../core/commands/commands';
import { MarketService } from '../core/gateway/market.service';
import { ConversationsStore } from '../core/state/conversations.store';
import { downloadMarkdown } from '../core/state/export';
import { PreferencesStore } from '../core/state/preferences.store';
import { ShellStateService } from './shell-state.service';

interface PaletteItem {
  id: string;
  group: 'Commands' | 'Symbols' | 'Conversations' | 'Settings' | 'Actions';
  label: string;
  hint: string;
  run: () => void;
}

@Component({
  selector: 'cd-command-palette',
  imports: [LucideSearch],
  template: `
    <div class="search">
      <svg lucideSearch [size]="15"></svg>
      <input
        #input
        role="combobox"
        aria-label="Search commands, symbols, conversations and settings"
        aria-controls="palette-list"
        aria-expanded="true"
        aria-autocomplete="list"
        [attr.aria-activedescendant]="items()[active()] ? 'pal-' + items()[active()]?.id : null"
        placeholder="Commands, symbols, conversations, settings…"
        autocomplete="off"
        spellcheck="false"
        [value]="query()"
        (input)="onInput($any($event.target).value)"
        (keydown)="onKey($event)"
      />
      <span class="kbd">Esc</span>
    </div>
    <ul id="palette-list" role="listbox" class="list panel-scroll" aria-label="Results">
      @for (item of items(); track item.id; let i = $index) {
        @if (i === 0 || items()[i - 1]?.group !== item.group) {
          <li class="group" role="presentation">{{ item.group }}</li>
        }
        <li
          [id]="'pal-' + item.id"
          role="option"
          class="item"
          [class.active]="i === active()"
          [attr.aria-selected]="i === active()"
          tabindex="-1"
          (mousemove)="active.set(i)"
          (click)="run(item)"
          (keydown.enter)="run(item)"
        >
          <span class="item-label mono">{{ item.label }}</span>
          <span class="item-hint">{{ item.hint }}</span>
        </li>
      } @empty {
        <li class="empty" role="presentation">No matches.</li>
      }
    </ul>
  `,
  styleUrl: './command-palette.css',
})
export class CommandPalette {
  private readonly dialogRef = inject(DialogRef);
  private readonly commands = inject(CommandService);
  private readonly store = inject(ConversationsStore);
  private readonly prefs = inject(PreferencesStore);
  private readonly shell = inject(ShellStateService);
  private readonly router = inject(Router);
  private readonly market = inject(MarketService);
  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('input');

  protected readonly query = signal('');
  protected readonly active = signal(0);
  private readonly symbols = signal<SymbolMatch[]>([]);

  constructor() {
    let seq = 0;
    effect((onCleanup) => {
      const q = this.query().trim().replace(/^\$/, '');
      const id = ++seq;
      if (!q || q.startsWith('/') || q.length > 32) {
        this.symbols.set([]);
        return;
      }
      const timer = setTimeout(async () => {
        const results = await this.market.search(q, 5);
        if (id === seq) this.symbols.set(results);
      }, 160);
      onCleanup(() => clearTimeout(timer));
    });
  }

  private readonly all = computed<PaletteItem[]>(() => {
    const commandItems: PaletteItem[] = COMMANDS.map((c) => ({
      id: `cmd-${c.name}`,
      group: 'Commands',
      label: c.usage,
      hint: c.description,
      run: () => {
        if (c.usage.includes('<') || c.usage.includes('|')) this.shell.insert(`/${c.name} `);
        else this.commands.execute(`/${c.name}`);
      },
    }));
    const sessions: PaletteItem[] = this.store
      .sorted()
      .filter((c) => c.turns.length > 0)
      .slice(0, 12)
      .map((c) => ({
        id: `ses-${c.id}`,
        group: 'Conversations',
        label: c.title,
        hint: c.id === this.store.activeId() ? 'current' : 'open conversation',
        run: () => {
          this.store.select(c.id);
          void this.router.navigate(['/']);
        },
      }));
    const active = this.store.active();
    const settings: PaletteItem[] = [
      {
        id: 'set-reasoning',
        group: 'Settings',
        label: `Reasoning: ${this.prefs.reasoning() ? 'on' : 'off'}`,
        hint: this.prefs.reasoning() ? 'turn off thinking tokens' : 'show thinking tokens',
        run: () => this.prefs.reasoning.update((v) => !v),
      },
      {
        id: 'set-telemetry',
        group: 'Settings',
        label: `Telemetry: ${this.prefs.telemetry() ? 'on' : 'off'}`,
        hint: this.prefs.telemetry()
          ? 'stop streaming model internals'
          : 'stream model internals for the Observatory',
        run: () => this.prefs.telemetry.update((v) => !v),
      },
      {
        id: 'set-model',
        group: 'Settings',
        label: `Model: ${this.prefs.model() === 'pro' ? 'Candela Pro only' : 'auto'}`,
        hint:
          this.prefs.model() === 'pro'
            ? 'switch to auto routing'
            : 'require the Candela Pro GPU worker',
        run: () => this.prefs.model.update((m) => (m === 'pro' ? 'auto' : 'pro')),
      },
    ];
    const actions: PaletteItem[] = [
      {
        id: 'act-context',
        group: 'Actions',
        label: this.prefs.contextOpen() ? 'Hide context panel' : 'Show context panel',
        hint: 'layout',
        run: () => this.prefs.contextOpen.update((v) => !v),
      },
      {
        id: 'act-rail',
        group: 'Actions',
        label: this.prefs.railCollapsed() ? 'Expand sidebar' : 'Collapse sidebar',
        hint: 'layout',
        run: () => this.prefs.railCollapsed.update((v) => !v),
      },
      ...(active?.turns.length
        ? [
            {
              id: 'act-export',
              group: 'Actions' as const,
              label: 'Export session as Markdown',
              hint: active.title,
              run: () => downloadMarkdown(active),
            },
          ]
        : []),
    ];
    return [...commandItems, ...settings, ...actions, ...sessions];
  });

  private readonly symbolItems = computed<PaletteItem[]>(() =>
    this.symbols().map((m) => ({
      id: `sym-${m.symbol}`,
      group: 'Symbols',
      label: m.symbol,
      hint: `${m.name} · ${m.exchange} · prefill /analyze`,
      run: () => {
        this.shell.pinnedSymbol.set(m.symbol);
        this.shell.insert(`/analyze ${m.symbol}`);
        void this.router.navigate(['/']);
      },
    })),
  );

  protected readonly items = computed(() => {
    const q = this.query().trim().toLowerCase().replace(/^\//, '');
    if (!q) return this.all();
    const matches = this.all().filter(
      (item) =>
        item.label.toLowerCase().replace(/^\//, '').includes(q) ||
        item.hint.toLowerCase().includes(q),
    );
    const commands = matches.filter((i) => i.group === 'Commands');
    return [...commands, ...this.symbolItems(), ...matches.filter((i) => i.group !== 'Commands')];
  });

  protected onInput(value: string): void {
    this.query.set(value);
    this.active.set(0);
  }

  protected onKey(event: KeyboardEvent): void {
    const count = this.items().length;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.active.update((i) => (count ? (i + 1) % count : 0));
      this.scrollActive();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.active.update((i) => (count ? (i - 1 + count) % count : 0));
      this.scrollActive();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const item = this.items()[this.active()];
      if (item) this.run(item);
      else if (this.query().startsWith('/')) {
        this.dialogRef.close();
        this.commands.execute(this.query());
      }
    }
  }

  private scrollActive(): void {
    queueMicrotask(() => {
      const id = this.items()[this.active()]?.id;
      if (id) document.getElementById(`pal-${id}`)?.scrollIntoView({ block: 'nearest' });
    });
  }

  protected run(item: PaletteItem): void {
    this.dialogRef.close();
    item.run();
  }

  focus(): void {
    this.input().nativeElement.focus();
  }
}
