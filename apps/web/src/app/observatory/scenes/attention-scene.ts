import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  DataTexture,
  DoubleSide,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  NearestFilter,
  PerspectiveCamera,
  PlaneGeometry,
  RGBAFormat,
  SRGBColorSpace,
  Scene,
} from 'three';
import { decodeHead, heatColor } from '../data/attention';
import type { SparkAttention } from '../data/artifacts';
import { label } from '../engine/labels';
import { PALETTE } from '../engine/palette';
import type { PickContext, SceneModule } from '../engine/stage';
import { fitSphere } from '../engine/stage';

export interface HeadHit {
  kind: 'head';
  layer: number;
  head: number;
}

const TILE = 1.6;
const GAP = 0.3;
const LAYER_GAP = 1.15;

export class AttentionScene implements SceneModule {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(42, 1, 0.1, 300);

  private readonly root = new Group();
  private radius = 1;
  private readonly tiles: Mesh[] = [];
  private readonly outline: LineSegments[] = [];
  private selected: Mesh | null = null;
  private dirty = true;

  constructor(attention: SparkAttention, sentence: number) {
    const s = attention.sentences[sentence];
    const T = s?.tokens.length ?? 0;
    const heads = attention.heads;
    const width = heads * TILE + (heads - 1) * GAP;
    const geometry = new PlaneGeometry(TILE, TILE);
    geometry.rotateX(-Math.PI / 2);
    const edges = new EdgesGeometry(geometry);

    for (let l = 0; l < attention.layers; l++) {
      const global = attention.layerTypes[l] === 'global';
      for (let h = 0; h < heads; h++) {
        const b64 = s?.layers[l]?.[h] ?? '';
        const values = b64 ? decodeHead(b64, T) : new Float32Array(0);
        const pixels = new Uint8Array(Math.max(1, T * T) * 4);
        for (let i = 0; i < T; i++) {
          for (let j = 0; j < T; j++) {
            // Texture rows run bottom-up; flip so query 0 sits at the far edge like the 2D view.
            const o = ((T - 1 - i) * T + j) * 4;
            if (j > i) {
              pixels.set([6, 9, 13, 255], o);
              continue;
            }
            const [r, g, b] = heatColor(values[i * T + j] ?? 0);
            pixels.set([r, g, b, 255], o);
          }
        }
        const texture = new DataTexture(pixels, Math.max(1, T), Math.max(1, T), RGBAFormat);
        texture.magFilter = NearestFilter;
        texture.minFilter = NearestFilter;
        texture.colorSpace = SRGBColorSpace;
        texture.needsUpdate = true;
        const tile = new Mesh(
          geometry,
          new MeshBasicMaterial({
            map: texture,
            side: DoubleSide,
            transparent: true,
            opacity: 0.92,
          }),
        );
        tile.position.set(-width / 2 + TILE / 2 + h * (TILE + GAP), l * LAYER_GAP, 0);
        tile.userData = { layer: l, head: h };
        this.root.add(tile);
        this.tiles.push(tile);
        const frame = new LineSegments(
          edges,
          new LineBasicMaterial({
            color: global ? PALETTE.cyan : PALETTE.dim,
            transparent: true,
            opacity: global ? 0.9 : 0.6,
          }),
        );
        frame.userData['base'] = global ? PALETTE.cyan : PALETTE.dim;
        frame.position.copy(tile.position);
        frame.position.y += 0.002;
        this.root.add(frame);
        this.outline.push(frame);
      }
      const tag = label(
        `L${l}${global ? ' · global' : ''}`,
        global ? 'obs-label obs-label-cyan' : 'obs-label obs-label-dim',
        'right',
      );
      tag.position.set(-width / 2 - 0.3, l * LAYER_GAP, TILE / 2);
      this.root.add(tag);
    }
    for (let h = 0; h < heads; h++) {
      const tag = label(`head ${h}`, 'obs-label obs-label-dim');
      tag.position.set(-width / 2 + TILE / 2 + h * (TILE + GAP), -0.4, TILE / 2 + 0.3);
      this.root.add(tag);
    }
    this.scene.add(this.root);
    const height = attention.layers * LAYER_GAP;
    this.radius = (Math.hypot(width, height, TILE) / 2) * 0.78;
    this.camera.position.set(width * 0.3, height * 0.9, width * 1.3);
  }

  configureControls(controls: OrbitControls): void {
    controls.target.set(0, (this.tiles.at(-1)?.position.y ?? 0) / 2, 0);
    controls.minDistance = 3;
    controls.maxDistance = 60;
    controls.autoRotate = false;
    controls.update();
  }

  fit(aspect: number, controls: OrbitControls): void {
    fitSphere(this.camera, controls, this.radius, aspect);
  }

  select(layer: number, head: number): void {
    this.selected =
      this.tiles.find((t) => t.userData['layer'] === layer && t.userData['head'] === head) ?? null;
    this.dirty = true;
  }

  update(): boolean {
    if (!this.dirty) return false;
    this.dirty = false;
    this.tiles.forEach((tile, i) => {
      const on = tile === this.selected;
      const line = this.outline[i];
      if (line) {
        (line.material as LineBasicMaterial).color.set(
          on ? PALETTE.amber : (line.userData['base'] as string),
        );
      }
      tile.scale.setScalar(on ? 1.08 : 1);
    });
    return false;
  }

  pick({ raycaster }: PickContext): HeadHit | null {
    const hit = raycaster.intersectObjects(this.tiles, false)[0];
    if (!hit) return null;
    const { layer, head } = hit.object.userData as { layer: number; head: number };
    return { kind: 'head', layer, head };
  }

  dispose(): void {
    for (const tile of this.tiles) (tile.material as MeshBasicMaterial).map?.dispose();
  }
}
