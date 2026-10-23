import { Component, inject } from '@angular/core';
import { LucideRefreshCw, LucideX } from '@lucide/angular';
import { PwaService } from '../core/pwa/pwa.service';

@Component({
  selector: 'cd-update-toast',
  imports: [LucideRefreshCw, LucideX],
  template: `
    @if (pwa.updateReady()) {
      <div class="toast" role="status" aria-live="polite">
        <span class="mono">A new version of Candela is ready.</span>
        <button type="button" class="btn btn-primary" (click)="pwa.applyUpdate()">
          <svg lucideRefreshCw [size]="13"></svg>
          Reload
        </button>
        <button type="button" class="icon-btn" aria-label="Dismiss" (click)="pwa.dismissUpdate()">
          <svg lucideX [size]="14"></svg>
        </button>
      </div>
    }
  `,
  styles: `
    :host {
      position: fixed;
      left: 50%;
      bottom: calc(var(--status-h) + 16px + var(--safe-bottom));
      z-index: 1100;
      transform: translateX(-50%);
      width: max-content;
      max-width: calc(100vw - 24px);
    }
    .toast {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 8px 8px 14px;
      border: 1px solid var(--line-strong);
      border-left: 2px solid var(--accent);
      border-radius: 6px;
      background: var(--bg-2);
      box-shadow: 0 12px 32px rgb(0 0 0 / 0.5);
      font-size: 12.5px;
      animation: rise var(--dur-slow) var(--ease-out);
    }
    .btn {
      height: 28px;
    }
    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
    }
    @media (max-width: 767.98px) {
      :host {
        top: calc(var(--topbar-h) + var(--safe-top) + 8px);
        bottom: auto;
      }
      .toast span {
        font-size: 12px;
      }
    }
  `,
})
export class UpdateToast {
  protected readonly pwa = inject(PwaService);
}
