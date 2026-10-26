import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  BoxGeometry,
  BufferGeometry,
  Color,
  Group,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  Vector3,
} from 'three';
import type { LoraDeltas } from '../data/artifacts';
import { label } from '../engine/labels';
import { PALETTE, flameRamp } from '../engine/palette';
import type { PickContext, SceneModule } from '../engine/stage';
import { fitSphere } from '../engine/stage';

export interface CellHit {
  kind: 'cell';
  layer: number;
  module: number;
}

const DX = 1.25;
const DZ = 0.42;
const MAX_H = 4.5;

export class FieldScene implements SceneModule {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(40, 1, 0.1, 400);

  private readonly root = new Group();
  private readonly bars: InstancedMesh;
  private readonly modules: number;
  private readonly layers: number;
  private readonly tau: number;
  private readonly logMax: number;
  private readonly current: Float32Array;
  private readonly target: Float32Array;
  private readonly matrix = new Matrix4();
  private readonly color = new Color();
  private readonly idle = new Color('#1a222d');
  private settled = false;

  constructor(
    private readonly deltas: LoraDeltas,
    private readonly reducedMotion: boolean,
  ) {
    this.modules = deltas.modules.length;
    this.layers = deltas.layers;
    const max = Math.max(1e-6, ...deltas.checkpoints.map((c) => c.maxNorm));
    this.tau = max / 200;
    this.logMax = Math.log1p(max / this.tau);
    this.current = new Float32Array(this.modules * this.layers);
    this.target = new Float32Array(this.modules * this.layers);
    this.scene.add(this.root);

    const depth = this.layers * DZ;
    this.camera.position.set(depth * 0.55, depth * 0.62, depth * 0.95);

    const geometry = new BoxGeometry(DX * 0.72, 1, DZ * 0.72);
    geometry.translate(0, 0.5, 0);
    this.bars = new InstancedMesh(
      geometry,
      new MeshBasicMaterial({ color: 0xffffff }),
      this.modules * this.layers,
    );
    this.bars.frustumCulled = false;
    this.root.add(this.bars);
    this.buildFloor();
    this.buildAxes();
    this.apply();
  }

  configureControls(controls: OrbitControls): void {
    controls.target.set(0, -0.6, 0);
    controls.minDistance = 6;
    controls.maxDistance = 80;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.autoRotate = false;
    controls.update();
  }

  fit(aspect: number, controls: OrbitControls): void {
    const radius = (Math.hypot(this.modules * DX, this.layers * DZ, MAX_H) / 2) * 0.8;
    fitSphere(this.camera, controls, radius, aspect);
  }

  private x(module: number): number {
    return (module - (this.modules - 1) / 2) * DX;
  }

  private z(layer: number): number {
    return (layer - (this.layers - 1) / 2) * DZ;
  }

  height(norm: number): number {
    return norm <= 0 ? 0 : (MAX_H * Math.log1p(norm / this.tau)) / this.logMax;
  }

  // position is a fractional checkpoint index; values between checkpoints are linear blends.
  setPosition(position: number): void {
    const cps = this.deltas.checkpoints;
    const i = Math.max(0, Math.min(cps.length - 1, Math.floor(position)));
    const j = Math.min(cps.length - 1, i + 1);
    const f = Math.max(0, Math.min(1, position - i));
    const a = cps[i]?.norms;
    const b = cps[j]?.norms;
    for (let l = 0; l < this.layers; l++) {
      for (let m = 0; m < this.modules; m++) {
        const va = a?.[l]?.[m] ?? 0;
        const vb = b?.[l]?.[m] ?? 0;
        this.target[l * this.modules + m] = va + (vb - va) * f;
      }
    }
    this.settled = false;
  }

  private buildFloor(): void {
    const w = this.modules * DX;
    const d = this.layers * DZ;
    const pts: Vector3[] = [];
    for (let m = 0; m <= this.modules; m++) {
      const x = -w / 2 + m * DX;
      pts.push(new Vector3(x, 0, -d / 2), new Vector3(x, 0, d / 2));
    }
    for (let l = 0; l <= this.layers; l += 4) {
      const z = -d / 2 + l * DZ;
      pts.push(new Vector3(-w / 2, 0, z), new Vector3(w / 2, 0, z));
    }
    this.root.add(
      new LineSegments(
        new BufferGeometry().setFromPoints(pts),
        new LineBasicMaterial({ color: PALETTE.cyan, transparent: true, opacity: 0.14 }),
      ),
    );
    const axis = [new Vector3(-w / 2, 0, d / 2), new Vector3(-w / 2, MAX_H, d / 2)];
    for (let t = 0; t <= 4; t++) {
      const y = (MAX_H * t) / 4;
      axis.push(new Vector3(-w / 2, y, d / 2), new Vector3(-w / 2 - 0.25, y, d / 2));
    }
    this.root.add(
      new LineSegments(
        new BufferGeometry().setFromPoints(axis),
        new LineBasicMaterial({ color: PALETTE.cyan, transparent: true, opacity: 0.45 }),
      ),
    );
  }

  private buildAxes(): void {
    const d = this.layers * DZ;
    const w = this.modules * DX;
    this.deltas.modules.forEach((name, m) => {
      const tag = label(name, 'obs-label obs-label-axis');
      tag.position.set(this.x(m), 0, d / 2 + 0.9);
      this.root.add(tag);
    });
    const every = this.layers > 24 ? 8 : 4;
    for (let l = 0; l < this.layers; l += every) {
      const tag = label(`L${l}`, 'obs-label obs-label-dim', 'left');
      tag.position.set(w / 2 + 0.4, 0, this.z(l));
      this.root.add(tag);
    }
    const last = label(`L${this.layers - 1}`, 'obs-label obs-label-dim', 'left');
    last.position.set(w / 2 + 0.4, 0, this.z(this.layers - 1));
    this.root.add(last);
    const max = this.tau * Math.expm1(this.logMax);
    for (let t = 1; t <= 4; t++) {
      const y = (MAX_H * t) / 4;
      const value = this.tau * Math.expm1((this.logMax * t) / 4);
      const tag = label(
        value >= 1 ? value.toFixed(2) : value.toPrecision(2),
        'obs-label obs-label-dim',
        'right',
      );
      tag.position.set(-w / 2 - 0.35, y, d / 2);
      this.root.add(tag);
    }
    const title = label(
      `‖scale·B·A‖_F · log scale · max ${max.toFixed(2)}`,
      'obs-label obs-label-amber',
      'left',
    );
    title.position.set(-w / 2, MAX_H + 0.7, d / 2);
    this.root.add(title);
  }

  update(dt: number): boolean {
    if (this.settled) return false;
    const k = this.reducedMotion ? 1 : 1 - Math.exp(-dt * 9);
    let moving = false;
    for (let i = 0; i < this.current.length; i++) {
      const c = this.current[i] ?? 0;
      const t = this.target[i] ?? 0;
      const next = c + (t - c) * k;
      const done = Math.abs(next - t) <= 1e-4 * (1 + t);
      if (!done) moving = true;
      this.current[i] = done ? t : next;
    }
    this.apply();
    this.settled = !moving;
    return moving;
  }

  private apply(): void {
    for (let l = 0; l < this.layers; l++) {
      for (let m = 0; m < this.modules; m++) {
        const i = l * this.modules + m;
        const v = this.current[i] ?? 0;
        const h = this.height(v);
        this.matrix.makeScale(1, Math.max(0.03, h), 1);
        this.matrix.setPosition(this.x(m), 0, this.z(l));
        this.bars.setMatrixAt(i, this.matrix);
        this.bars.setColorAt(
          i,
          v <= 0 ? this.idle : flameRamp(0.1 + (0.8 * h) / MAX_H, this.color).multiplyScalar(0.82),
        );
      }
    }
    this.bars.instanceMatrix.needsUpdate = true;
    if (this.bars.instanceColor) this.bars.instanceColor.needsUpdate = true;
    this.bars.computeBoundingSphere();
  }

  pick({ raycaster }: PickContext): CellHit | null {
    const hit = raycaster.intersectObject(this.bars, false)[0];
    if (hit?.instanceId === undefined) return null;
    return {
      kind: 'cell',
      layer: Math.floor(hit.instanceId / this.modules),
      module: hit.instanceId % this.modules,
    };
  }

  dispose(): void {
    this.bars.dispose();
  }
}
