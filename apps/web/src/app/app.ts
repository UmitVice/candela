import { Component, computed, effect, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';
import { PreferencesStore } from './core/state/preferences.store';
import { CommandPalette } from './shell/command-palette';
import { ContextPanel } from './shell/context-panel';
import { LayoutService } from './shell/layout.service';
import { LeftRail } from './shell/left-rail';
import { SheetService } from './shell/sheet.service';
import { StatusLine } from './shell/status-line';
import { TopBar } from './shell/top-bar';
import { UpdateToast } from './shell/update-toast';

@Component({
  selector: 'cd-root',
  imports: [RouterOutlet, TopBar, LeftRail, ContextPanel, StatusLine, UpdateToast],
  templateUrl: './app.html',
  styleUrl: './app.css',
  host: {
    '(document:keydown)': 'onKeydown($event)',
  },
})
export class App {
  protected readonly layout = inject(LayoutService);
  protected readonly prefs = inject(PreferencesStore);
  private readonly sheets = inject(SheetService);
  private readonly router = inject(Router);

  protected readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );
  protected readonly onObservatory = computed(() => this.url().startsWith('/observatory'));
  protected readonly showRail = computed(() => !this.layout.isMobile() && !this.onObservatory());
  protected readonly railCollapsed = computed(
    () => this.layout.isTablet() || this.prefs.railCollapsed(),
  );
  protected readonly showContext = computed(
    () => this.layout.isDesktop() && this.prefs.contextOpen() && !this.onObservatory(),
  );

  constructor() {
    effect(() => {
      if (this.layout.isDesktop()) this.sheets.closeAll();
    });
  }

  protected openPalette(): void {
    const ref = this.sheets.open(CommandPalette, { placement: 'center', label: 'Command palette' });
    queueMicrotask(() => ref.componentInstance?.focus());
  }

  protected openNav(): void {
    this.sheets.open(LeftRail, {
      placement: this.layout.isMobile() ? 'bottom' : 'left',
      label: 'Sessions and watchlist',
    });
  }

  protected expandRail(): void {
    if (this.layout.isDesktop()) this.prefs.railCollapsed.set(false);
    else this.openNav();
  }

  protected toggleContext(): void {
    if (this.layout.isDesktop()) {
      if (this.onObservatory()) void this.router.navigate(['/']);
      this.prefs.contextOpen.update((open) => (this.onObservatory() ? true : !open));
      return;
    }
    this.sheets.open(ContextPanel, {
      placement: this.layout.isMobile() ? 'bottom' : 'right',
      label: 'Context',
    });
  }

  protected openStatus(): void {
    this.sheets.open(ContextPanel, {
      placement: this.layout.isMobile() ? 'bottom' : 'right',
      label: 'Status',
      data: { variant: 'status' },
    });
  }

  protected onKeydown(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this.openPalette();
    }
  }
}
