import { DialogRef } from '@angular/cdk/dialog';
import type { ElementRef } from '@angular/core';
import { Component, computed, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { LucideSearch } from '@lucide/angular';
import { COMMANDS, CommandService } from '../core/commands/commands';
import { ConversationsStore } from '../core/state/conversations.store';
import { downloadMarkdown } from '../core/state/export';
import { PreferencesStore } from '../core/state/preferences.store';
import { ShellStateService } from './shell-state.service';

interface PaletteItem {
  id: string;
  group: 'Commands' | 'Sessions' | 'Actions';
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
        aria-label="Search commands and sessions"
        aria-controls="palette-list"
        aria-expanded="true"
        aria-autocomplete="list"
        [attr.aria-activedescendant]="items()[active()] ? 'pal-' + items()[active()]?.id : null"
        placeholder="Type a command or search sessions…"
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
  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('input');

  protected readonly query = signal('');
  protected readonly active = signal(0);

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
        group: 'Sessions',
        label: c.title,
        hint: c.id === this.store.activeId() ? 'current' : 'open session',
        run: () => {
          this.store.select(c.id);
          void this.router.navigate(['/']);
        },
      }));
    const active = this.store.active();
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
    return [...commandItems, ...actions, ...sessions];
  });

  protected readonly items = computed(() => {
    const q = this.query().trim().toLowerCase().replace(/^\//, '');
    if (!q) return this.all();
    return this.all().filter(
      (item) =>
        item.label.toLowerCase().replace(/^\//, '').includes(q) ||
        item.hint.toLowerCase().includes(q),
    );
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
