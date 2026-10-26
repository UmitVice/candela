import { Injectable, computed, inject, signal } from '@angular/core';
import type { ModelInfo, TelemetryFrame } from '../api/types';
import { PreferencesStore } from '../state/preferences.store';

const CAPACITY = 256;
const PUBLISH_MS = 50;

export interface TelemetrySession {
  modelId: string;
  displayName: string;
  supportsTelemetry: boolean;
  startedAt: number;
  active: boolean;
}

// Frames land in a ring buffer that render loops read directly; signals are republished at most
// every 50 ms (20 Hz) so Angular views never re-render per token.
@Injectable({ providedIn: 'root' })
export class TelemetryStore {
  private readonly prefs = inject(PreferencesStore);
  private readonly ring: (TelemetryFrame | undefined)[] = new Array<TelemetryFrame | undefined>(
    CAPACITY,
  );
  private written = 0;
  private publishTimer: ReturnType<typeof setTimeout> | undefined;

  readonly observatoryVisible = signal(false);
  readonly wanted = computed(() => this.prefs.telemetry() || this.observatoryVisible());
  readonly session = signal<TelemetrySession | null>(null);
  readonly latest = signal<TelemetryFrame | null>(null);
  readonly count = signal(0);

  get total(): number {
    return this.written;
  }

  frameAt(index: number): TelemetryFrame | undefined {
    if (index < 0 || index >= this.written || index < this.written - CAPACITY) return undefined;
    return this.ring[index % CAPACITY];
  }

  recent(limit: number): TelemetryFrame[] {
    const frames: TelemetryFrame[] = [];
    for (let i = Math.max(0, this.written - limit); i < this.written; i++) {
      const frame = this.frameAt(i);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  begin(model: ModelInfo): void {
    this.session.set({
      modelId: model.id,
      displayName: model.displayName,
      supportsTelemetry: model.supportsTelemetry,
      startedAt: Date.now(),
      active: true,
    });
  }

  push(frame: TelemetryFrame): void {
    if (!isFrame(frame)) return;
    this.ring[this.written % CAPACITY] = frame;
    this.written++;
    this.schedulePublish();
  }

  end(): void {
    const s = this.session();
    if (s?.active) this.session.set({ ...s, active: false });
    this.publish();
  }

  private schedulePublish(): void {
    if (this.publishTimer !== undefined) return;
    this.publishTimer = setTimeout(() => {
      this.publishTimer = undefined;
      this.publish();
    }, PUBLISH_MS);
  }

  private publish(): void {
    this.latest.set(this.frameAt(this.written - 1) ?? null);
    this.count.set(this.written);
  }
}

function isFrame(value: unknown): value is TelemetryFrame {
  const f = value as Partial<TelemetryFrame> | null;
  return (
    !!f &&
    typeof f.step === 'number' &&
    typeof f.entropy === 'number' &&
    Array.isArray(f.topK) &&
    Array.isArray(f.layers)
  );
}
