import { CdkMenu, CdkMenuItemCheckbox, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, computed, inject, output } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import {
  LucideChevronDown,
  LucideCommand,
  LucideDownload,
  LucideMenu,
  LucidePanelRight,
  LucideTelescope,
  LucideSquareTerminal,
} from '@lucide/angular';
import { GatewayService } from '../core/gateway/gateway.service';
import { PwaService } from '../core/pwa/pwa.service';
import { PreferencesStore } from '../core/state/preferences.store';
import { BrandMark } from '../ui/brand-mark';
import { LayoutService } from './layout.service';
import { ModelStatusService } from './model-status.service';

@Component({
  selector: 'cd-top-bar',
  imports: [
    RouterLink,
    RouterLinkActive,
    BrandMark,
    CdkMenu,
    CdkMenuItemCheckbox,
    CdkMenuTrigger,
    LucideChevronDown,
    LucideCommand,
    LucideDownload,
    LucideMenu,
    LucidePanelRight,
    LucideTelescope,
    LucideSquareTerminal,
  ],
  templateUrl: './top-bar.html',
  styleUrl: './top-bar.css',
  host: { role: 'banner' },
})
export class TopBar {
  protected readonly layout = inject(LayoutService);
  protected readonly gateway = inject(GatewayService);
  protected readonly prefs = inject(PreferencesStore);
  protected readonly pwa = inject(PwaService);
  protected readonly models = inject(ModelStatusService);

  readonly openPalette = output();
  readonly openNav = output();
  readonly toggleContext = output();
  readonly openStatus = output();

  protected readonly pillTone = computed(() => {
    const state = this.models.state();
    if (state === 'connecting') return 'connecting';
    if (state === 'live') return 'live';
    return state === 'offline' ? 'offline' : 'replay';
  });
}
