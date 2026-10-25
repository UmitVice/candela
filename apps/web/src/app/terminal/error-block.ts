import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import type { AssistantTurn } from '../core/state/conversation.model';

const HINTS: Record<string, string> = {
  rate_limited: 'Too many requests in a short time.',
  overloaded:
    'Candela runs on a single GPU and serves one conversation at a time; the queue is full right now.',
  upstream_unavailable: 'The model server is unreachable.',
  upstream_timeout: 'The model took too long to respond.',
  data_unavailable: 'A market data provider failed.',
  invalid_request: 'The request was rejected.',
  unauthorized: 'Not authorized.',
  not_found: 'Not found.',
  internal: 'Something went wrong on our side.',
};

@Component({
  selector: 'cd-error-block',
  template: `
    @let e = error();
    @if (e) {
      <div class="err mono" role="alert">
        <div>
          <span class="x">✗</span> <span class="code">{{ e.code }}</span> — {{ e.message }}
        </div>
        <div class="hint">{{ hint() }}</div>
        <div class="actions">
          <button
            type="button"
            class="btn"
            [disabled]="remaining() > 0 || disabled()"
            (click)="retry.emit()"
          >
            @if (remaining() > 0) {
              Retry in {{ remaining() }} s
            } @else {
              Retry
            }
          </button>
          @if (countdown()) {
            <label class="auto">
              <input
                type="checkbox"
                [checked]="autoRetry()"
                (change)="autoRetry.set($any($event.target).checked)"
              />
              retry automatically
            </label>
          }
        </div>
      </div>
    }
  `,
  styles: `
    .err {
      margin-top: 6px;
      padding: 8px 12px;
      border: 1px solid rgb(246 70 93 / 0.35);
      border-left: 2px solid var(--down);
      border-radius: 6px;
      background: rgb(246 70 93 / 0.06);
      color: var(--fg-0);
      font-size: calc(var(--term-size) - 0.5px);
      line-height: var(--term-leading);
    }
    .x,
    .code {
      color: var(--down);
      font-weight: 600;
    }
    .hint {
      color: var(--fg-1);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
      margin-top: 8px;
    }
    .auto {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--fg-1);
      font-size: 12px;
    }
    .auto input {
      accent-color: var(--accent);
    }
    .btn {
      height: 28px;
      font-family: var(--font-mono);
      font-size: 12px;
    }
    @media (max-width: 767.98px) {
      .btn {
        height: 44px;
      }
    }
  `,
})
export class ErrorBlock {
  readonly turn = input.required<AssistantTurn>();
  readonly disabled = input(false);
  readonly retryable = input(true);
  readonly retry = output();
  private readonly now = signal(Date.now());
  protected readonly autoRetry = signal(true);
  private autoFired = false;

  protected readonly error = computed(() => this.turn().error ?? null);
  protected readonly hint = computed(() => HINTS[this.error()?.code ?? ''] ?? '');
  protected readonly countdown = computed(
    () => this.retryable() && !!this.error()?.retryAfterMs && this.remainingAtStart() > 0,
  );
  private readonly remainingAtStart = computed(() => {
    const e = this.error();
    if (!e?.retryAfterMs) return 0;
    return new Date(e.at).getTime() + e.retryAfterMs - Date.now();
  });
  protected readonly remaining = computed(() => {
    const e = this.error();
    if (!e?.retryAfterMs) return 0;
    const until = new Date(e.at).getTime() + e.retryAfterMs;
    return Math.max(0, Math.ceil((until - this.now()) / 1000));
  });

  constructor() {
    let timer: ReturnType<typeof setInterval> | undefined;
    effect(() => {
      clearInterval(timer);
      if (this.error()?.retryAfterMs) {
        timer = setInterval(() => {
          this.now.set(Date.now());
          if (this.remaining() > 0) return;
          clearInterval(timer);
          if (this.countdown() && this.autoRetry() && !this.disabled() && !this.autoFired) {
            this.autoFired = true;
            this.retry.emit();
          }
        }, 250);
      }
    });
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
}
