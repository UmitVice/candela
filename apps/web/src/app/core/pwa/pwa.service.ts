import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { SwUpdate } from '@angular/service-worker';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const UPDATE_CHECK_MS = 30 * 60 * 1000;

@Injectable({ providedIn: 'root' })
export class PwaService {
  private readonly updates = inject(SwUpdate);
  private deferredPrompt: BeforeInstallPromptEvent | null = null;

  readonly updateReady = signal(false);
  readonly canInstall = signal(false);
  readonly installed = signal(
    typeof window !== 'undefined' && window.matchMedia('(display-mode: standalone)').matches,
  );
  readonly offline = signal(typeof navigator !== 'undefined' && !navigator.onLine);

  constructor() {
    const destroyRef = inject(DestroyRef);
    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      this.deferredPrompt = event as BeforeInstallPromptEvent;
      this.canInstall.set(true);
    };
    const onInstalled = () => {
      this.deferredPrompt = null;
      this.canInstall.set(false);
      this.installed.set(true);
    };
    const onOnline = () => this.offline.set(false);
    const onOffline = () => this.offline.set(true);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void this.check();
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    document.addEventListener('visibilitychange', onVisible);

    let interval: ReturnType<typeof setInterval> | undefined;
    if (this.updates.isEnabled) {
      const sub = this.updates.versionUpdates.subscribe((event) => {
        if (event.type === 'VERSION_READY') this.updateReady.set(true);
      });
      const unrecoverable = this.updates.unrecoverable.subscribe(() => this.updateReady.set(true));
      interval = setInterval(() => void this.check(), UPDATE_CHECK_MS);
      destroyRef.onDestroy(() => {
        sub.unsubscribe();
        unrecoverable.unsubscribe();
      });
    }

    destroyRef.onDestroy(() => {
      clearInterval(interval);
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      document.removeEventListener('visibilitychange', onVisible);
    });
  }

  async check(): Promise<void> {
    if (!this.updates.isEnabled || !navigator.onLine) return;
    try {
      await this.updates.checkForUpdate();
    } catch {
      /* the next interval retries */
    }
  }

  async install(): Promise<void> {
    const prompt = this.deferredPrompt;
    if (!prompt) return;
    await prompt.prompt();
    const choice = await prompt.userChoice;
    this.deferredPrompt = null;
    this.canInstall.set(false);
    if (choice.outcome === 'accepted') this.installed.set(true);
  }

  async applyUpdate(): Promise<void> {
    try {
      if (this.updates.isEnabled) await this.updates.activateUpdate();
    } finally {
      document.location.reload();
    }
  }

  dismissUpdate(): void {
    this.updateReady.set(false);
  }
}
