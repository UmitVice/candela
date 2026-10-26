import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { LayoutService } from '../../shell/layout.service';
import { ObservatoryDataService } from '../data/observatory-data.service';
import { flameRampCss } from '../engine/palette';
import type { HoverEvent } from '../engine/scene-canvas';
import { SceneCanvas } from '../engine/scene-canvas';
import { ObservatoryUi } from '../observatory-ui.service';
import type { CellHit } from '../scenes/field-scene';
import { FieldScene } from '../scenes/field-scene';
import type { Column, Row } from '../ui/data-table';
import { DataTable } from '../ui/data-table';

const STEP_MS = 1400;

@Component({
  selector: 'cd-field-view',
  imports: [SceneCanvas, DataTable],
  templateUrl: './field-view.html',
  styleUrls: ['./views.css', './field-view.css'],
})
export class FieldView {
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  private readonly layout = inject(LayoutService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly canvas = viewChild(SceneCanvas);

  protected readonly deltas = computed(() =>
    this.data.loraDeltas.hasValue() ? this.data.loraDeltas.value() : null,
  );
  protected readonly checkpoints = computed(() => this.deltas()?.checkpoints ?? []);
  protected readonly index = signal(0);
  protected readonly playing = signal(false);
  protected readonly hover = signal<{ x: number; y: number; text: string[] } | null>(null);
  protected readonly gradient = `linear-gradient(90deg, ${[0.12, 0.35, 0.6, 0.8, 1]
    .map((t) => flameRampCss(t))
    .join(', ')})`;

  private readonly stepParam = toSignal(
    this.route.queryParamMap.pipe(map((q) => Number(q.get('step') ?? NaN))),
    { initialValue: NaN },
  );

  protected readonly checkpoint = computed(() => this.checkpoints()[this.index()] ?? null);

  protected readonly module = computed(() => {
    const d = this.deltas();
    if (!d?.checkpoints.length || this.ui.dataView() || !this.ui.webgl2) return null;
    return untracked(() => {
      const scene = new FieldScene(d, this.layout.reducedMotion);
      scene.setPosition(this.index());
      return scene;
    });
  });

  protected readonly summary = computed(() => {
    const d = this.deltas();
    const cp = this.checkpoint();
    if (!d || !cp) return null;
    let adapted = 0;
    let top = { layer: 0, module: 0, value: 0 };
    cp.norms.forEach((row, l) =>
      row.forEach((v, m) => {
        if (v > 0) adapted++;
        if (v > top.value) top = { layer: l, module: m, value: v };
      }),
    );
    return {
      adapted,
      total: d.layers * d.modules.length,
      top:
        cp.step === 0 ? null : `${d.modules[top.module]} · L${top.layer} · ${top.value.toFixed(3)}`,
    };
  });

  protected readonly tableColumns = computed<Column[]>(() => [
    { key: 'layer', label: 'Layer', numeric: true },
    ...(this.deltas()?.modules ?? []).map((m) => ({ key: m, label: m, numeric: true })),
  ]);

  protected readonly tableRows = computed<Row[]>(() => {
    const d = this.deltas();
    const cp = this.checkpoint();
    if (!d || !cp) return [];
    return cp.norms
      .map((row, l) => ({ row, l }))
      .filter(({ row }) => row.some((v) => v > 0) || cp.step === 0)
      .map(({ row, l }) => {
        const r: Row = { layer: l };
        d.modules.forEach((m, i) => (r[m] = (row[i] ?? 0) > 0 ? (row[i] ?? 0).toFixed(4) : '0'));
        return r;
      });
  });

  constructor() {
    effect(() => {
      const cps = this.checkpoints();
      const step = this.stepParam();
      if (!cps.length) return;
      untracked(() => {
        const wanted = Number.isFinite(step)
          ? cps.findIndex((c) => c.step >= step)
          : cps.length - 1;
        this.index.set(wanted < 0 ? cps.length - 1 : wanted);
      });
    });

    effect(() => {
      const i = this.index();
      const scene = this.module();
      untracked(() => {
        if (!scene) return;
        scene.setPosition(i);
        this.canvas()?.invalidate();
      });
    });

    let timer: ReturnType<typeof setInterval> | undefined;
    effect(() => {
      clearInterval(timer);
      if (!this.playing()) return;
      timer = setInterval(() => {
        const n = this.checkpoints().length;
        const next = this.index() + 1;
        if (next >= n) {
          this.playing.set(false);
          return;
        }
        this.index.set(next);
      }, STEP_MS);
    });
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected play(): void {
    if (this.playing()) {
      this.playing.set(false);
      return;
    }
    if (this.index() >= this.checkpoints().length - 1) this.index.set(0);
    this.playing.set(true);
  }

  protected scrub(value: string): void {
    this.playing.set(false);
    this.index.set(Number(value));
    this.syncUrl();
  }

  private syncUrl(): void {
    const step = this.checkpoint()?.step;
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { step: step ?? null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected onHover(event: HoverEvent): void {
    const hit = event.hit as CellHit | null;
    const d = this.deltas();
    const cp = this.checkpoint();
    if (!hit || !d || !cp) {
      this.hover.set(null);
      return;
    }
    const value = cp.norms[hit.layer]?.[hit.module] ?? 0;
    this.hover.set({
      x: event.x,
      y: event.y,
      text: [
        `${d.modules[hit.module]} · layer ${hit.layer}`,
        value > 0 ? `‖scale·B·A‖_F = ${value.toFixed(6)}` : 'not adapted (frozen)',
        `checkpoint step ${cp.step}`,
      ],
    });
  }
}
