import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  AdditiveBlending,
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  CylinderGeometry,
  EdgesGeometry,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Points,
  RingGeometry,
  Scene,
  ShaderMaterial,
  TorusGeometry,
  Vector3,
} from 'three';
import type { TelemetryFrame } from '../../core/api/types';
import type { TowerSpec } from '../data/observatory-data.service';
import { label, setLabel } from '../engine/labels';
import { PALETTE, flameRamp, kvGroupColor } from '../engine/palette';
import type { PickContext, SceneModule } from '../engine/stage';

export interface TelemetrySource {
  readonly total: number;
  frameAt(index: number): TelemetryFrame | undefined;
}

export interface LayerHit {
  kind: 'layer';
  layer: number;
}

const SLAB = 6;
const RING = 2.25;
const PULSE_SECONDS = 0.75;
const MAX_PULSES = 10;
const BARS = 5;
const FLAME_PARTICLES = 700;

interface Pulse {
  mesh: Mesh;
  started: number;
  norms: Float32Array;
  active: boolean;
}

const FLAME_VERTEX = /* glsl */ `
  attribute vec3 seed;
  uniform float uTime;
  uniform float uEntropy;
  uniform float uIntensity;
  uniform float uPixelRatio;
  varying float vLife;
  void main() {
    float speed = 0.35 + seed.z * 0.4;
    float life = fract(seed.y + uTime * speed);
    float turbulence = 0.25 + uEntropy * 0.9;
    float swirl = seed.x * 6.2831 + uTime * (0.6 + uEntropy);
    float radius = (1.0 - life) * 0.9 * (0.4 + seed.z) ;
    vec3 p = vec3(cos(swirl) * radius, life * (1.6 + uEntropy * 1.4), sin(swirl) * radius);
    p.x += sin(uTime * 3.1 + seed.y * 17.0) * turbulence * life * 0.45;
    p.z += cos(uTime * 2.7 + seed.x * 13.0) * turbulence * life * 0.45;
    vLife = life;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = (1.0 - life) * 22.0 * uIntensity * uPixelRatio / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;

const FLAME_FRAGMENT = /* glsl */ `
  varying float vLife;
  uniform float uIntensity;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    vec3 hot = vec3(1.0, 0.88, 0.62);
    vec3 warm = vec3(1.0, 0.55, 0.14);
    vec3 cool = vec3(0.85, 0.25, 0.08);
    vec3 color = mix(mix(hot, warm, smoothstep(0.0, 0.45, vLife)), cool, smoothstep(0.45, 1.0, vLife));
    float alpha = (1.0 - d * 2.0) * (1.0 - vLife) * 0.75 * uIntensity;
    gl_FragColor = vec4(color * alpha, alpha);
  }
`;

export class TowerScene implements SceneModule {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(38, 1, 0.1, 400);

  private readonly root = new Group();
  private readonly layerCount: number;
  private readonly spacing: number;
  private readonly height: number;
  private readonly slabs: InstancedMesh;
  private readonly heads: InstancedMesh;
  private readonly cores: InstancedMesh;
  private readonly edges: LineSegments;
  private readonly edgeBase: Float32Array;
  private readonly headBase: Color[] = [];
  private readonly glow: Float32Array;
  private readonly glowTarget: Float32Array;
  private readonly lastNorm: Float32Array;
  private readonly pulses: Pulse[] = [];
  private readonly bars: Mesh[] = [];
  private readonly topRows: HTMLElement[] = [];
  private topLabel!: CSS2DObject;
  private readonly barValue = new Float32Array(BARS);
  private readonly barTarget = new Float32Array(BARS);
  private readonly lensLabels = new Map<number, CSS2DObject>();
  private readonly flameMaterial: ShaderMaterial;
  private entropy = 0;
  private entropyTarget = 0;
  private consumed: number;
  private time = 0;
  private lastFrameAt = -Infinity;
  private readonly tmpColor = new Color();
  private readonly amber = new Color(PALETTE.amber);
  private readonly slabColor = new Color(PALETTE.slab);
  private readonly coreColor = new Color('#5a3a10');

  constructor(
    private readonly spec: TowerSpec,
    private readonly telemetry: TelemetrySource,
    private readonly reducedMotion: boolean,
  ) {
    const n = Math.max(1, spec.layers);
    this.layerCount = n;
    this.height = Math.min(18, Math.max(8, n * 0.375));
    this.spacing = this.height / n;
    this.glow = new Float32Array(n);
    this.glowTarget = new Float32Array(n);
    this.lastNorm = new Float32Array(n);
    this.consumed = telemetry.total;
    this.scene.add(this.root);

    this.camera.position.set(23, this.height * 0.5 + 15, 23);

    this.slabs = this.buildSlabs();
    this.edges = this.buildEdges();
    this.edgeBase = Float32Array.from(this.edges.geometry.getAttribute('color').array);
    this.cores = this.buildCores();
    this.heads = this.buildHeads();
    this.buildSpine();
    this.buildBase();
    this.buildCrown();
    this.flameMaterial = this.buildFlame();
    this.buildPulses();
    this.buildLayerLabels();

    const last = telemetry.frameAt(telemetry.total - 1);
    if (last) this.applyFrame(last, false);
    this.applyColors();
  }

  configureControls(controls: OrbitControls): void {
    controls.target.set(0, this.height * 0.5, 0);
    controls.minDistance = 8;
    controls.maxDistance = 70;
    controls.maxPolarAngle = Math.PI * 0.92;
    controls.autoRotate = true;
    controls.update();
  }

  private layerY(index: number): number {
    return (index + 0.5) * this.spacing;
  }

  private buildSlabs(): InstancedMesh {
    const geometry = new BoxGeometry(SLAB, Math.min(0.08, this.spacing * 0.3), SLAB);
    const material = new MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.1,
      depthWrite: false,
      blending: AdditiveBlending,
    });
    const mesh = new InstancedMesh(geometry, material, this.layerCount);
    const m = new Matrix4();
    for (let i = 0; i < this.layerCount; i++) {
      mesh.setMatrixAt(i, m.makeTranslation(0, this.layerY(i), 0));
      mesh.setColorAt(i, this.slabColor);
    }
    this.root.add(mesh);
    return mesh;
  }

  private buildEdges(): LineSegments {
    const box = new EdgesGeometry(new BoxGeometry(SLAB, Math.min(0.08, this.spacing * 0.3), SLAB));
    const unit = box.getAttribute('position').array as Float32Array;
    const perSlab = unit.length / 3;
    const positions = new Float32Array(unit.length * this.layerCount);
    const colors = new Float32Array(unit.length * this.layerCount);
    const lora = new Set(this.spec.loraLayers);
    const c = new Color();
    for (let l = 0; l < this.layerCount; l++) {
      const y = this.layerY(l);
      const kind = this.spec.layerKinds[l] ?? 'full';
      if (lora.has(l)) c.set(PALETTE.amber).multiplyScalar(0.55);
      else if (kind === 'global') c.set(PALETTE.cyan).multiplyScalar(0.6);
      else c.set(PALETTE.cyan).multiplyScalar(kind === 'local' ? 0.2 : 0.28);
      for (let v = 0; v < perSlab; v++) {
        const o = (l * perSlab + v) * 3;
        positions[o] = unit[v * 3] ?? 0;
        positions[o + 1] = (unit[v * 3 + 1] ?? 0) + y;
        positions[o + 2] = unit[v * 3 + 2] ?? 0;
        colors[o] = c.r;
        colors[o + 1] = c.g;
        colors[o + 2] = c.b;
      }
    }
    box.dispose();
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new BufferAttribute(positions, 3));
    geometry.setAttribute('color', new BufferAttribute(colors, 3));
    const lines = new LineSegments(
      geometry,
      new LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }),
    );
    this.root.add(lines);
    return lines;
  }

  private buildCores(): InstancedMesh {
    const ratio = this.spec.intermediateSize / Math.max(1, this.spec.hiddenSize);
    const radius = Math.min(1.2, 0.28 * Math.sqrt(ratio));
    const geometry = new CylinderGeometry(radius, radius, this.spacing * 0.45, 24, 1, true);
    const material = new MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
      blending: AdditiveBlending,
    });
    const mesh = new InstancedMesh(geometry, material, this.layerCount);
    const m = new Matrix4();
    for (let i = 0; i < this.layerCount; i++) {
      mesh.setMatrixAt(i, m.makeTranslation(0, this.layerY(i), 0));
      mesh.setColorAt(i, this.coreColor);
    }
    this.root.add(mesh);
    return mesh;
  }

  private buildHeads(): InstancedMesh {
    const heads = Math.max(1, this.spec.heads);
    const groups = Math.max(1, Math.min(heads, this.spec.kvHeads));
    const perGroup = Math.ceil(heads / groups);
    const gap = groups > 1 ? 0.18 : 0;
    const step = (Math.PI * 2 - gap * groups) / heads;
    const size = Math.min(0.14, Math.max(0.05, this.spacing * 0.22));
    const geometry = new IcosahedronGeometry(size, 1);
    const material = new MeshBasicMaterial({ color: 0xffffff });
    const mesh = new InstancedMesh(geometry, material, this.layerCount * heads);
    const m = new Matrix4();
    const colors: Color[] = [];
    for (let h = 0; h < heads; h++) {
      const group = Math.floor(h / perGroup);
      colors.push(kvGroupColor(group, groups, new Color()));
    }
    for (let l = 0; l < this.layerCount; l++) {
      for (let h = 0; h < heads; h++) {
        const group = Math.floor(h / perGroup);
        const angle = h * step + group * gap;
        const i = l * heads + h;
        mesh.setMatrixAt(
          i,
          m.makeTranslation(Math.cos(angle) * RING, this.layerY(l), Math.sin(angle) * RING),
        );
        const c = colors[h] ?? new Color();
        this.headBase[i] = c;
        mesh.setColorAt(i, c);
      }
    }
    this.root.add(mesh);
    return mesh;
  }

  private buildSpine(): void {
    const geometry = new BufferGeometry().setFromPoints([
      new Vector3(0, -0.6, 0),
      new Vector3(0, this.height + 0.9, 0),
    ]);
    this.root.add(
      new LineSegments(
        geometry,
        new LineBasicMaterial({ color: PALETTE.cyan, transparent: true, opacity: 0.35 }),
      ),
    );
  }

  private buildBase(): void {
    const size = SLAB * 1.5;
    const lines: Vector3[] = [];
    const cells = 12;
    for (let i = 0; i <= cells; i++) {
      const t = -size / 2 + (size / cells) * i;
      lines.push(new Vector3(t, -0.6, -size / 2), new Vector3(t, -0.6, size / 2));
      lines.push(new Vector3(-size / 2, -0.6, t), new Vector3(size / 2, -0.6, t));
    }
    const grid = new LineSegments(
      new BufferGeometry().setFromPoints(lines),
      new LineBasicMaterial({ color: PALETTE.cyan, transparent: true, opacity: 0.12 }),
    );
    this.root.add(grid);
    const text = `token embeddings · ${this.spec.vocabSize.toLocaleString('en-US')} × ${this.spec.hiddenSize.toLocaleString('en-US')}`;
    const tag = label(text, 'obs-label obs-label-dim');
    tag.position.set(0, -1.3, size / 2);
    this.root.add(tag);
  }

  private buildCrown(): void {
    const y = this.height + 0.9;
    const ring = new Mesh(
      new TorusGeometry(2.6, 0.035, 8, 96),
      new MeshBasicMaterial({ color: PALETTE.amber, transparent: true, opacity: 0.85 }),
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = y;
    this.root.add(ring);

    const barGeometry = new BoxGeometry(0.42, 1, 0.42);
    barGeometry.translate(0, 0.5, 0);
    for (let i = 0; i < BARS; i++) {
      const bar = new Mesh(
        barGeometry,
        new MeshBasicMaterial({
          color: flameRamp(0.9 - i * 0.15),
          transparent: true,
          opacity: 0.92,
        }),
      );
      bar.position.set(-1.8 + i * 0.9, y, 0);
      bar.scale.y = 0.001;
      this.root.add(bar);
      this.bars.push(bar);
    }
    this.topLabel = label('', 'obs-label obs-label-token', 'left');
    const title = document.createElement('div');
    title.className = 'obs-top-title';
    title.textContent = 'next token · top-5';
    this.topLabel.element.replaceChildren(title);
    for (let i = 0; i < BARS; i++) {
      const row = document.createElement('div');
      this.topLabel.element.appendChild(row);
      this.topRows.push(row);
    }
    this.topLabel.position.set(SLAB / 2 + 0.9, y + 1.6, -SLAB / 2 - 0.9);
    this.topLabel.visible = false;
    this.root.add(this.topLabel);
    const tied = this.spec.tiedEmbeddings ? ' · tied embeddings' : '';
    const crown = label(`LM head${tied}`, 'obs-label obs-label-dim');
    crown.position.set(0, y - 0.45, 2.8);
    this.root.add(crown);
  }

  private buildFlame(): ShaderMaterial {
    const seeds = new Float32Array(FLAME_PARTICLES * 3);
    let s = 1234567;
    const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < seeds.length; i++) seeds[i] = rand();
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new BufferAttribute(new Float32Array(FLAME_PARTICLES * 3), 3),
    );
    geometry.setAttribute('seed', new BufferAttribute(seeds, 3));
    const material = new ShaderMaterial({
      vertexShader: FLAME_VERTEX,
      fragmentShader: FLAME_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uEntropy: { value: 0 },
        uIntensity: { value: 0.45 },
        uPixelRatio: { value: Math.min(2, window.devicePixelRatio || 1) * 10 },
      },
      transparent: true,
      depthWrite: false,
      blending: AdditiveBlending,
    });
    const points = new Points(geometry, material);
    points.frustumCulled = false;
    points.position.y = this.height + 1.1;
    this.root.add(points);
    return material;
  }

  private buildPulses(): void {
    const geometry = new RingGeometry(0.2, 0.55, 48);
    geometry.rotateX(-Math.PI / 2);
    for (let i = 0; i < MAX_PULSES; i++) {
      const mesh = new Mesh(
        geometry,
        new MeshBasicMaterial({
          color: PALETTE.ember,
          transparent: true,
          opacity: 0,
          depthWrite: false,
          blending: AdditiveBlending,
        }),
      );
      mesh.visible = false;
      this.root.add(mesh);
      this.pulses.push({
        mesh,
        started: 0,
        norms: new Float32Array(this.layerCount),
        active: false,
      });
    }
  }

  private buildLayerLabels(): void {
    const every = this.layerCount > 24 ? 8 : this.layerCount > 12 ? 4 : 2;
    for (let l = 0; l < this.layerCount; l += every) {
      const tag = label(`L${l}`, 'obs-label obs-label-dim', 'right');
      tag.position.set(-SLAB / 2 - 0.9, this.layerY(l), SLAB / 2 + 0.9);
      this.root.add(tag);
    }
    const lora = this.spec.loraLayers;
    if (lora.length) {
      const lo = Math.min(...lora);
      const hi = Math.max(...lora);
      const tag = label(
        `LoRA · layers ${lo}–${hi} · ${this.spec.loraModules.length} projections`,
        'obs-label obs-label-amber',
        'right',
      );
      const mid = Math.round((lo + hi) / 2) + 2;
      tag.position.set(-SLAB / 2 - 0.9, this.layerY(Math.min(hi, mid)), SLAB / 2 + 0.9);
      this.root.add(tag);
    }
    const globals = this.spec.layerKinds
      .map((k, i) => (k === 'global' ? i : -1))
      .filter((i) => i >= 0);
    for (const g of globals) {
      const tag = label(`L${g} global attention`, 'obs-label obs-label-cyan', 'right');
      tag.position.set(-SLAB / 2 - 0.9, this.layerY(g), SLAB / 2 + 0.9);
      this.root.add(tag);
    }
  }

  private mapLayer(frameLayer: number, frameLayers: number): number {
    if (frameLayers === this.layerCount || frameLayers <= 1) return frameLayer;
    return Math.round((frameLayer / (frameLayers - 1)) * (this.layerCount - 1));
  }

  private applyFrame(frame: TelemetryFrame, animate: boolean): void {
    let max = 0;
    for (const l of frame.layers) max = Math.max(max, l.norm);
    const norms = new Float32Array(this.layerCount);
    const frameLayers = frame.layers.length;
    for (const l of frame.layers) {
      const idx = this.mapLayer(l.layer, frameLayers);
      if (idx < 0 || idx >= this.layerCount) continue;
      norms[idx] = max > 0 ? l.norm / max : 0;
      this.lastNorm[idx] = l.norm;
    }
    for (let i = 0; i < BARS; i++) {
      const entry = frame.topK[i];
      this.barTarget[i] = entry ? Math.max(0, Math.min(1, entry.p)) : 0;
      const row = this.topRows[i];
      const text = entry
        ? `${i + 1}  ${visibleToken(entry.token)}  ${(entry.p * 100).toFixed(1)}%`
        : '';
      if (row && row.textContent !== text) row.textContent = text;
    }
    this.topLabel.visible = frame.topK.length > 0;
    this.entropyTarget = Math.min(1.5, frame.entropy / 4);
    this.updateLens(frame);
    this.lastFrameAt = this.time;
    if (animate && !this.reducedMotion) {
      const pulse = this.pulses.find((p) => !p.active) ?? this.pulses[0];
      if (pulse) {
        pulse.active = true;
        pulse.started = this.time;
        pulse.norms.set(norms);
        pulse.mesh.visible = true;
      }
    } else {
      this.glowTarget.set(norms);
      this.glow.set(norms);
      this.barValue.set(this.barTarget);
      this.entropy = this.entropyTarget;
    }
  }

  private updateLens(frame: TelemetryFrame): void {
    const seen = new Set<number>();
    for (const lens of frame.logitLens ?? []) {
      const idx = this.mapLayer(lens.layer, frame.layers.length || this.layerCount);
      if (idx < 0 || idx >= this.layerCount) continue;
      seen.add(idx);
      let tag = this.lensLabels.get(idx);
      if (!tag) {
        tag = label('', 'obs-label obs-label-lens', 'left');
        tag.position.set(SLAB / 2 + 0.9, this.layerY(idx), -SLAB / 2 - 0.9);
        this.root.add(tag);
        this.lensLabels.set(idx, tag);
      }
      tag.visible = true;
      const tops = lens.top
        .slice(0, 3)
        .map((t) => `${visibleToken(t.token)} ${(t.p * 100).toFixed(0)}%`)
        .join('  ');
      setLabel(tag, `L${lens.layer} ▸ ${tops}`);
    }
    for (const [idx, tag] of this.lensLabels) if (!seen.has(idx)) tag.visible = false;
  }

  update(dt: number, elapsed: number): boolean {
    this.time = elapsed;
    while (this.consumed < this.telemetry.total) {
      const frame = this.telemetry.frameAt(this.consumed);
      this.consumed++;
      if (frame && this.consumed >= this.telemetry.total - MAX_PULSES) this.applyFrame(frame, true);
    }
    let busy = false;
    for (const pulse of this.pulses) {
      if (!pulse.active) continue;
      busy = true;
      const progress = (this.time - pulse.started) / PULSE_SECONDS;
      const y = -0.6 + progress * (this.height + 1.5);
      pulse.mesh.position.y = y;
      (pulse.mesh.material as MeshBasicMaterial).opacity =
        0.8 * (1 - Math.max(0, progress - 0.85) / 0.15);
      const reached = Math.floor(y / this.spacing - 0.5);
      for (let l = 0; l <= Math.min(reached, this.layerCount - 1); l++) {
        if (pulse.norms[l] !== -1) {
          this.glowTarget[l] = pulse.norms[l] ?? 0;
          pulse.norms[l] = -1;
        }
      }
      if (progress >= 1) {
        pulse.active = false;
        pulse.mesh.visible = false;
      }
    }
    const k = this.reducedMotion ? 1 : 1 - Math.exp(-dt * 7);
    const decay = this.reducedMotion ? 0 : 1 - Math.exp(-dt * 0.9);
    const idle = this.time - this.lastFrameAt > 2.5;
    for (let l = 0; l < this.layerCount; l++) {
      const ambient = this.reducedMotion
        ? 0.04
        : 0.04 + 0.02 * Math.max(0, Math.sin(this.time * 0.7 - l * 0.18));
      if (idle) this.glowTarget[l] = (this.glowTarget[l] ?? 0) * (1 - decay);
      const target = Math.max(ambient, this.glowTarget[l] ?? 0);
      this.glow[l] = (this.glow[l] ?? 0) + (target - (this.glow[l] ?? 0)) * k;
    }
    for (let i = 0; i < BARS; i++) {
      this.barValue[i] =
        (this.barValue[i] ?? 0) + ((this.barTarget[i] ?? 0) - (this.barValue[i] ?? 0)) * k;
      const bar = this.bars[i];
      if (bar) bar.scale.y = Math.max(0.001, (this.barValue[i] ?? 0) * 3.2);
    }
    this.entropy += (this.entropyTarget - this.entropy) * k;
    this.flameMaterial.uniforms['uTime']!.value = this.reducedMotion ? 0 : elapsed;
    this.flameMaterial.uniforms['uEntropy']!.value = this.entropy;
    this.flameMaterial.uniforms['uIntensity']!.value = 0.35 + Math.min(1, this.entropy) * 0.5;
    this.applyColors();
    return !this.reducedMotion || busy;
  }

  private applyColors(): void {
    const heads = Math.max(1, this.spec.heads);
    const edgeColors = this.edges.geometry.getAttribute('color') as BufferAttribute;
    const arr = edgeColors.array as Float32Array;
    const perSlab = arr.length / 3 / this.layerCount;
    for (let l = 0; l < this.layerCount; l++) {
      const g = this.glow[l] ?? 0;
      this.slabs.setColorAt(l, this.tmpColor.copy(this.slabColor).lerp(this.amber, g * 0.85));
      this.cores.setColorAt(
        l,
        this.tmpColor.copy(this.coreColor).lerp(this.amber, Math.min(1, g * 1.4)),
      );
      for (let h = 0; h < heads; h++) {
        const i = l * heads + h;
        const base = this.headBase[i];
        if (base) this.heads.setColorAt(i, this.tmpColor.copy(base).multiplyScalar(0.45 + g * 1.1));
      }
      for (let v = 0; v < perSlab; v++) {
        const o = (l * perSlab + v) * 3;
        arr[o] = (this.edgeBase[o] ?? 0) + g * 0.9;
        arr[o + 1] = (this.edgeBase[o + 1] ?? 0) + g * 0.55;
        arr[o + 2] = (this.edgeBase[o + 2] ?? 0) + g * 0.12;
      }
    }
    edgeColors.needsUpdate = true;
    if (this.slabs.instanceColor) this.slabs.instanceColor.needsUpdate = true;
    if (this.cores.instanceColor) this.cores.instanceColor.needsUpdate = true;
    if (this.heads.instanceColor) this.heads.instanceColor.needsUpdate = true;
  }

  pick({ raycaster }: PickContext): LayerHit | null {
    const hit = raycaster.intersectObject(this.slabs, false)[0];
    if (hit?.instanceId === undefined) return null;
    return { kind: 'layer', layer: hit.instanceId };
  }

  layerNorm(layer: number): number {
    return this.lastNorm[layer] ?? 0;
  }

  dispose(): void {
    this.lensLabels.clear();
  }
}

export function visibleToken(token: string): string {
  const t = token.replace(/\n/g, '⏎').replace(/\t/g, '⇥');
  if (!t.trim()) return `␣${t.length > 1 ? `×${t.length}` : ''}`;
  return t.length > 14 ? `${t.slice(0, 13)}…` : t;
}
