import { Color } from 'three';

export const PALETTE = {
  space: '#05070a',
  amber: '#f5a524',
  flame: '#ff6a2b',
  ember: '#ffd27a',
  cyan: '#38bdf8',
  teal: '#2dd4bf',
  violet: '#a78bfa',
  dim: '#1d2633',
  slab: '#16212e',
};

const RAMP = [
  { t: 0, c: new Color('#3a2408') },
  { t: 0.35, c: new Color('#b8650f') },
  { t: 0.65, c: new Color('#f5a524') },
  { t: 0.85, c: new Color('#ff6a2b') },
  { t: 1, c: new Color('#ffe2a8') },
];

export function flameRamp(t: number, target = new Color()): Color {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < RAMP.length; i++) {
    const a = RAMP[i - 1];
    const b = RAMP[i];
    if (a && b && x <= b.t) return target.lerpColors(a.c, b.c, (x - a.t) / (b.t - a.t));
  }
  return target.copy(RAMP[RAMP.length - 1]?.c ?? new Color('#ffffff'));
}

export function flameRampCss(t: number): string {
  return `#${flameRamp(t).getHexString()}`;
}

// KV groups get neighbouring hues between cyan and violet so clusters read as related but distinct.
export function kvGroupColor(group: number, groups: number, target = new Color()): Color {
  const span = groups <= 1 ? 0 : group / (groups - 1);
  return target.setHSL((190 + span * 80) / 360, 0.7, 0.62);
}
