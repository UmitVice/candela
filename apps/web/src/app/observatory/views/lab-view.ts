import { Component, computed, inject } from '@angular/core';
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
import type { EvalSuite } from '../data/artifacts';
import { ObservatoryDataService } from '../data/observatory-data.service';
import { ObservatoryUi } from '../observatory-ui.service';
import type { Column, Row } from '../ui/data-table';
import { DataTable } from '../ui/data-table';
import { compact, shortDate, signed } from '../ui/format';

function better(s: EvalSuite): boolean {
  return s.higherIsBetter ? s.tuned > s.base : s.tuned < s.base;
}

@Component({
  selector: 'cd-lab-view',
  imports: [ObsChart, DataTable],
  templateUrl: './lab-view.html',
  styleUrls: ['./views.css', './lab-view.css'],
})
export class LabView {
  protected readonly data = inject(ObservatoryDataService);
  protected readonly ui = inject(ObservatoryUi);
  private readonly t = chartTheme();

  protected readonly run = computed(() =>
    this.data.training.hasValue() ? this.data.training.value() : null,
  );
  protected readonly report = computed(() =>
    this.data.evalReport.hasValue() ? this.data.evalReport.value() : null,
  );
  protected readonly arch = computed(() =>
    this.data.architecture.hasValue() ? this.data.architecture.value() : null,
  );
  protected readonly model = this.data.proModel;
  protected readonly shortDate = shortDate;
  protected readonly compact = compact;
  protected readonly signed = signed;
  protected readonly better = better;

  protected readonly duration = computed(() => {
    const r = this.run();
    const last = r?.train.at(-1);
    if (!last) return '—';
    const h = Math.floor(last.elapsedSec / 3600);
    const m = Math.round((last.elapsedSec % 3600) / 60);
    return h ? `${h} h ${m} min` : `${m} min`;
  });

  protected readonly lossOption = computed<EChartsCoreOption | null>(() => {
    const r = this.run();
    if (!r) return null;
    const t = this.t;
    return {
      grid: GRID,
      tooltip: tooltipBase(t),
      legend: { ...legendBase(t), data: ['train', 'validation'] },
      xAxis: {
        type: 'value',
        name: 'step',
        min: 0,
        max: r.config.iters,
        ...axisBase(t),
        splitLine: { show: false },
      },
      yAxis: { type: 'value', name: 'loss', scale: true, ...axisBase(t) },
      series: [
        {
          name: 'train',
          type: 'line',
          showSymbol: false,
          data: r.train.map((p) => [p.step, p.loss]),
          lineStyle: { color: t.accent, width: 1.5 },
          itemStyle: { color: t.accent },
          markLine: pauseMarks(t, r.pauses, (p) => p.step),
        },
        {
          name: 'validation',
          type: 'line',
          symbolSize: 6,
          data: r.valid.map((p) => [p.step, p.loss]),
          lineStyle: { color: t.info, width: 1.5 },
          itemStyle: { color: t.info },
        },
      ],
    };
  });

  protected readonly lrOption = computed<EChartsCoreOption | null>(() => {
    const r = this.run();
    if (!r) return null;
    const t = this.t;
    return {
      grid: { ...GRID, left: 56 },
      tooltip: { ...tooltipBase(t), valueFormatter: (v: number) => v.toExponential(2) },
      xAxis: {
        type: 'value',
        name: 'step',
        min: 0,
        max: r.config.iters,
        ...axisBase(t),
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        name: 'lr',
        ...axisBase(t),
        axisLabel: { ...axisBase(t).axisLabel, formatter: (v: number) => v.toExponential(0) },
      },
      series: [
        {
          name: 'learning rate',
          type: 'line',
          showSymbol: false,
          data: r.train.map((p) => [p.step, p.lr]),
          lineStyle: { color: t.reason, width: 1.5 },
          itemStyle: { color: t.reason },
          areaStyle: { color: withAlpha(t.reason, 0.08) },
        },
      ],
    };
  });

  protected readonly systemOption = computed<EChartsCoreOption | null>(() => {
    const r = this.run();
    if (!r) return null;
    const t = this.t;
    return {
      grid: { ...GRID, right: 48 },
      tooltip: tooltipBase(t),
      legend: { ...legendBase(t), data: ['tokens/s', 'peak memory'] },
      xAxis: {
        type: 'value',
        name: 'step',
        min: 0,
        max: r.config.iters,
        ...axisBase(t),
        splitLine: { show: false },
      },
      yAxis: [
        { type: 'value', name: 'tok/s', scale: true, ...axisBase(t) },
        {
          type: 'value',
          name: 'GB',
          min: 0,
          max: Math.ceil(
            Math.max(r.hardware.memoryLimitGb, ...r.train.map((p) => p.peakMemGb)) + 1,
          ),
          ...axisBase(t),
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'tokens/s',
          type: 'line',
          showSymbol: false,
          data: r.train.map((p) => [p.step, p.tokensPerSec]),
          lineStyle: { color: t.tool, width: 1.5 },
          itemStyle: { color: t.tool },
          markLine: pauseMarks(t, r.pauses, (p) => p.step),
        },
        {
          name: 'peak memory',
          type: 'line',
          yAxisIndex: 1,
          step: 'end',
          showSymbol: false,
          data: r.train.map((p) => [p.step, p.peakMemGb]),
          lineStyle: { color: t.accent, width: 1.2 },
          itemStyle: { color: t.accent },
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { color: t.down, type: 'dotted' },
            label: {
              color: t.down,
              fontFamily: t.mono,
              fontSize: 10,
              formatter: 'guard limit {c} GB',
            },
            data: [{ yAxis: r.hardware.memoryLimitGb }],
          },
        },
      ],
    };
  });

  protected readonly suites = computed(() =>
    (this.report()?.suites ?? []).filter((s) => s.metric !== 'loss'),
  );
  protected readonly lossSuites = computed(() =>
    (this.report()?.suites ?? []).filter((s) => s.metric === 'loss'),
  );

  protected readonly evalOption = computed<EChartsCoreOption | null>(() => {
    const suites = this.suites();
    if (!suites.length) return null;
    const t = this.t;
    const names = suites.map((s) => s.name);
    return {
      grid: { left: 150, right: 56, top: 24, bottom: 24 },
      tooltip: { ...tooltipBase(t), trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { ...legendBase(t), data: ['base', 'tuned'] },
      xAxis: { type: 'value', min: 0, max: 1, ...axisBase(t) },
      yAxis: {
        type: 'category',
        data: names,
        inverse: true,
        ...axisBase(t),
        splitLine: { show: false },
      },
      series: [
        {
          name: 'base',
          type: 'bar',
          barGap: '15%',
          data: suites.map((s) => s.base),
          itemStyle: { color: withAlpha(t.fg2, 0.7) },
        },
        {
          name: 'tuned',
          type: 'bar',
          data: suites.map((s) => ({
            value: s.tuned,
            itemStyle: { color: better(s) ? t.accent : t.down },
          })),
          label: {
            show: true,
            position: 'right',
            fontFamily: t.mono,
            fontSize: 10,
            formatter: (p: { dataIndex: number }) => {
              const s = suites[p.dataIndex];
              return s ? `${better(s) ? '▲' : '▼'} ${signed(s.delta)}` : '';
            },
            color: t.fg1,
          },
        },
      ],
    };
  });

  protected readonly trainColumns: Column[] = [
    { key: 'step', label: 'Step', numeric: true },
    { key: 'loss', label: 'Loss', numeric: true },
    { key: 'lr', label: 'LR', numeric: true },
    { key: 'tps', label: 'Tokens/s', numeric: true },
    { key: 'mem', label: 'Peak GB', numeric: true },
    { key: 'elapsed', label: 'Elapsed s', numeric: true },
  ];
  protected readonly trainRows = computed<Row[]>(() =>
    (this.run()?.train ?? []).map((p) => ({
      step: p.step,
      loss: p.loss.toFixed(4),
      lr: p.lr.toExponential(2),
      tps: p.tokensPerSec.toFixed(1),
      mem: p.peakMemGb.toFixed(2),
      elapsed: p.elapsedSec.toFixed(0),
    })),
  );
  protected readonly validColumns: Column[] = [
    { key: 'step', label: 'Step', numeric: true },
    { key: 'loss', label: 'Validation loss', numeric: true },
  ];
  protected readonly validRows = computed<Row[]>(() =>
    (this.run()?.valid ?? []).map((p) => ({ step: p.step, loss: p.loss.toFixed(4) })),
  );
  protected readonly pauseColumns: Column[] = [
    { key: 'step', label: 'Step', numeric: true },
    { key: 'reason', label: 'Reason' },
    { key: 'at', label: 'At (UTC)' },
  ];
  protected readonly pauseRows = computed<Row[]>(() =>
    (this.run()?.pauses ?? []).map((p) => ({
      step: p.step,
      reason: p.reason,
      at: shortDate(p.at),
    })),
  );
  protected readonly evalColumns: Column[] = [
    { key: 'name', label: 'Suite' },
    { key: 'metric', label: 'Metric' },
    { key: 'n', label: 'n', numeric: true },
    { key: 'base', label: 'Base', numeric: true },
    { key: 'tuned', label: 'Tuned', numeric: true },
    { key: 'delta', label: 'Δ', numeric: true },
  ];
  protected readonly evalRows = computed<Row[]>(() =>
    (this.report()?.suites ?? []).map((s) => ({
      name: s.name,
      metric: `${s.metric}${s.higherIsBetter ? ' ↑' : ' ↓'}`,
      n: s.n,
      base: s.base.toFixed(4),
      tuned: s.tuned.toFixed(4),
      delta: `${better(s) ? '▲' : '▼'} ${signed(s.delta, 4)}`,
    })),
  );
}
