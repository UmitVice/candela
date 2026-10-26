import { Injectable, computed, inject, resource, signal } from '@angular/core';
import { GatewayService } from '../../core/gateway/gateway.service';
import type {
  Architecture,
  EmbeddingGalaxy,
  EvalReport,
  LoraDeltas,
  ManifestModel,
  ObservatoryManifest,
  SparkArchitecture,
  SparkAttention,
  SparkLiveStatus,
  SparkManifest,
  SparkMilestones,
  SparkTraining,
  TrainingRun,
} from './artifacts';

const ROOT = '/observatory/';
const SPARK_ROOT = '/observatory/spark/';

async function loadJson<T>(url: string, signal: AbortSignal): Promise<T | null> {
  const response = await fetch(url, { signal, cache: 'no-cache', credentials: 'omit' });
  if (!response.ok || !response.headers.get('content-type')?.includes('json')) return null;
  return (await response.json()) as T;
}

function safePath(path: string | undefined): string | undefined {
  if (!path || path.includes('..') || /^[a-z]+:/i.test(path) || path.startsWith('/'))
    return undefined;
  return path;
}

export interface TowerSpec {
  id: string;
  label: string;
  family: string;
  layers: number;
  heads: number;
  kvHeads: number;
  hiddenSize: number;
  intermediateSize: number;
  headDim: number;
  vocabSize: number;
  contextLength: number;
  parameters: number | string;
  tiedEmbeddings: boolean;
  loraLayers: number[];
  loraModules: string[];
  layerKinds: ('local' | 'global' | 'full')[];
  source: 'artifact' | 'gateway';
}

export interface ModelChoice {
  id: string;
  label: string;
  group: 'Candela Pro' | 'Candela Spark';
  status: string;
}

@Injectable({ providedIn: 'root' })
export class ObservatoryDataService {
  private readonly gateway = inject(GatewayService);

  readonly requestedModel = signal<string | null>(null);

  readonly manifest = resource({
    loader: ({ abortSignal }) => loadJson<ObservatoryManifest>(`${ROOT}manifest.json`, abortSignal),
  });

  readonly sparkManifest = resource({
    loader: ({ abortSignal }) => loadJson<SparkManifest>(`${SPARK_ROOT}manifest.json`, abortSignal),
  });

  private readonly manifestValue = computed(() =>
    this.manifest.hasValue() ? this.manifest.value() : null,
  );

  readonly proModels = computed<ManifestModel[]>(() => this.manifestValue()?.models ?? []);

  readonly choices = computed<ModelChoice[]>(() => {
    const pro = this.proModels().map<ModelChoice>((m) => ({
      id: m.id,
      label: `${m.displayName} ${m.version}`,
      group: 'Candela Pro',
      status: m.status,
    }));
    const spark = (this.sparkManifest.hasValue() ? this.sparkManifest.value() : null)?.models ?? [];
    return [
      ...pro,
      ...spark.map<ModelChoice>((m) => ({
        id: m.id,
        label: m.displayName,
        group: 'Candela Spark',
        status: m.status,
      })),
    ];
  });

  readonly proModel = computed<ManifestModel | null>(() => {
    const models = this.proModels();
    const wanted = this.requestedModel();
    return (
      models.find((m) => m.id === wanted) ??
      models.find((m) => m.id === this.manifestValue()?.current) ??
      models[0] ??
      null
    );
  });

  readonly sparkModel = computed(() => {
    const m = this.sparkManifest.hasValue() ? this.sparkManifest.value() : null;
    if (!m) return null;
    const wanted = this.requestedModel();
    return (
      m.models.find((x) => x.id === wanted) ?? m.models.find((x) => x.id === m.current) ?? null
    );
  });

  readonly towerIsSpark = computed(() => {
    const wanted = this.requestedModel();
    return !!wanted && this.sparkModel()?.id === wanted;
  });

  private proFile<K extends keyof ManifestModel['files']>(key: K) {
    return computed(() => safePath(this.proModel()?.files[key]));
  }

  readonly architecture = resource({
    params: this.proFile('architecture'),
    loader: ({ params, abortSignal }) => loadJson<Architecture>(ROOT + params, abortSignal),
  });

  readonly training = resource({
    params: this.proFile('training'),
    loader: ({ params, abortSignal }) => loadJson<TrainingRun>(ROOT + params, abortSignal),
  });

  readonly loraDeltas = resource({
    params: this.proFile('loraDeltas'),
    loader: ({ params, abortSignal }) => loadJson<LoraDeltas>(ROOT + params, abortSignal),
  });

  readonly evalReport = resource({
    params: this.proFile('eval'),
    loader: ({ params, abortSignal }) => loadJson<EvalReport>(ROOT + params, abortSignal),
  });

  readonly galaxy = resource({
    params: computed(() => {
      if (!this.manifest.hasValue() && this.manifest.isLoading()) return undefined;
      return safePath(this.manifestValue()?.galaxy ?? 'galaxy.json');
    }),
    loader: ({ params, abortSignal }) => loadJson<EmbeddingGalaxy>(ROOT + params, abortSignal),
  });

  private sparkFile(key: 'architecture' | 'training' | 'milestones' | 'attention') {
    return computed(() => safePath(this.sparkModel()?.files[key]));
  }

  readonly sparkArchitecture = resource({
    params: this.sparkFile('architecture'),
    loader: ({ params, abortSignal }) =>
      loadJson<SparkArchitecture>(SPARK_ROOT + params, abortSignal),
  });

  readonly sparkTraining = resource({
    params: this.sparkFile('training'),
    loader: ({ params, abortSignal }) => loadJson<SparkTraining>(SPARK_ROOT + params, abortSignal),
  });

  readonly sparkMilestones = resource({
    params: this.sparkFile('milestones'),
    loader: ({ params, abortSignal }) =>
      loadJson<SparkMilestones>(SPARK_ROOT + params, abortSignal),
  });

  readonly sparkAttention = resource({
    params: this.sparkFile('attention'),
    loader: ({ params, abortSignal }) => loadJson<SparkAttention>(SPARK_ROOT + params, abortSignal),
  });

  readonly sparkLive = signal<SparkLiveStatus | null>(null);
  private sparkLiveMissing = false;

  async refreshSparkLive(): Promise<void> {
    const c = this.gateway.connection();
    if (c.mode !== 'live' || c.state !== 'online' || this.sparkLiveMissing) {
      this.sparkLive.set(null);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(`${c.baseUrl}/api/v1/lab/spark`, {
        signal: controller.signal,
        cache: 'no-store',
        credentials: 'omit',
        headers: { accept: 'application/json' },
      });
      if (response.status === 404) this.sparkLiveMissing = true;
      const body = response.ok ? ((await response.json()) as Partial<SparkLiveStatus>) : null;
      this.sparkLive.set(
        body?.schema === 'candela.spark.status.v1' && typeof body.step === 'number'
          ? (body as SparkLiveStatus)
          : null,
      );
    } catch {
      this.sparkLive.set(null);
    } finally {
      clearTimeout(timer);
    }
  }

  readonly tower = computed<TowerSpec | null>(() => {
    if (this.towerIsSpark()) {
      const a = this.sparkArchitecture.hasValue() ? this.sparkArchitecture.value() : null;
      const m = this.sparkModel();
      if (!a || !m) return null;
      return {
        id: a.modelId,
        label: m.displayName,
        family: a.layout,
        layers: a.layers.length,
        heads: a.attentionHeads,
        kvHeads: a.kvHeads,
        hiddenSize: a.hiddenSize,
        intermediateSize: a.intermediateSize,
        headDim: a.headDim,
        vocabSize: a.vocabSize,
        contextLength: a.contextLength,
        parameters: a.parameters.total,
        tiedEmbeddings: a.tiedEmbeddings,
        loraLayers: [],
        loraModules: [],
        layerKinds: a.layers.map((l) => l.attention),
        source: 'artifact',
      };
    }
    const a = this.architecture.hasValue() ? this.architecture.value() : null;
    const m = this.proModel();
    if (a && m) {
      return {
        id: a.modelId,
        label: `${m.displayName} ${m.version}`,
        family: a.family,
        layers: a.layers,
        heads: a.attentionHeads,
        kvHeads: a.kvHeads,
        hiddenSize: a.hiddenSize,
        intermediateSize: a.intermediateSize,
        headDim: a.headDim,
        vocabSize: a.vocabSize,
        contextLength: a.contextLength,
        parameters: a.parameters,
        tiedEmbeddings: a.tiedEmbeddings,
        loraLayers: a.lora.layerIndices,
        loraModules: a.lora.modules,
        layerKinds: Array.from({ length: a.layers }, () => 'full' as const),
        source: 'artifact',
      };
    }
    if (this.architecture.isLoading() || this.manifest.isLoading()) return null;
    const live = this.gateway.status()?.models.find((x) => x.architecture);
    const arch = live?.architecture;
    if (!live || !arch) return null;
    return {
      id: live.id,
      label: `${live.displayName} ${live.version}`,
      family: live.baseModel,
      layers: arch.layers,
      heads: arch.attentionHeads,
      kvHeads: arch.kvHeads,
      hiddenSize: arch.hiddenSize,
      intermediateSize: arch.hiddenSize * 4,
      headDim: Math.round(arch.hiddenSize / Math.max(1, arch.attentionHeads)),
      vocabSize: arch.vocabSize,
      contextLength: live.contextLength,
      parameters: arch.parameters,
      tiedEmbeddings: false,
      loraLayers: [],
      loraModules: [],
      layerKinds: Array.from({ length: arch.layers }, () => 'full' as const),
      source: 'gateway',
    };
  });
}
