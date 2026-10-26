import { Component, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { GatewayService } from '../../core/gateway/gateway.service';
import { TelemetryStore } from '../../core/telemetry/telemetry.store';
import { LayoutService } from '../../shell/layout.service';
import { ObservatoryDataService } from '../data/observatory-data.service';
import type { HoverEvent } from '../engine/scene-canvas';
import { SceneCanvas } from '../engine/scene-canvas';
import { kvGroupColor } from '../engine/palette';
import { ObservatoryUi } from '../observatory-ui.service';
import type { LayerHit } from '../scenes/tower-scene';
import { TowerScene, visibleToken } from '../scenes/tower-scene';
import type { Column, Row } from '../ui/data-table';
import { DataTable } from '../ui/data-table';
import { compact } from '../ui/format';

@Component({
  selector: 'cd-tower-view',
  imports: [SceneCanvas, DataTable],
  templateUrl: './tower-view.html',
  styleUrl: './views.css',
})
export class TowerView {
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  protected readonly telemetry = inject(TelemetryStore);
  protected readonly gateway = inject(GatewayService);
  private readonly layout = inject(LayoutService);
  private readonly canvas = viewChild(SceneCanvas);

  protected readonly spec = this.data.tower;
  protected readonly loading = computed(
    () => !this.spec() && (this.data.manifest.isLoading() || this.data.architecture.isLoading()),
  );

  protected readonly module = computed(() => {
    const spec = this.spec();
    if (!spec || this.ui.dataView() || !this.ui.webgl2) return null;
    return untracked(() => new TowerScene(spec, this.telemetry, this.layout.reducedMotion));
  });

  protected readonly hover = signal<{ x: number; y: number; text: string[] } | null>(null);

  protected readonly kvLegend = computed(() => {
    const s = this.spec();
    if (!s) return [];
    const groups = Math.max(1, Math.min(s.heads, s.kvHeads));
    return Array.from({ length: Math.min(groups, 8) }, (_, g) => ({
      color: `#${kvGroupColor(g, groups).getHexString()}`,
    }));
  });

  protected readonly frame = this.telemetry.latest;

  protected readonly status = computed(() => {
    const session = this.telemetry.session();
    const frame = this.frame();
    if (this.gateway.isReplay()) {
      return {
        live: false,
        text: 'Replay mode. Live telemetry streams only from the Candela gateway with a worker online; the tower shows the architecture.',
      };
    }
    if (session && !session.supportsTelemetry) {
      return {
        live: false,
        text: `${session.displayName} does not stream telemetry, so the tower stays in ambient mode.`,
      };
    }
    if (session?.active && frame) {
      return {
        live: true,
        text: `token #${frame.step} · “${visibleToken(frame.token)}” · ${frame.phase} · entropy ${frame.entropy.toFixed(2)} nats`,
      };
    }
    if (frame && session) {
      return {
        live: false,
        text: `Last generation: ${this.telemetry.count()} frames from ${session.displayName}. Send a prompt to stream again.`,
      };
    }
    return {
      live: false,
      text: 'Waiting for a generation. While the Observatory is open, every prompt requests per-token telemetry.',
    };
  });

  protected readonly mismatch = computed(() => {
    const session = this.telemetry.session();
    const spec = this.spec();
    const frame = this.frame();
    if (!session || !spec || !frame || session.modelId === spec.id) return null;
    return { name: session.displayName, remapped: frame.layers.length !== spec.layers };
  });

  protected readonly specRows = computed<Row[]>(() => {
    const s = this.spec();
    if (!s) return [];
    return [
      { k: 'Model', v: s.label },
      { k: 'Family', v: s.family },
      { k: 'Decoder layers', v: s.layers },
      { k: 'Attention heads', v: s.heads },
      { k: 'KV heads', v: s.kvHeads },
      { k: 'Head dim', v: s.headDim },
      { k: 'Hidden size', v: s.hiddenSize.toLocaleString('en-US') },
      { k: 'MLP size', v: s.intermediateSize.toLocaleString('en-US') },
      { k: 'Vocabulary', v: s.vocabSize.toLocaleString('en-US') },
      { k: 'Context', v: s.contextLength.toLocaleString('en-US') },
      {
        k: 'Parameters',
        v: typeof s.parameters === 'number' ? compact(s.parameters) : s.parameters,
      },
      { k: 'Tied embeddings', v: s.tiedEmbeddings ? 'yes' : 'no' },
      {
        k: 'LoRA layers',
        v: s.loraLayers.length ? `${Math.min(...s.loraLayers)}–${Math.max(...s.loraLayers)}` : '—',
      },
      { k: 'LoRA modules', v: s.loraModules.join(', ') || '—' },
      { k: 'Source', v: s.source === 'artifact' ? 'architecture.json' : '/api/v1/status' },
    ];
  });
  protected readonly specColumns: Column[] = [
    { key: 'k', label: 'Property' },
    { key: 'v', label: 'Value' },
  ];

  protected readonly layerRows = computed<Row[]>(() => {
    const f = this.frame();
    if (!f) return [];
    const max = Math.max(...f.layers.map((l) => l.norm), 0);
    const lens = new Map((f.logitLens ?? []).map((l) => [l.layer, l.top]));
    return f.layers.map((l) => ({
      layer: l.layer,
      norm: l.norm.toFixed(2),
      rel: max > 0 ? (l.norm / max).toFixed(3) : '—',
      lens:
        lens
          .get(l.layer)
          ?.map((t) => `${visibleToken(t.token)} ${(t.p * 100).toFixed(1)}%`)
          .join(' · ') ?? '',
    }));
  });
  protected readonly layerColumns: Column[] = [
    { key: 'layer', label: 'Layer', numeric: true },
    { key: 'norm', label: 'Residual ‖h‖₂', numeric: true },
    { key: 'rel', label: 'Normalised', numeric: true },
    { key: 'lens', label: 'Logit lens top-3' },
  ];

  protected readonly topRows = computed<Row[]>(() =>
    (this.frame()?.topK ?? []).map((t, i) => ({
      rank: i + 1,
      token: visibleToken(t.token),
      p: `${(t.p * 100).toFixed(2)}%`,
    })),
  );
  protected readonly topColumns: Column[] = [
    { key: 'rank', label: '#', numeric: true },
    { key: 'token', label: 'Token' },
    { key: 'p', label: 'Probability', numeric: true },
  ];

  constructor() {
    effect(() => {
      this.telemetry.count();
      untracked(() => this.canvas()?.invalidate());
    });
  }

  protected onHover(event: HoverEvent): void {
    const hit = event.hit as LayerHit | null;
    const spec = this.spec();
    if (!hit || !spec) {
      this.hover.set(null);
      return;
    }
    const lora = spec.loraLayers.includes(hit.layer);
    const kind = spec.layerKinds[hit.layer];
    const frame = this.frame();
    const norm = frame?.layers.find((l) => l.layer === hit.layer)?.norm;
    this.hover.set({
      x: event.x,
      y: event.y,
      text: [
        `layer ${hit.layer}${kind && kind !== 'full' ? ` · ${kind} attention` : ''}`,
        `${spec.heads} heads · ${spec.kvHeads} KV · MLP ${spec.intermediateSize.toLocaleString('en-US')}`,
        lora ? `LoRA-adapted · ${spec.loraModules.length} projections` : 'frozen base weights',
        norm !== undefined ? `last residual norm ${norm.toFixed(2)}` : 'no telemetry yet',
      ],
    });
  }
}
