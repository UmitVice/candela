import type { ElementRef } from '@angular/core';
import { Component, afterRenderEffect, input, signal, viewChild } from '@angular/core';
import { heatColor } from '../data/attention';
import { visibleToken } from '../scenes/tower-scene';

const LABEL_W = 86;

@Component({
  selector: 'cd-attention-map',
  template: `
    <canvas
      #canvas
      role="img"
      [attr.aria-label]="caption()"
      (pointermove)="onMove($event)"
      (pointerleave)="hover.set(null)"
    ></canvas>
    <p class="readout mono" aria-live="off">
      @if (hover(); as h) {
        query “{{ h.q }}” → key “{{ h.k }}” · {{ (h.p * 100).toFixed(1) }}%
      } @else {
        rows = query token · columns = attended key · hover a cell
      }
    </p>
  `,
  styles: `
    :host {
      display: block;
    }
    canvas {
      display: block;
      width: 100%;
      touch-action: none;
    }
    .readout {
      margin: 6px 0 0;
      color: var(--fg-1);
      font-size: 11.5px;
      min-height: 1.4em;
    }
  `,
})
export class AttentionMap {
  readonly tokens = input.required<string[]>();
  readonly values = input.required<Float32Array>();
  readonly caption = input.required<string>();

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  protected readonly hover = signal<{ q: string; k: string; p: number } | null>(null);
  private cell = 0;

  constructor() {
    afterRenderEffect(() => this.draw());
  }

  private draw(): void {
    const el = this.canvas().nativeElement;
    const tokens = this.tokens();
    const values = this.values();
    const T = tokens.length;
    const width = el.clientWidth || 360;
    this.cell = Math.max(6, Math.floor((width - LABEL_W) / Math.max(1, T)));
    const height = LABEL_W + this.cell * T;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    el.width = Math.round(width * dpr);
    el.height = Math.round(height * dpr);
    el.style.height = `${height}px`;
    const ctx = el.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const style = getComputedStyle(document.documentElement);
    ctx.font = `10px ${style.getPropertyValue('--font-mono') || 'monospace'}`;
    ctx.fillStyle = style.getPropertyValue('--fg-1') || '#aab4c0';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < T; i++) {
      const tok = visibleToken(tokens[i] ?? '').slice(0, 11);
      ctx.textAlign = 'right';
      ctx.fillText(tok, LABEL_W - 6, LABEL_W + i * this.cell + this.cell / 2);
      ctx.save();
      ctx.translate(LABEL_W + i * this.cell + this.cell / 2, LABEL_W - 6);
      ctx.rotate(-Math.PI / 3);
      ctx.textAlign = 'left';
      ctx.fillText(tok, 0, 0);
      ctx.restore();
    }
    for (let i = 0; i < T; i++) {
      for (let j = 0; j < T; j++) {
        if (j > i) ctx.fillStyle = '#06090d';
        else {
          const [r, g, b] = heatColor(values[i * T + j] ?? 0);
          ctx.fillStyle = `rgb(${r | 0} ${g | 0} ${b | 0})`;
        }
        ctx.fillRect(
          LABEL_W + j * this.cell,
          LABEL_W + i * this.cell,
          this.cell - 1,
          this.cell - 1,
        );
      }
    }
  }

  protected onMove(event: PointerEvent): void {
    const rect = this.canvas().nativeElement.getBoundingClientRect();
    const j = Math.floor((event.clientX - rect.left - LABEL_W) / this.cell);
    const i = Math.floor((event.clientY - rect.top - LABEL_W) / this.cell);
    const tokens = this.tokens();
    if (i < 0 || j < 0 || i >= tokens.length || j > i) {
      this.hover.set(null);
      return;
    }
    this.hover.set({
      q: visibleToken(tokens[i] ?? ''),
      k: visibleToken(tokens[j] ?? ''),
      p: this.values()[i * tokens.length + j] ?? 0,
    });
  }
}
