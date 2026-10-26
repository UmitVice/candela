import {
  Component,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  input,
  output,
  untracked,
  ViewEncapsulation,
} from '@angular/core';
import { LayoutService } from '../../shell/layout.service';
import { ObservatoryUi } from '../observatory-ui.service';
import type { SceneModule } from './stage';
import { Stage } from './stage';

export interface HoverEvent {
  hit: unknown;
  x: number;
  y: number;
}

@Component({
  selector: 'cd-scene-canvas',
  template: '',
  encapsulation: ViewEncapsulation.None,
  styles: `
    cd-scene-canvas {
      position: absolute;
      inset: 0;
      display: block;
      overflow: hidden;
    }
    cd-scene-canvas .obs-label {
      padding: 1px 5px;
      border-radius: 3px;
      background: rgb(5 7 10 / 0.55);
      color: var(--fg-0);
      font-family: var(--font-mono);
      font-size: 11px;
      line-height: 1.4;
      white-space: nowrap;
      pointer-events: none;
      user-select: none;
    }
    cd-scene-canvas .obs-label-dim {
      background: transparent;
      color: var(--fg-2);
      font-size: 10.5px;
    }
    cd-scene-canvas .obs-label-amber {
      color: var(--accent);
      background: transparent;
      font-size: 10.5px;
    }
    cd-scene-canvas .obs-label-cyan {
      color: var(--info);
      background: transparent;
      font-size: 10.5px;
    }
    cd-scene-canvas .obs-label-token {
      color: #ffe2a8;
      border: 1px solid rgb(245 165 36 / 0.35);
    }
    cd-scene-canvas .obs-label-token div {
      font-variant-numeric: tabular-nums;
    }
    cd-scene-canvas .obs-top-title {
      color: var(--fg-2);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    cd-scene-canvas .obs-label-lens {
      color: var(--fg-1);
      border-left: 2px solid var(--info);
      border-radius: 0 3px 3px 0;
    }
    cd-scene-canvas .obs-label-axis {
      background: transparent;
      color: var(--fg-1);
      font-size: 10.5px;
    }
    cd-scene-canvas .obs-label-focus {
      color: var(--fg-0);
      border: 1px solid var(--line-strong);
      background: rgb(12 16 21 / 0.85);
    }
  `,
})
export class SceneCanvas {
  readonly module = input.required<SceneModule | null>();
  readonly autoRotate = input(true);
  readonly hovered = output<HoverEvent>();
  readonly picked = output<unknown>();

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly layout = inject(LayoutService);
  private readonly ui = inject(ObservatoryUi);
  private stage: Stage | null = null;

  constructor() {
    effect(() => {
      const module = this.module();
      untracked(() => {
        this.stage?.dispose();
        this.stage = null;
        if (!module) return;
        this.stage = new Stage(this.host, module, {
          reducedMotion: this.layout.reducedMotion,
          mobile: this.layout.isMobile(),
          onStats: (stats) => this.ui.stats.set(stats),
          onHover: (hit, x, y) => this.hovered.emit({ hit, x, y }),
          onClick: (hit) => this.picked.emit(hit),
        });
        this.stage.setAutoRotate(this.autoRotate());
      });
    });
    effect(() => {
      const rotate = this.autoRotate();
      untracked(() => this.stage?.setAutoRotate(rotate));
    });
    inject(DestroyRef).onDestroy(() => {
      this.stage?.dispose();
      this.stage = null;
      this.ui.stats.set(null);
    });
  }

  invalidate(): void {
    this.stage?.invalidate();
  }
}
