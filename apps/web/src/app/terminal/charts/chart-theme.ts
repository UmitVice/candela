export interface ChartTheme {
  bg: string;
  fg0: string;
  fg1: string;
  fg2: string;
  line: string;
  lineStrong: string;
  up: string;
  down: string;
  accent: string;
  info: string;
  tool: string;
  reason: string;
  warn: string;
  mono: string;
}

export function chartTheme(): ChartTheme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    bg: v('--bg-1', '#0c1015'),
    fg0: v('--fg-0', '#e8edf3'),
    fg1: v('--fg-1', '#aab4c0'),
    fg2: v('--fg-2', '#7a8592'),
    line: v('--line', '#1d2633'),
    lineStrong: v('--line-strong', '#2a3646'),
    up: v('--up', '#2ebd85'),
    down: v('--down', '#f6465d'),
    accent: v('--accent', '#f5a524'),
    info: v('--info', '#38bdf8'),
    tool: v('--tool', '#2dd4bf'),
    reason: v('--reason', '#a78bfa'),
    warn: v('--warn', '#fbbf24'),
    mono: v('--font-mono', 'monospace'),
  };
}

export function withAlpha(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m?.[1]) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export function lightweightBase(theme: ChartTheme, compact: boolean) {
  return {
    autoSize: true,
    layout: {
      background: { color: 'transparent' },
      textColor: theme.fg2,
      fontFamily: theme.mono,
      fontSize: compact ? 10 : 11,
      attributionLogo: true,
      panes: { separatorColor: theme.line, separatorHoverColor: theme.lineStrong },
    },
    grid: {
      vertLines: { color: withAlpha(theme.line, 0.6) },
      horzLines: { color: withAlpha(theme.line, 0.6) },
    },
    rightPriceScale: { borderColor: theme.line },
    timeScale: { borderColor: theme.line, fixLeftEdge: true, fixRightEdge: true },
    crosshair: {
      vertLine: { color: theme.lineStrong, labelBackgroundColor: theme.lineStrong },
      horzLine: { color: theme.lineStrong, labelBackgroundColor: theme.lineStrong },
    },
    handleScroll: { vertTouchDrag: false },
  };
}
