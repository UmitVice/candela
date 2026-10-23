import type { ModelInfo, StatusResponse } from '../../../api/types';
import { SNAPSHOT_AS_OF } from './universe';

export const DEMO_PRO_MODEL: ModelInfo = {
  id: 'candela-12b-demo',
  displayName: 'Candela 12B',
  tier: 'pro',
  version: 'v0.1-demo',
  baseModel: 'google/gemma-4-12B-it',
  runtime: 'mlx',
  host: 'local-gpu-worker',
  quantization: '4bit',
  contextLength: 8192,
  supportsReasoning: true,
  supportsTools: true,
  supportsTelemetry: false,
};

export function demoStatus(): StatusResponse {
  return {
    status: 'ok',
    version: 'replay',
    commit: 'demo',
    route: 'worker',
    models: [{ ...DEMO_PRO_MODEL, available: true }],
    workers: [],
    queue: { depth: 0, maxDepth: 8 },
    dataProviders: [
      { id: 'snapshot', status: 'ok', asOf: SNAPSHOT_AS_OF },
      { id: 'baseline-forecast', status: 'ok', asOf: SNAPSHOT_AS_OF },
      { id: 'sec', status: 'degraded', asOf: '2025-10-31' },
      { id: 'live-prices', status: 'disabled' },
      { id: 'vaniras', status: 'disabled' },
    ],
    time: new Date().toISOString(),
  };
}
