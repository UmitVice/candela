import { Component, computed, inject } from '@angular/core';
import { LucideRefreshCw } from '@lucide/angular';
import type { ModelPreference } from '../core/api/types';
import { RUNTIME_CONFIG } from '../core/config/runtime-config';
import { GatewayService } from '../core/gateway/gateway.service';
import { PwaService } from '../core/pwa/pwa.service';
import { PreferencesStore } from '../core/state/preferences.store';
import { ModelStatusService } from './model-status.service';

@Component({
  selector: 'cd-status-details',
  imports: [LucideRefreshCw],
  template: `
    <dl class="kv">
      <dt>Connection</dt>
      <dd>
        <span class="state" [attr.data-tone]="tone()">{{ connectionLabel() }}</span>
      </dd>
      @if (gateway.connection().reason) {
        <dt class="sr-only">Detail</dt>
        <dd class="reason">{{ gateway.connection().reason }}</dd>
      }
      <dt>Model</dt>
      <dd class="mono">{{ models.model()?.id ?? '—' }}</dd>
      <dt>Tier</dt>
      <dd class="mono">
        {{ models.model()?.tier?.toUpperCase() ?? '—' }} · {{ models.model()?.runtime ?? '' }}
        {{ models.model()?.quantization ?? '' }}
      </dd>
      <dt>Base</dt>
      <dd class="mono small">{{ models.model()?.baseModel ?? '—' }}</dd>
      <dt>Market data</dt>
      <dd class="mono">snapshot · {{ gateway.snapshotAsOf() ?? '—' }}</dd>
      <dt>Throughput</dt>
      <dd class="mono">
        {{ models.tokensPerSecond() ? models.tokensPerSecond() + ' tok/s' : '—' }}
      </dd>
      <dt>Release</dt>
      <dd class="mono">{{ config.release }}{{ pwa.offline() ? ' · offline' : '' }}</dd>
    </dl>

    <fieldset class="tiers">
      <legend class="label">Inference tier</legend>
      @for (tier of tiers; track tier) {
        <label class="tier">
          <input
            type="radio"
            name="tier"
            [value]="tier"
            [checked]="prefs.model() === tier"
            (change)="prefs.model.set(tier)"
          />
          <span>{{ tier }}</span>
        </label>
      }
    </fieldset>
    <label class="toggle">
      <input
        type="checkbox"
        [checked]="prefs.reasoning()"
        (change)="prefs.reasoning.set($any($event.target).checked)"
      />
      <span>Show reasoning</span>
    </label>

    @if (!gateway.forcedReplay) {
      <button
        type="button"
        class="btn reconnect"
        (click)="gateway.connect()"
        [disabled]="gateway.connection().state === 'connecting'"
      >
        <svg lucideRefreshCw [size]="13"></svg>
        Reconnect
      </button>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .kv {
      display: grid;
      grid-template-columns: 96px 1fr;
      gap: 6px 10px;
      margin: 0;
      font-size: 12px;
    }
    dt {
      color: var(--fg-2);
    }
    dd {
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
      color: var(--fg-0);
    }
    .small {
      font-size: 11px;
      color: var(--fg-1);
    }
    .reason {
      grid-column: 1 / -1;
      font-size: 11.5px;
      color: var(--fg-1);
    }
    .state {
      font-family: var(--font-mono);
    }
    .state[data-tone='live'] {
      color: var(--up);
    }
    .state[data-tone='replay'] {
      color: var(--warn);
    }
    .state[data-tone='connecting'] {
      color: var(--info);
    }
    .tiers {
      display: flex;
      align-items: center;
      gap: 12px;
      margin: 14px 0 0;
      padding: 0;
      border: 0;
    }
    .tiers legend {
      float: left;
      margin-right: 8px;
    }
    .tier,
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 32px;
      font-size: 12.5px;
      color: var(--fg-1);
      text-transform: capitalize;
    }
    input {
      accent-color: var(--accent);
    }
    .toggle {
      margin-top: 4px;
      text-transform: none;
    }
    .reconnect {
      margin-top: 10px;
      height: 28px;
      font-size: 12px;
    }
    @media (max-width: 767.98px) {
      .tier,
      .toggle {
        min-height: 44px;
      }
      .reconnect {
        height: 44px;
      }
    }
  `,
})
export class StatusDetails {
  protected readonly gateway = inject(GatewayService);
  protected readonly prefs = inject(PreferencesStore);
  protected readonly models = inject(ModelStatusService);
  protected readonly pwa = inject(PwaService);
  protected readonly config = inject(RUNTIME_CONFIG);
  protected readonly tiers: ModelPreference[] = ['auto', 'pro', 'lite'];

  protected readonly tone = computed(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting';
    return c.mode === 'replay' ? 'replay' : 'live';
  });

  protected readonly connectionLabel = computed(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting…';
    if (c.mode === 'replay') return 'replay · recorded demo';
    return `live · ${c.transport.toUpperCase()}`;
  });
}
