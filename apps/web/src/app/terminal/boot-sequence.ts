import { Component, DestroyRef, computed, effect, inject, output, signal } from '@angular/core';
import { RUNTIME_CONFIG } from '../core/config/runtime-config';
import { GatewayService } from '../core/gateway/gateway.service';
import { LayoutService } from '../shell/layout.service';
import { ModelStatusService } from '../shell/model-status.service';

const SEEN_KEY = 'candela.booted';
const STEP_MS = 220;

interface BootLine {
  key: string;
  label: string;
  value: string;
  tone: 'ok' | 'warn' | 'info' | 'plain';
}

function seen(): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return true;
  }
}

@Component({
  selector: 'cd-boot-sequence',
  template: `
    <div class="boot mono" aria-label="Session status">
      <div class="title">
        <span class="brand">candela</span> terminal {{ config.release }}
        <span class="dim">· open financial-analysis LLM</span>
      </div>
      @for (line of visible(); track line.key) {
        <div class="line">
          <span class="arrow" aria-hidden="true">›</span>
          <span class="key-label">{{ line.label }}</span>
          <span class="dots" aria-hidden="true"></span>
          <span class="value" [attr.data-tone]="line.tone">{{ line.value }}</span>
        </div>
      }
      @if (complete()) {
        <div class="hint">
          Type a question, or <span class="key">/</span> for commands. Not financial advice.
        </div>
      } @else {
        <div class="line pending"><span class="cursor" aria-hidden="true">▋</span></div>
      }
    </div>
  `,
  styleUrl: './boot-sequence.css',
  host: { '(document:keydown)': 'skip()', '(document:pointerdown)': 'skip()' },
})
export class BootSequence {
  protected readonly config = inject(RUNTIME_CONFIG);
  private readonly gateway = inject(GatewayService);
  private readonly models = inject(ModelStatusService);
  private readonly layout = inject(LayoutService);
  readonly done = output();

  private readonly step = signal(seen() || this.layout.reducedMotion ? 99 : 0);

  private readonly lines = computed<BootLine[]>(() => {
    const c = this.gateway.connection();
    const m = this.models.expectedModel();
    const asOf = this.gateway.snapshotAsOf();
    const gatewayValue =
      c.state === 'connecting'
        ? 'connecting…'
        : c.mode === 'replay'
          ? this.gateway.forcedReplay
            ? 'replay · recorded demo sessions'
            : 'offline → replay · recorded demo'
          : `online · ${c.transport.toUpperCase()}${c.baseUrl ? '' : ' · same origin'}`;
    return [
      {
        key: 'gw',
        label: 'gateway',
        value: gatewayValue,
        tone: c.mode === 'replay' ? 'warn' : c.state === 'online' ? 'ok' : 'info',
      },
      {
        key: 'inf',
        label: 'inference',
        value: m
          ? `${m.id} · ${m.tier.toUpperCase()} · ${m.runtime} ${m.quantization}`
          : 'resolving…',
        tone: m ? 'ok' : 'info',
      },
      {
        key: 'mkt',
        label: 'market data',
        value: asOf ? `snapshot · as of ${asOf} · delayed` : 'unknown',
        tone: asOf ? 'plain' : 'info',
      },
    ];
  });

  protected readonly visible = computed(() =>
    this.gateway.ready() ? this.lines().slice(0, this.step()) : [],
  );
  protected readonly complete = computed(
    () => this.gateway.ready() && this.step() >= this.lines().length,
  );

  constructor() {
    let timer: ReturnType<typeof setTimeout> | undefined;
    effect(() => {
      if (!this.gateway.ready()) return;
      const step = this.step();
      clearTimeout(timer);
      if (step < this.lines().length)
        timer = setTimeout(() => this.step.update((s) => s + 1), STEP_MS);
      else this.finish();
    });
    inject(DestroyRef).onDestroy(() => clearTimeout(timer));
  }

  protected skip(): void {
    if (this.step() < 99) this.step.set(99);
  }

  private finish(): void {
    try {
      sessionStorage.setItem(SEEN_KEY, '1');
    } catch {
      /* session storage may be disabled */
    }
    this.done.emit();
  }
}
