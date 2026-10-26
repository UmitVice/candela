import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  Group,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  Vector3,
} from 'three';
import type { EmbeddingGalaxy, GalaxyPoint } from '../data/artifacts';
import { label, setLabel } from '../engine/labels';
import type { PickContext, SceneModule } from '../engine/stage';

export interface PointHit {
  kind: 'point';
  index: number;
  point: GalaxyPoint;
}

const RADIUS = 10;
const ALWAYS_LABELLED = 12;

const VERTEX = /* glsl */ `
  attribute float size;
  attribute float emphasis;
  attribute vec3 tint;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vEmphasis;
  void main() {
    vColor = tint;
    vEmphasis = emphasis;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * uPixelRatio * (0.35 + emphasis * 0.65) * 110.0 / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  varying float vEmphasis;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float core = smoothstep(0.5, 0.0, d);
    float alpha = core * (0.18 + vEmphasis * 0.82);
    gl_FragColor = vec4(vColor * (0.55 + core * 0.9) * alpha, alpha);
  }
`;

export class GalaxyScene implements SceneModule {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(50, 1, 0.1, 500);

  private readonly root = new Group();
  private readonly points: Points;
  private readonly emphasis: Float32Array;
  private readonly positions: Float32Array;
  private readonly hoverLabel: CSS2DObject;
  private readonly focusLabel: CSS2DObject;
  private readonly sectorIndex: string[];
  private hidden = new Set<string>();
  private selected = -1;
  private hovered = -1;
  private dirty = true;

  constructor(
    private readonly galaxy: EmbeddingGalaxy,
    pixelRatio: number,
  ) {
    const pts = galaxy.points;
    const n = pts.length;
    this.positions = new Float32Array(n * 3);
    const tints = new Float32Array(n * 3);
    const sizes = new Float32Array(n);
    this.emphasis = new Float32Array(n).fill(1);
    this.sectorIndex = pts.map((p) => p.sector);

    const center = new Vector3();
    for (const p of pts) center.add(new Vector3(p.x, p.y, p.z));
    center.divideScalar(Math.max(1, n));
    let spread = 1e-6;
    for (const p of pts) spread = Math.max(spread, new Vector3(p.x, p.y, p.z).sub(center).length());
    const scale = RADIUS / spread;
    const caps = pts.map((p) => p.marketCapB ?? 0);
    const maxCap = Math.max(1, ...caps);
    const colors = new Map(galaxy.sectors.map((s) => [s.id, new Color(s.color)]));
    const fallback = new Color('#7a8592');

    pts.forEach((p, i) => {
      this.positions[i * 3] = (p.x - center.x) * scale;
      this.positions[i * 3 + 1] = (p.y - center.y) * scale;
      this.positions[i * 3 + 2] = (p.z - center.z) * scale;
      const c = colors.get(p.sector) ?? fallback;
      tints[i * 3] = c.r;
      tints[i * 3 + 1] = c.g;
      tints[i * 3 + 2] = c.b;
      sizes[i] = p.marketCapB ? 0.9 + 3.2 * Math.sqrt(p.marketCapB / maxCap) : 0.8;
    });

    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new BufferAttribute(this.positions, 3));
    geometry.setAttribute('tint', new BufferAttribute(tints, 3));
    geometry.setAttribute('size', new BufferAttribute(sizes, 1));
    geometry.setAttribute('emphasis', new BufferAttribute(this.emphasis, 1));
    geometry.computeBoundingSphere();
    this.points = new Points(
      geometry,
      new ShaderMaterial({
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        uniforms: { uPixelRatio: { value: pixelRatio } },
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
      }),
    );
    this.root.add(this.points);
    this.scene.add(this.root);

    [...pts.keys()]
      .filter((i) => pts[i]?.marketCapB)
      .sort((a, b) => (pts[b]?.marketCapB ?? 0) - (pts[a]?.marketCapB ?? 0))
      .slice(0, ALWAYS_LABELLED)
      .forEach((i) => {
        const tag = label(pts[i]?.symbol ?? '', 'obs-label obs-label-dim', 'left');
        tag.position.fromArray(this.positions, i * 3).add(new Vector3(0.25, 0, 0));
        this.root.add(tag);
      });

    this.hoverLabel = label('', 'obs-label', 'left');
    this.hoverLabel.visible = false;
    this.root.add(this.hoverLabel);
    this.focusLabel = label('', 'obs-label obs-label-focus', 'left');
    this.focusLabel.visible = false;
    this.root.add(this.focusLabel);

    this.camera.position.set(0, RADIUS * 0.55, RADIUS * 1.9);
  }

  configureControls(controls: OrbitControls): void {
    controls.target.set(0, 0, 0);
    controls.minDistance = 3;
    controls.maxDistance = RADIUS * 6;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.25;
    controls.update();
  }

  setHidden(sectors: Set<string>): void {
    this.hidden = sectors;
    this.dirty = true;
  }

  select(index: number): void {
    this.selected = index;
    const p = this.galaxy.points[index];
    this.focusLabel.visible = !!p;
    if (p) {
      setLabel(this.focusLabel, `${p.symbol} · ${p.name}`);
      this.focusLabel.position.fromArray(this.positions, index * 3).add(new Vector3(0.35, 0.35, 0));
    }
    this.dirty = true;
  }

  indexOf(symbol: string): number {
    return this.galaxy.points.findIndex((p) => p.symbol === symbol);
  }

  update(): boolean {
    if (!this.dirty) return false;
    this.dirty = false;
    for (let i = 0; i < this.emphasis.length; i++) {
      const visible = !this.hidden.has(this.sectorIndex[i] ?? '');
      this.emphasis[i] =
        i === this.selected || i === this.hovered
          ? 1.6
          : visible
            ? this.selected >= 0
              ? 0.7
              : 1
            : 0.12;
    }
    this.points.geometry.getAttribute('emphasis').needsUpdate = true;
    return false;
  }

  pick({ raycaster }: PickContext): PointHit | null {
    const distance = this.camera.position.length();
    raycaster.params.Points = { threshold: Math.max(0.12, distance * 0.012) };
    const hits = raycaster.intersectObject(this.points, false);
    const hit = hits.find(
      (h) => h.index !== undefined && !this.hidden.has(this.sectorIndex[h.index] ?? ''),
    );
    const index = hit?.index ?? -1;
    if (index !== this.hovered) {
      this.hovered = index;
      this.dirty = true;
      const p = this.galaxy.points[index];
      this.hoverLabel.visible = !!p && index !== this.selected;
      if (p) {
        setLabel(this.hoverLabel, p.symbol);
        this.hoverLabel.position.fromArray(this.positions, index * 3).add(new Vector3(0.3, 0, 0));
      }
    }
    const point = this.galaxy.points[index];
    return point ? { kind: 'point', index, point } : null;
  }

  dispose(): void {
    this.hidden.clear();
  }
}
