import {
  CdkMenu,
  CdkMenuGroup,
  CdkMenuItemCheckbox,
  CdkMenuItemRadio,
  CdkMenuTrigger,
} from '@angular/cdk/menu';
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
import type { ModelPreference } from '../core/api/types';
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
    CdkMenuItemRadio,
    CdkMenuItemCheckbox,
    CdkMenuGroup,
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

  protected readonly tierOptions: { value: ModelPreference; label: string; hint: string }[] = [
    { value: 'auto', label: 'Auto', hint: 'Pro when a GPU worker is online, else lite' },
    { value: 'pro', label: 'Pro', hint: '12B on the Apple Silicon worker' },
    { value: 'lite', label: 'Lite', hint: 'Small, fast fallback model' },
  ];

  protected readonly pillTone = computed(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting';
    if (c.mode === 'replay') return 'replay';
    return c.reason ? 'degraded' : 'live';
  });
}
