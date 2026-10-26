export interface ObservatoryManifest {
  generatedAt: string;
  current: string;
  models: ManifestModel[];
  galaxy?: string;
}

export interface ManifestModel {
  id: string;
  displayName: string;
  version: string;
  tier: 'pro' | 'lite';
  baseModel: string;
  releasedAt?: string;
  status: 'training' | 'evaluated' | 'released';
  files: { architecture: string; training: string; loraDeltas: string; eval?: string };
  huggingFace?: { adapter?: string; gguf?: string };
}

export interface Architecture {
  modelId: string;
  baseModel: string;
  family: string;
  layers: number;
  hiddenSize: number;
  intermediateSize: number;
  attentionHeads: number;
  kvHeads: number;
  headDim: number;
  vocabSize: number;
  contextLength: number;
  parameters: number;
  tiedEmbeddings: boolean;
  lora: {
    rank: number;
    scale: number;
    dropout: number;
    layerIndices: number[];
    modules: string[];
    trainableParameters: number;
  };
}

export interface TrainPoint {
  step: number;
  loss: number;
  lr: number;
  tokensPerSec: number;
  peakMemGb: number;
  elapsedSec: number;
}

export interface Pause {
  step: number;
  reason: string;
  at: string;
}

export interface TrainingRun {
  modelId: string;
  runId: string;
  status: 'running' | 'paused' | 'completed' | 'failed';
  startedAt: string;
  finishedAt?: string;
  hardware: { device: string; memoryLimitGb: number };
  config: {
    iters: number;
    batchSize: number;
    gradAccumulation: number;
    learningRate: number;
    schedule: string;
    maxSeqLength: number;
    datasetVersion: string;
    trainExamples: number;
    validExamples: number;
  };
  train: TrainPoint[];
  valid: { step: number; loss: number }[];
  checkpoints: number[];
  pauses: Pause[];
}

export interface LoraCheckpoint {
  step: number;
  maxNorm: number;
  norms: number[][];
}

export interface LoraDeltas {
  modelId: string;
  modules: string[];
  layers: number;
  checkpoints: LoraCheckpoint[];
}

export interface EvalSuite {
  id: string;
  name: string;
  metric: string;
  higherIsBetter: boolean;
  n: number;
  base: number;
  tuned: number;
  delta: number;
}

export interface EvalReport {
  modelId: string;
  baseModel: string;
  evaluatedAt: string;
  datasetVersion: string;
  suites: EvalSuite[];
  samples?: { suite: string; prompt: string; base: string; tuned: string }[];
}

export interface GalaxyPoint {
  symbol: string;
  name: string;
  sector: string;
  x: number;
  y: number;
  z: number;
  marketCapB?: number;
}

export interface EmbeddingGalaxy {
  modelId: string;
  method: 'pca' | 'umap';
  source: 'hidden_state_mean' | 'embedding_model';
  generatedAt: string;
  sectors: { id: string; name: string; color: string }[];
  points: GalaxyPoint[];
}

export interface SparkManifest {
  schema: string;
  generatedAt: string;
  current: string;
  models: {
    id: string;
    displayName: string;
    status: string;
    parameters: number;
    files: { architecture: string; training: string; milestones: string; attention: string };
    huggingFace?: string;
  }[];
}

export interface SparkFamilyPreset {
  id: string;
  parameters: number;
  hiddenSize: number;
  layers: number;
  heads: number;
  kvHeads: number;
  trained: boolean;
}

export interface SparkArchitecture {
  modelId: string;
  family: string;
  layout: string;
  layers: {
    index: number;
    attention: 'local' | 'global';
    window: number | null;
    ropeBase: number;
  }[];
  hiddenSize: number;
  intermediateSize: number;
  attentionHeads: number;
  kvHeads: number;
  headDim: number;
  vocabSize: number;
  contextLength: number;
  tiedEmbeddings: boolean;
  parameters: { total: number; embedding: number; non_embedding: number; per_layer: number };
  quantization: {
    bits: number;
    groupSize: number;
    mode: string;
    qatFromStep: number;
    scope: string;
  };
  tokenizer: { type: string; vocabSize: number };
  familyPresets: SparkFamilyPreset[];
}

export interface SparkTrainPoint {
  step: number;
  tokens: number;
  loss: number;
  lr: number;
  tokensPerSec: number;
  peakMemGb: number;
  elapsedSec: number;
}

export interface SparkValidPoint {
  step: number;
  tokens: number;
  bf16: number;
  int4: number;
  gapRel: number;
  perSource?: Record<string, { bf16: number; int4: number }>;
}

export interface SparkRun {
  runId: string;
  train: SparkTrainPoint[];
  valid: SparkValidPoint[];
  pauses: Pause[];
  checkpoints: number[];
}

export interface SparkTraining {
  modelId: string;
  main: SparkRun;
  branches: SparkRun[];
}

export interface SparkMilestone {
  id: string;
  step: number;
  tokens: number;
  evaluatedAt: string;
  validation: { meanBf16: number; meanInt4: number; gapRel: number };
  zeroShot: { id: string; metric: string; n: number; value: number; chance: number }[];
  samples?: { prompt: string; completion: string }[];
  huggingFace?: string;
}

export interface SparkMilestones {
  modelId: string;
  milestones: SparkMilestone[];
}

export interface SparkAttention {
  modelId: string;
  milestone: string;
  encoding: string;
  layers: number;
  heads: number;
  layerTypes: ('local' | 'global')[];
  sentences: { text: string; tokens: string[]; layers: string[][] }[];
}

export interface SparkLiveStatus {
  schema: 'candela.spark.status.v1';
  updatedAt: string;
  state: string;
  runId: string;
  model: string;
  parameters: number;
  phase: string;
  step: number;
  tokens: number;
  pauseReason?: string | null;
  train?: { loss?: number; tokensPerSec?: number; lr?: number; peakMemGb?: number } | null;
  valid?: { bf16?: number; int4?: number; gapRel?: number; step?: number } | null;
  milestones?: unknown[];
  leasePriority?: number;
  startedAt?: string;
}
