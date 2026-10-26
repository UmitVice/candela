// Spark attention maps: per head, the row-major lower triangle of the T×T matrix as uint8
// (probability × 255), base64-encoded. Row i holds i + 1 values for keys 0..i.
export function decodeHead(b64: string, tokens: number): Float32Array {
  const raw = atob(b64);
  const out = new Float32Array(tokens * tokens);
  let k = 0;
  for (let i = 0; i < tokens; i++) {
    for (let j = 0; j <= i; j++) {
      out[i * tokens + j] = (raw.charCodeAt(k++) || 0) / 255;
    }
  }
  return out;
}

export function heatColor(v: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, v)) ** 0.6;
  if (x < 0.5) {
    const t = x / 0.5;
    return [12 + t * (56 - 12), 18 + t * (189 - 18), 26 + t * (248 - 26)];
  }
  const t = (x - 0.5) / 0.5;
  return [56 + t * (255 - 56), 189 + t * (210 - 189), 248 + t * (122 - 248)];
}
