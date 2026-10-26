import { Injectable, signal } from '@angular/core';
import type { StageStats } from './engine/stage';
import { supportsWebGL2 } from './engine/stage';

@Injectable({ providedIn: 'root' })
export class ObservatoryUi {
  readonly webgl2 = supportsWebGL2();
  readonly dataView = signal(!this.webgl2);
  readonly stats = signal<StageStats | null>(null);
}
