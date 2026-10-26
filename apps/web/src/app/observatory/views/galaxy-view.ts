import { Component, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { LayoutService } from '../../shell/layout.service';
import { ShellStateService } from '../../shell/shell-state.service';
import type { GalaxyPoint } from '../data/artifacts';
import { ObservatoryDataService } from '../data/observatory-data.service';
import type { HoverEvent } from '../engine/scene-canvas';
import { SceneCanvas } from '../engine/scene-canvas';
import { ObservatoryUi } from '../observatory-ui.service';
import type { PointHit } from '../scenes/galaxy-scene';
import { GalaxyScene } from '../scenes/galaxy-scene';
import type { Column, Row } from '../ui/data-table';
import { DataTable } from '../ui/data-table';
import { shortDate } from '../ui/format';

@Component({
  selector: 'cd-galaxy-view',
  imports: [SceneCanvas, DataTable],
  templateUrl: './galaxy-view.html',
  styleUrls: ['./views.css', './galaxy-view.css'],
})
export class GalaxyView {
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  private readonly layout = inject(LayoutService);
  private readonly shell = inject(ShellStateService);
  private readonly router = inject(Router);
  private readonly canvas = viewChild(SceneCanvas);

  protected readonly galaxy = computed(() =>
    this.data.galaxy.hasValue() ? this.data.galaxy.value() : null,
  );
  protected readonly hidden = signal<ReadonlySet<string>>(new Set());
  protected readonly selected = signal<GalaxyPoint | null>(null);
  protected readonly hover = signal<{ x: number; y: number; point: GalaxyPoint } | null>(null);
  protected readonly query = signal('');
  protected readonly notice = signal('');
  protected readonly shortDate = shortDate;

  protected readonly module = computed(() => {
    const g = this.galaxy();
    if (!g?.points.length || this.ui.dataView() || !this.ui.webgl2) return null;
    return untracked(
      () =>
        new GalaxyScene(
          g,
          Math.min(this.layout.isMobile() ? 1.5 : 2, window.devicePixelRatio || 1),
        ),
    );
  });

  protected readonly sectors = computed(() => {
    const g = this.galaxy();
    if (!g) return [];
    const counts = new Map<string, number>();
    for (const p of g.points) counts.set(p.sector, (counts.get(p.sector) ?? 0) + 1);
    return g.sectors.map((s) => ({ ...s, count: counts.get(s.id) ?? 0 }));
  });

  protected readonly sectorName = computed(
    () => new Map((this.galaxy()?.sectors ?? []).map((s) => [s.id, s.name])),
  );

  protected readonly columns: Column[] = [
    { key: 'symbol', label: 'Symbol' },
    { key: 'name', label: 'Company' },
    { key: 'sector', label: 'Sector' },
    { key: 'cap', label: 'Market cap ($B)', numeric: true },
    { key: 'x', label: 'x', numeric: true },
    { key: 'y', label: 'y', numeric: true },
    { key: 'z', label: 'z', numeric: true },
  ];

  protected readonly rows = computed<Row[]>(() => {
    const names = this.sectorName();
    return (this.galaxy()?.points ?? [])
      .slice()
      .sort((a, b) => (b.marketCapB ?? 0) - (a.marketCapB ?? 0))
      .map((p) => ({
        symbol: p.symbol,
        name: p.name,
        sector: names.get(p.sector) ?? p.sector,
        cap: p.marketCapB?.toFixed(1),
        x: p.x.toFixed(3),
        y: p.y.toFixed(3),
        z: p.z.toFixed(3),
      }));
  });

  constructor() {
    effect(() => {
      const scene = this.module();
      const hidden = this.hidden();
      const selected = this.selected();
      untracked(() => {
        if (!scene) return;
        scene.setHidden(new Set(hidden));
        scene.select(selected ? scene.indexOf(selected.symbol) : -1);
        this.canvas()?.invalidate();
      });
    });
  }

  protected toggleSector(id: string): void {
    this.hidden.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected onHover(event: HoverEvent): void {
    const hit = event.hit as PointHit | null;
    this.hover.set(hit ? { x: event.x, y: event.y, point: hit.point } : null);
    this.canvas()?.invalidate();
  }

  protected onPick(hit: unknown): void {
    const point = (hit as PointHit | null)?.point ?? null;
    this.selected.set(point);
    this.notice.set('');
  }

  protected find(): void {
    const q = this.query().trim().toUpperCase();
    if (!q) return;
    const g = this.galaxy();
    const point =
      g?.points.find((p) => p.symbol === q) ??
      g?.points.find((p) => p.name.toUpperCase().includes(q)) ??
      null;
    this.selected.set(point);
    this.notice.set(point ? '' : `No point for “${this.query().trim()}” in this galaxy.`);
  }

  protected focusInTerminal(point: GalaxyPoint): void {
    this.shell.pinnedSymbol.set(point.symbol);
    this.notice.set(`${point.symbol} is pinned in the terminal context panel.`);
  }

  protected analyze(point: GalaxyPoint): void {
    this.shell.pinnedSymbol.set(point.symbol);
    this.shell.insert(`/analyze ${point.symbol}`);
    if (!this.layout.isWide()) void this.router.navigate(['/']);
    else this.notice.set(`/analyze ${point.symbol} is ready in the terminal prompt.`);
  }
}
