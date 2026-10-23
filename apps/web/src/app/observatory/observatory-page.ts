import { Component, computed, resource } from '@angular/core';
import { RouterLink } from '@angular/router';

interface ManifestSummary {
  current?: string;
  models?: { id: string; status: string; displayName: string }[];
}

const MODULES = [
  {
    name: 'Architecture Tower',
    detail: 'Every decoder layer as a slab; residual norms pulse per generated token.',
  },
  {
    name: 'Fine-tune Field',
    detail: 'LoRA update norms per layer and projection, scrubbed across checkpoints.',
  },
  {
    name: 'Embedding Galaxy',
    detail: 'US equities placed by how the model represents them, coloured by sector.',
  },
  {
    name: 'Lab HUD',
    detail: 'Training loss, resource-guard pauses and base-vs-tuned evaluation deltas.',
  },
];

@Component({
  selector: 'cd-observatory-page',
  imports: [RouterLink],
  templateUrl: './observatory-page.html',
  styleUrl: './observatory-page.css',
})
export class ObservatoryPage {
  protected readonly modules = MODULES;
  protected readonly layers = Array.from({ length: 14 }, (_, i) => i);
  protected readonly stars = Array.from({ length: 42 }, (_, i) => {
    const a = i * 2.399963;
    const r = 30 + ((i * 37) % 100);
    return {
      x: 200 + Math.cos(a) * r * 1.6,
      y: 170 + Math.sin(a) * r * 0.55,
      d: (i % 7) * 0.4,
      s: 0.6 + (i % 3) * 0.5,
    };
  });

  protected readonly manifest = resource({
    loader: async ({ abortSignal }) => {
      const response = await fetch('/observatory/manifest.json', {
        signal: abortSignal,
        cache: 'no-cache',
      });
      if (!response.ok || !response.headers.get('content-type')?.includes('json')) return null;
      return (await response.json()) as ManifestSummary;
    },
  });

  protected readonly staged = computed(() => {
    const m = this.manifest.hasValue() ? this.manifest.value() : null;
    return m?.models?.length ?? 0;
  });
}
