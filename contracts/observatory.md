# Observatory artifacts contract

The Observatory (3D design view in `apps/web`) visualizes real data produced by the ML pipeline in `ml/`. The pipeline exports JSON into `apps/web/public/observatory/` (the only path under `apps/web` that `ml/` tooling writes to). Files are static, versioned with the site, each < 2 MB, minified. Curves are downsampled to ≤ 2 000 points.

```
apps/web/public/observatory/
  manifest.json
  galaxy.json
  models/<modelId>/architecture.json
  models/<modelId>/training.json
  models/<modelId>/lora-deltas.json
  models/<modelId>/eval.json
```

```ts
interface ObservatoryManifest {
  generatedAt: string;
  current: string;                         // modelId shown by default
  models: Array<{
    id: string;                            // 'candela-8b-v0.1'
    displayName: string; version: string; tier: 'pro' | 'lite';
    baseModel: string; releasedAt?: string;
    status: 'training' | 'evaluated' | 'released';
    files: { architecture: string; training: string; loraDeltas: string; eval?: string };  // relative paths
    huggingFace?: { adapter?: string; gguf?: string };                                      // repo ids
  }>;
  galaxy?: string;
}

interface Architecture {
  modelId: string; baseModel: string; family: string;
  layers: number; hiddenSize: number; intermediateSize: number;
  attentionHeads: number; kvHeads: number; headDim: number;
  vocabSize: number; contextLength: number; parameters: number; tiedEmbeddings: boolean;
  lora: { rank: number; scale: number; dropout: number; layerIndices: number[]; modules: string[]; trainableParameters: number };
}

interface TrainingRun {
  modelId: string; runId: string; status: 'running' | 'paused' | 'completed' | 'failed';
  startedAt: string; finishedAt?: string;
  hardware: { device: string; memoryLimitGb: number };
  config: { iters: number; batchSize: number; gradAccumulation: number; learningRate: number; schedule: string;
            maxSeqLength: number; datasetVersion: string; trainExamples: number; validExamples: number };
  train: Array<{ step: number; loss: number; lr: number; tokensPerSec: number; peakMemGb: number; elapsedSec: number }>;
  valid: Array<{ step: number; loss: number }>;
  checkpoints: number[];                   // steps that have an entry in lora-deltas.json
  pauses: Array<{ step: number; reason: string; at: string }>;   // resource-guard pauses
}

interface LoraDeltas {
  modelId: string;
  modules: string[];                       // e.g. ['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']
  layers: number;
  checkpoints: Array<{ step: number; maxNorm: number; norms: number[][] }>;   // norms[layer][module] = ‖scale·B·A‖_F, 0 if not adapted
}

interface EvalReport {
  modelId: string; baseModel: string; evaluatedAt: string; datasetVersion: string;
  suites: Array<{ id: string; name: string; metric: string; higherIsBetter: boolean; n: number; base: number; tuned: number; delta: number }>;
  samples?: Array<{ suite: string; prompt: string; base: string; tuned: string }>;   // ≤ 10 curated side-by-sides
}

interface EmbeddingGalaxy {
  modelId: string; method: 'pca' | 'umap'; source: 'hidden_state_mean' | 'embedding_model'; generatedAt: string;
  sectors: Array<{ id: string; name: string; color: string }>;
  points: Array<{ symbol: string; name: string; sector: string; x: number; y: number; z: number; marketCapB?: number }>;
}
```

Live data complements the static files: `telemetry` events in the chat stream (see `contracts/api.md`) drive the per-token animation of the architecture view.
