import { Component, computed, inject, output } from '@angular/core';
import { RUNTIME_CONFIG } from '../core/config/runtime-config';
import { ChatService } from '../core/chat/chat.service';
import { GatewayService } from '../core/gateway/gateway.service';
import { PwaService } from '../core/pwa/pwa.service';
import { ModelStatusService } from './model-status.service';

@Component({
  selector: 'cd-status-line',
  template: `
    <button
      type="button"
      class="seg conn"
      [attr.data-tone]="tone()"
      (click)="openStatus.emit()"
      aria-label="Connection details"
    >
      <span class="dot" aria-hidden="true"></span>
      {{ connection() }}
    </button>
    <span class="seg">{{ models.model()?.id ?? '—' }}</span>
    <span class="seg hide-sm">data {{ gateway.snapshotAsOf() ?? '—' }}</span>
    @if (pwa.offline()) {
      <span class="seg warn">offline</span>
    }
    <span class="grow"></span>
    @if (chat.busy()) {
      <span class="seg busy">streaming…</span>
    } @else if (models.tokensPerSecond()) {
      <span class="seg">{{ models.tokensPerSecond() }} tok/s</span>
    }
    <span class="seg hide-sm">v{{ config.release }}</span>
    <span class="seg hide-sm"><span class="kbd">⌘K</span></span>
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      height: var(--status-h);
      padding: 0 8px;
      border-top: 1px solid var(--line);
      background: var(--bg-1);
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--fg-2);
      white-space: nowrap;
      overflow: hidden;
    }
    .seg {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 100%;
      padding: 0 8px;
      border-right: 1px solid var(--line);
    }
    .seg:last-child {
      border-right: 0;
    }
    .grow {
      flex: 1;
    }
    .conn {
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--fg-1);
      font: inherit;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .conn:hover {
      color: var(--fg-0);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--fg-2);
    }
    [data-tone='live'] .dot {
      background: var(--up);
    }
    [data-tone='replay'] .dot {
      background: var(--warn);
    }
    [data-tone='connecting'] .dot {
      background: var(--info);
    }
    .warn {
      color: var(--warn);
    }
    .busy {
      color: var(--accent);
    }
    .kbd {
      height: 16px;
      font-size: 10px;
    }
    @media (max-width: 1023.98px) {
      .hide-sm {
        display: none;
      }
    }
  `,
})
export class StatusLine {
  protected readonly gateway = inject(GatewayService);
  protected readonly chat = inject(ChatService);
  protected readonly models = inject(ModelStatusService);
  protected readonly pwa = inject(PwaService);
  protected readonly config = inject(RUNTIME_CONFIG);
  readonly openStatus = output();

  protected readonly tone = computed(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting';
    return c.mode === 'replay' ? 'replay' : 'live';
  });

  protected readonly connection = computed(() => {
    const c = this.gateway.connection();
    if (c.state === 'connecting') return 'connecting';
    return c.mode === 'replay' ? 'replay' : `live · ${c.transport}`;
  });
}
