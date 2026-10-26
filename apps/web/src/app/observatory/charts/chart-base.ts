import type { ChartTheme } from '../../terminal/charts/chart-theme';
import { chartTheme, withAlpha } from '../../terminal/charts/chart-theme';
import type { Pause } from '../data/artifacts';

export { chartTheme, withAlpha };
export type { ChartTheme };

export function axisBase(t: ChartTheme) {
  return {
    axisLine: { lineStyle: { color: t.lineStrong } },
    axisTick: { lineStyle: { color: t.lineStrong } },
    axisLabel: { color: t.fg2, fontFamily: t.mono, fontSize: 10 },
    splitLine: { lineStyle: { color: withAlpha(t.line, 0.8) } },
    nameTextStyle: { color: t.fg2, fontFamily: t.mono, fontSize: 10 },
  };
}

export function tooltipBase(t: ChartTheme) {
  return {
    trigger: 'axis' as const,
    // Rich-text tooltips render on canvas; HTML tooltips would need innerHTML, which Trusted Types blocks.
    renderMode: 'richText' as const,
    backgroundColor: t.bg,
    borderColor: t.lineStrong,
    textStyle: { color: t.fg0, fontFamily: t.mono, fontSize: 11 },
    axisPointer: { lineStyle: { color: t.lineStrong } },
  };
}

export function legendBase(t: ChartTheme) {
  return {
    top: 0,
    right: 0,
    itemWidth: 12,
    itemHeight: 3,
    textStyle: { color: t.fg1, fontFamily: t.mono, fontSize: 10.5 },
    inactiveColor: t.fg2,
  };
}

export const GRID = { left: 48, right: 16, top: 26, bottom: 28, containLabel: false };

// Resource-guard pauses drawn as dashed vertical marks at the step (or x value) where they happened.
export function pauseMarks(t: ChartTheme, pauses: Pause[], x: (p: Pause) => number) {
  return {
    symbol: 'none',
    silent: false,
    lineStyle: { color: t.warn, type: 'dashed' as const, width: 1 },
    label: { show: false },
    tooltip: { show: true, formatter: (p: { data?: { name?: string } }) => p.data?.name ?? '' },
    emphasis: {
      label: {
        show: true,
        formatter: (p: { data?: { name?: string } }) => p.data?.name ?? '',
        color: t.warn,
        fontFamily: t.mono,
        fontSize: 10,
      },
    },
    data: pauses.map((p) => ({ xAxis: x(p), name: `pause @ ${p.step}: ${p.reason}` })),
  };
}
