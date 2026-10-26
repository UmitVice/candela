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
import type { EChartsCoreOption } from 'echarts/core';
import {
  axisBase,
  chartTheme,
  GRID,
  legendBase,
  pauseMarks,
  tooltipBase,
  withAlpha,
} from '../charts/chart-base';
import { ObsChart } from '../charts/obs-chart';
import { decodeHead } from '../data/attention';
import { ObservatoryDataService } from '../data/observatory-data.service';
import type { HoverEvent } from '../engine/scene-canvas';
import { SceneCanvas } from '../engine/scene-canvas';
import { ObservatoryUi } from '../observatory-ui.service';
import type { HeadHit } from '../scenes/attention-scene';
import { AttentionScene } from '../scenes/attention-scene';
import { AttentionMap } from '../ui/attention-map';
import type { Column, Row } from '../ui/data-table';
import { DataTable } from '../ui/data-table';
import { compact, pct, shortDate } from '../ui/format';

const LIVE_POLL_MS = 30_000;

@Component({
  selector: 'cd-spark-view',
  imports: [ObsChart, DataTable, SceneCanvas, AttentionMap],
  templateUrl: './spark-view.html',
  styleUrls: ['./views.css', './lab-view.css', './spark-view.css'],
})
export class SparkView {
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  private readonly t = chartTheme();
  private readonly canvas = viewChild(SceneCanvas);

  protected readonly compact = compact;
  protected readonly pct = pct;
  protected readonly shortDate = shortDate;

  protected readonly model = this.data.sparkModel;
  protected readonly arch = computed(() =>
    this.data.sparkArchitecture.hasValue() ? this.data.sparkArchitecture.value() : null,
  );
  protected readonly training = computed(() =>
    this.data.sparkTraining.hasValue() ? this.data.sparkTraining.value() : null,
  );
  protected readonly milestones = computed(
    () =>
      (this.data.sparkMilestones.hasValue() ? this.data.sparkMilestones.value() : null)
        ?.milestones ?? [],
  );
  protected readonly attention = computed(() =>
    this.data.sparkAttention.hasValue() ? this.data.sparkAttention.value() : null,
  );
  protected readonly live = this.data.sparkLive;

  protected readonly sentence = signal(0);
  protected readonly layer = signal(0);
  protected readonly head = signal(0);
  protected readonly hoverHead = signal<{ x: number; y: number; text: string } | null>(null);

  protected readonly family = computed(() => {
    const a = this.arch();
    const m = this.model();
    if (!a) return [];
    const released = new Set(this.milestones().map((x) => x.id.replace(/-m\d+$/, '')));
    return a.familyPresets.map((p) => ({
      ...p,
      status:
        p.id === m?.id
          ? released.has(p.id)
            ? `${m.status} · m${this.milestones().length} released`
            : m.status
          : p.trained
            ? 'trained'
            : 'planned',
      active: p.id === m?.id,
      size: 26 + 10 * Math.log10(p.parameters / 3e7 + 1) * 3,
    }));
  });

  protected readonly progress = computed(() => {
    const live = this.live();
    const run = this.training()?.main;
    const lastTrain = run?.train.at(-1);
    const lastValid = run?.valid.at(-1);
    if (live) {
      return {
        source: `live · gateway /api/v1/lab/spark · ${shortDate(live.updatedAt)} UTC`,
        live: true,
        state: live.state + (live.pauseReason ? ` · ${live.pauseReason}` : ''),
        step: live.step,
        tokens: live.tokens,
        loss: live.train?.loss,
        tps: live.train?.tokensPerSec,
        mem: live.train?.peakMemGb,
        bf16: live.valid?.bf16,
        int4: live.valid?.int4,
        gap: live.valid?.gapRel,
        pauses: run?.pauses.length ?? 0,
      };
    }
    return {
      source: `static artifact · exported ${shortDate(this.data.sparkManifest.hasValue() ? this.data.sparkManifest.value()?.generatedAt : undefined)} UTC`,
      live: false,
      state: this.model()?.status ?? '—',
      step: lastTrain?.step,
      tokens: lastTrain?.tokens,
      loss: lastTrain?.loss,
      tps: lastTrain?.tokensPerSec,
      mem: lastTrain?.peakMemGb,
      bf16: lastValid?.bf16,
      int4: lastValid?.int4,
      gap: lastValid?.gapRel,
      pauses: run?.pauses.length ?? 0,
    };
  });

  protected readonly lossOption = computed<EChartsCoreOption | null>(() => {
    const tr = this.training();
    if (!tr) return null;
    const t = this.t;
    const runs = [tr.main, ...tr.branches];
    const colors = [t.accent, t.reason, t.tool];
    return {
      grid: GRID,
      tooltip: { ...tooltipBase(t), valueFormatter: (v: number) => v.toFixed(3) },
      legend: { ...legendBase(t), data: runs.map((r) => r.runId) },
      xAxis: {
        type: 'log',
        name: 'tokens',
        ...axisBase(t),
        axisLabel: { ...axisBase(t).axisLabel, formatter: (v: number) => compact(v) },
        splitLine: { show: false },
      },
      yAxis: { type: 'value', name: 'loss', scale: true, ...axisBase(t) },
      series: runs.map((r, i) => ({
        name: r.runId,
        type: 'line',
        showSymbol: false,
        sampling: 'lttb',
        data: r.train.filter((p) => p.tokens > 0).map((p) => [p.tokens, p.loss]),
        lineStyle: { color: colors[i % colors.length], width: 1.3 },
        itemStyle: { color: colors[i % colors.length] },
      })),
    };
  });

  protected readonly gapOption = computed<EChartsCoreOption | null>(() => {
    const tr = this.training();
    if (!tr) return null;
    const t = this.t;
    const v = tr.main.valid.filter((p) => p.tokens > 0);
    return {
      grid: { ...GRID, right: 48 },
      tooltip: tooltipBase(t),
      legend: { ...legendBase(t), data: ['bf16', 'int4', 'gap'] },
      xAxis: {
        type: 'log',
        name: 'tokens',
        ...axisBase(t),
        axisLabel: { ...axisBase(t).axisLabel, formatter: (x: number) => compact(x) },
        splitLine: { show: false },
      },
      yAxis: [
        { type: 'value', name: 'val loss', scale: true, ...axisBase(t) },
        {
          type: 'value',
          name: 'gap',
          min: 0,
          ...axisBase(t),
          axisLabel: { ...axisBase(t).axisLabel, formatter: (x: number) => pct(x, 1) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'bf16',
          type: 'line',
          symbolSize: 4,
          data: v.map((p) => [p.tokens, p.bf16]),
          lineStyle: { color: t.info, width: 1.3 },
          itemStyle: { color: t.info },
        },
        {
          name: 'int4',
          type: 'line',
          symbolSize: 4,
          data: v.map((p) => [p.tokens, p.int4]),
          lineStyle: { color: t.accent, width: 1.3, type: 'dashed' },
          itemStyle: { color: t.accent },
        },
        {
          name: 'gap',
          type: 'line',
          yAxisIndex: 1,
          symbolSize: 3,
          data: v.map((p) => [p.tokens, p.gapRel]),
          lineStyle: { color: withAlpha(t.down, 0.8), width: 1 },
          itemStyle: { color: t.down },
          areaStyle: { color: withAlpha(t.down, 0.12) },
          tooltip: { valueFormatter: (x: number) => pct(x, 2) },
        },
      ],
    };
  });

  protected readonly throughputOption = computed<EChartsCoreOption | null>(() => {
    const tr = this.training();
    if (!tr) return null;
    const t = this.t;
    const main = tr.main;
    return {
      grid: { ...GRID, left: 56 },
      tooltip: tooltipBase(t),
      xAxis: { type: 'value', name: 'step', ...axisBase(t), splitLine: { show: false } },
      yAxis: {
        type: 'value',
        name: 'tok/s',
        ...axisBase(t),
        axisLabel: { ...axisBase(t).axisLabel, formatter: (x: number) => compact(x) },
      },
      series: [
        {
          name: 'tokens/s',
          type: 'line',
          showSymbol: false,
          sampling: 'lttb',
          data: main.train.map((p) => [p.step, p.tokensPerSec]),
          lineStyle: { color: t.tool, width: 1.2 },
          itemStyle: { color: t.tool },
          markLine: pauseMarks(t, main.pauses, (p) => p.step),
        },
      ],
    };
  });

  protected readonly scalingOption = computed<EChartsCoreOption | null>(() => {
    const tr = this.training();
    const a = this.arch();
    if (!tr || !a) return null;
    const t = this.t;
    const n = a.parameters.non_embedding;
    const flops = (tokens: number) => 6 * n * tokens;
    const valid = tr.main.valid.filter((p) => p.tokens > 0);
    return {
      grid: { ...GRID, left: 52 },
      tooltip: {
        ...tooltipBase(t),
        trigger: 'item',
        formatter: (p: { seriesName: string; value: number[] }) =>
          `${p.seriesName}\n${(p.value[0] ?? 0).toExponential(2)} FLOPs · loss ${(p.value[1] ?? 0).toFixed(3)}`,
      },
      legend: { ...legendBase(t), data: [`${a.modelId} · int4`, 'milestones'] },
      xAxis: {
        type: 'log',
        name: 'compute (FLOPs)',
        ...axisBase(t),
        axisLabel: { ...axisBase(t).axisLabel, formatter: (x: number) => x.toExponential(0) },
      },
      yAxis: { type: 'value', name: 'val loss', scale: true, ...axisBase(t) },
      series: [
        {
          name: `${a.modelId} · int4`,
          type: 'line',
          symbolSize: 4,
          data: valid.map((p) => [flops(p.tokens), p.int4]),
          lineStyle: { color: t.accent, width: 1.3 },
          itemStyle: { color: t.accent },
        },
        {
          name: 'milestones',
          type: 'scatter',
          symbol: 'diamond',
          symbolSize: 11,
          data: this.milestones().map((m) => ({
            value: [flops(m.tokens), m.validation.meanInt4],
            name: m.id,
          })),
          itemStyle: { color: t.up },
        },
      ],
    };
  });

  protected readonly zeroShotColumns: Column[] = [
    { key: 'id', label: 'Benchmark' },
    { key: 'metric', label: 'Metric' },
    { key: 'n', label: 'n', numeric: true },
    { key: 'value', label: 'Score', numeric: true },
    { key: 'chance', label: 'Chance', numeric: true },
  ];
  protected readonly zeroShotRows = computed<Row[]>(() =>
    (this.milestones().at(-1)?.zeroShot ?? []).map((z) => ({
      id: z.id,
      metric: z.metric,
      n: z.n,
      value: pct(z.value),
      chance: pct(z.chance),
    })),
  );
  protected readonly validColumns: Column[] = [
    { key: 'step', label: 'Step', numeric: true },
    { key: 'tokens', label: 'Tokens', numeric: true },
    { key: 'bf16', label: 'bf16 loss', numeric: true },
    { key: 'int4', label: 'int4 loss', numeric: true },
    { key: 'gap', label: 'Gap', numeric: true },
  ];
  protected readonly validRows = computed<Row[]>(() =>
    (this.training()?.main.valid ?? []).map((p) => ({
      step: p.step,
      tokens: compact(p.tokens),
      bf16: p.bf16.toFixed(4),
      int4: p.int4.toFixed(4),
      gap: pct(p.gapRel, 2),
    })),
  );
  protected readonly pauseColumns: Column[] = [
    { key: 'step', label: 'Step', numeric: true },
    { key: 'reason', label: 'Reason' },
    { key: 'at', label: 'At (UTC)' },
  ];
  protected readonly pauseRows = computed<Row[]>(() =>
    (this.training()?.main.pauses ?? []).map((p) => ({
      step: p.step,
      reason: p.reason,
      at: shortDate(p.at),
    })),
  );

  protected readonly attentionModule = computed(() => {
    const a = this.attention();
    const s = this.sentence();
    if (!a || this.ui.dataView() || !this.ui.webgl2) return null;
    return untracked(() => {
      const scene = new AttentionScene(a, s);
      scene.select(this.layer(), this.head());
      return scene;
    });
  });

  protected readonly tokens = computed(
    () => this.attention()?.sentences[this.sentence()]?.tokens ?? [],
  );
  protected readonly drill = computed(() => {
    const a = this.attention();
    const s = a?.sentences[this.sentence()];
    const b64 = s?.layers[this.layer()]?.[this.head()];
    return b64 && s ? decodeHead(b64, s.tokens.length) : new Float32Array(0);
  });
  protected readonly layers = computed(() =>
    Array.from({ length: this.attention()?.layers ?? 0 }, (_, i) => i),
  );
  protected readonly heads = computed(() =>
    Array.from({ length: this.attention()?.heads ?? 0 }, (_, i) => i),
  );

  constructor() {
    effect(() => {
      const scene = this.attentionModule();
      const l = this.layer();
      const h = this.head();
      untracked(() => {
        scene?.select(l, h);
        this.canvas()?.invalidate();
      });
    });

    void this.data.refreshSparkLive();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void this.data.refreshSparkLive();
    }, LIVE_POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected setSentence(value: string): void {
    this.sentence.set(Number(value));
  }

  protected onHeadHover(event: HoverEvent): void {
    const hit = event.hit as HeadHit | null;
    const kind = hit ? this.attention()?.layerTypes[hit.layer] : undefined;
    this.hoverHead.set(
      hit
        ? { x: event.x, y: event.y, text: `layer ${hit.layer} (${kind}) · head ${hit.head}` }
        : null,
    );
  }

  protected onHeadPick(hit: unknown): void {
    const h = hit as HeadHit | null;
    if (!h) return;
    this.layer.set(h.layer);
    this.head.set(h.head);
  }
}
