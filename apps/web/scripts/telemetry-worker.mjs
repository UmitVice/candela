// Dev-only stand-in for the MLX worker that streams contract-shaped telemetry frames
// (residual norm per layer, top-5, logit lens) so the Observatory can be exercised end to end
// before the real worker exists. Every frame is synthetic and the model registers as such.
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const url = process.env.CANDELA_WORKER_URL ?? 'ws://127.0.0.1:8719/api/v1/worker/connect';
const token = process.env.CANDELA_WORKER_TOKEN;
const delayMs = Number(process.env.TELEMETRY_DELAY_MS ?? 70);
if (!token) {
  console.error('CANDELA_WORKER_TOKEN is not set');
  process.exit(1);
}

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'observatory');
const manifest = JSON.parse(await readFile(join(root, 'manifest.json'), 'utf8'));
const entry = manifest.models.find((m) => m.id === manifest.current) ?? manifest.models[0];
const arch = JSON.parse(await readFile(join(root, entry.files.architecture), 'utf8'));

const model = {
  id: 'candela-dev-telemetry',
  displayName: 'Dev telemetry worker (synthetic)',
  tier: 'pro',
  version: 'dev',
  baseModel: arch.baseModel,
  runtime: 'mlx',
  host: 'local-gpu-worker',
  quantization: 'none',
  contextLength: 8192,
  supportsReasoning: true,
  supportsTools: false,
  supportsTelemetry: true,
  architecture: {
    layers: arch.layers,
    hiddenSize: arch.hiddenSize,
    attentionHeads: arch.attentionHeads,
    kvHeads: arch.kvHeads,
    vocabSize: arch.vocabSize,
    parameters: `${(arch.parameters / 1e9).toFixed(1)}B`,
  },
};

const REASONING =
  'The user is asking about the market. I should explain that this worker is synthetic and only exercises the telemetry path. ';
const ANSWER =
  'This answer comes from the synthetic dev telemetry worker. Every token you see drives a pulse through the Architecture Tower, with residual norms, a top-5 distribution and logit-lens labels shaped exactly like the real Candela Pro frames. ';
const FILLER = [
  'the',
  ',',
  ' of',
  ' and',
  ' to',
  ' a',
  ' in',
  '.',
  ' is',
  ' market',
  ' price',
  ' rate',
];

let seed = 7;
const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const gauss = () => Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(2 * Math.PI * rand());

let entropy = 1.4;
function frame(step, tok, phase) {
  entropy = Math.min(4.2, Math.max(0.15, entropy + gauss() * 0.45));
  const confidence = Math.exp(-entropy * 0.55);
  const topK = [{ token: tok, p: confidence }];
  let rest = 1 - confidence;
  for (let i = 0; i < 4; i++) {
    const p = rest * (0.35 + rand() * 0.25);
    rest -= p;
    topK.push({ token: FILLER[Math.floor(rand() * FILLER.length)], p });
  }
  topK.sort((a, b) => b.p - a.p);
  const L = arch.layers;
  const layers = Array.from({ length: L }, (_, l) => {
    const depth = l / (L - 1);
    const norm =
      6 + 140 * depth ** 1.7 + (l === L - 1 ? 260 : 0) + Math.abs(gauss()) * (4 + 18 * depth);
    return { layer: l, norm: Math.round(norm * 100) / 100 };
  });
  const lensLayers = [Math.round(L * 0.25), Math.round(L * 0.5), Math.round(L * 0.75), L - 1];
  const logitLens = lensLayers.map((layer) => {
    const depth = layer / (L - 1);
    const p = Math.min(0.97, confidence * depth ** 2 + rand() * 0.05);
    const top = [{ token: depth > 0.6 ? tok : FILLER[Math.floor(rand() * FILLER.length)], p }];
    top.push({ token: FILLER[Math.floor(rand() * FILLER.length)], p: (1 - p) * 0.4 });
    top.push({ token: FILLER[Math.floor(rand() * FILLER.length)], p: (1 - p) * 0.2 });
    return { layer, top };
  });
  return {
    step,
    token: tok,
    phase,
    entropy: Math.round(entropy * 1000) / 1000,
    topK,
    layers,
    logitLens,
  };
}

const words = (text) => text.split(/(?<= )/);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function connect() {
  const ws = new WebSocket(url, {
    protocols: ['candela.worker.v1'],
    headers: { Authorization: `Bearer ${token}` },
  });
  const jobs = new Map();
  const send = (v) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(v));

  ws.onopen = () =>
    send({
      type: 'hello',
      protocol: 'candela.worker.v1',
      workerId: 'dev-telemetry',
      version: '0.0.0-dev',
      device: 'synthetic',
      maxConcurrency: 1,
      models: [model],
    });

  ws.onmessage = async (msg) => {
    let m;
    try {
      m = JSON.parse(String(msg.data));
    } catch {
      return;
    }
    if (m.type === 'welcome') console.log('registered', model.id);
    else if (m.type === 'ping') send({ type: 'pong', ts: m.ts });
    else if (m.type === 'cancel') jobs.get(m.jobId)?.abort();
    else if (m.type === 'job') {
      const controller = new AbortController();
      jobs.set(m.jobId, controller);
      try {
        await runJob(m, controller.signal, send);
      } finally {
        jobs.delete(m.jobId);
      }
    }
  };

  ws.onclose = () => {
    for (const c of jobs.values()) c.abort();
    console.log('disconnected; reconnecting in 2 s');
    setTimeout(connect, 2000);
  };
  ws.onerror = () => {};
}

async function runJob(m, signal, send) {
  let seq = 0;
  const emit = (event, data) => send({ type: 'event', jobId: m.jobId, seq: ++seq, event, data });
  send({ type: 'status', state: 'busy', loadedModelId: model.id, memoryMb: 64 });
  const start = Date.now();
  let first = 0;
  let step = 0;
  const stream = async (event, text) => {
    for (const w of words(text)) {
      await sleep(delayMs);
      if (signal.aborted) return false;
      if (!first) first = Date.now();
      emit(event, { delta: w });
      if (m.params?.telemetry)
        emit('telemetry', frame(step, w, event === 'reasoning' ? 'reasoning' : 'answer'));
      step++;
    }
    return true;
  };
  const ok =
    (!m.params?.reasoning || (await stream('reasoning', REASONING))) &&
    (await stream('token', ANSWER));
  if (!ok) emit('done', { finishReason: 'cancelled' });
  else {
    const totalMs = Date.now() - start;
    emit('usage', {
      promptTokens: 120,
      completionTokens: step,
      reasoningTokens: m.params?.reasoning ? words(REASONING).length : 0,
      timeToFirstTokenMs: first - start,
      tokensPerSecond: step / (totalMs / 1000),
      totalMs,
    });
    emit('done', { finishReason: 'stop' });
  }
  send({ type: 'status', state: 'idle', loadedModelId: model.id, memoryMb: 64 });
}

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
connect();
