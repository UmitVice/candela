import type { ElementRef } from '@angular/core';
import {
  Component,
  DestroyRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';

@Component({
  selector: 'cd-canvas-spark',
  template: `<canvas #canvas aria-hidden="true"></canvas>`,
  styles: `
    :host {
      display: block;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
    }
  `,
})
export class CanvasSpark {
  readonly values = input.required<readonly number[]>();
  readonly fill = input(false);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private mounted = false;

  constructor() {
    let observer: ResizeObserver | undefined;
    afterNextRender(() => {
      this.mounted = true;
      observer = new ResizeObserver(() => this.draw());
      observer.observe(this.canvas().nativeElement);
      this.draw();
    });
    inject(DestroyRef).onDestroy(() => observer?.disconnect());
    effect(() => {
      this.values();
      this.draw();
    });
  }

  private draw(): void {
    if (!this.mounted) return;
    const el = this.canvas().nativeElement;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = el.clientWidth;
    const height = el.clientHeight;
    if (!width || !height) return;
    if (el.width !== Math.round(width * ratio) || el.height !== Math.round(height * ratio)) {
      el.width = Math.round(width * ratio);
      el.height = Math.round(height * ratio);
    }
    const ctx = el.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const v = this.values();
    if (v.length < 2) return;
    let min = Infinity;
    let max = -Infinity;
    for (const x of v) {
      if (x < min) min = x;
      if (x > max) max = x;
    }
    const span = max - min || 1;
    const css = getComputedStyle(document.documentElement);
    const up = (v[v.length - 1] ?? 0) >= (v[0] ?? 0);
    const color =
      css.getPropertyValue(up ? '--up' : '--down').trim() || (up ? '#2ebd85' : '#f6465d');
    const pad = 1.5;
    ctx.beginPath();
    v.forEach((y, i) => {
      const px = (i / (v.length - 1)) * width;
      const py = pad + (1 - (y - min) / span) * (height - pad * 2);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = color;
    ctx.lineJoin = 'round';
    ctx.stroke();
    if (this.fill()) {
      ctx.lineTo(width, height);
      ctx.lineTo(0, height);
      ctx.closePath();
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, `${color}40`);
      gradient.addColorStop(1, `${color}00`);
      ctx.fillStyle = gradient;
      ctx.fill();
    }
  }
}
