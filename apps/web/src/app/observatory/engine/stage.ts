import {
  BloomEffect,
  EffectComposer,
  EffectPass,
  RenderPass,
  SMAAEffect,
  SMAAPreset,
  VignetteEffect,
} from 'postprocessing';
import type { Object3D, PerspectiveCamera, Material, Mesh, Scene } from 'three';
import {
  Color,
  HalfFloatType,
  NoToneMapping,
  Raycaster,
  SRGBColorSpace,
  Texture,
  Timer,
  Vector2,
  WebGLRenderer,
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export type QualityTier = 'high' | 'medium' | 'low';

export interface PickContext {
  raycaster: Raycaster;
  pointer: Vector2;
}

export interface SceneModule {
  readonly scene: Scene;
  readonly camera: PerspectiveCamera;
  // Returns true while the scene still has motion to show; the stage stops its loop otherwise.
  update(dt: number, elapsed: number): boolean;
  configureControls?(controls: OrbitControls): void;
  // Re-frames the camera for a new aspect ratio until the user moves it.
  fit?(aspect: number, controls: OrbitControls): void;
  pick?(ctx: PickContext): unknown;
  dispose(): void;
}

export interface StageStats {
  fps: number;
  dpr: number;
  tier: QualityTier;
  bloom: number;
}

export interface StageOptions {
  reducedMotion: boolean;
  mobile: boolean;
  onStats?: (stats: StageStats) => void;
  onHover?: (hit: unknown, clientX: number, clientY: number) => void;
  onClick?: (hit: unknown) => void;
}

export function fitSphere(
  camera: PerspectiveCamera,
  controls: OrbitControls,
  radius: number,
  aspect: number,
): void {
  const vHalf = (camera.fov * Math.PI) / 360;
  const hHalf = Math.atan(Math.tan(vHalf) * aspect);
  const distance = radius / Math.sin(Math.min(vHalf, hHalf));
  const offset = camera.position.clone().sub(controls.target).normalize();
  camera.position.copy(controls.target).addScaledVector(offset, distance);
  controls.update();
}

export function supportsWebGL2(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2');
    const ok = !!gl;
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return ok;
  } catch {
    return false;
  }
}

function initialTier(mobile: boolean): QualityTier {
  const cores = navigator.hardwareConcurrency || 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8;
  if (cores <= 4 || memory <= 4) return 'low';
  return mobile ? 'medium' : 'high';
}

export class Stage {
  readonly renderer: WebGLRenderer;
  readonly controls: OrbitControls;
  private readonly composer: EffectComposer;
  private readonly labels: CSS2DRenderer;
  private readonly bloom: BloomEffect;
  private readonly bloomPass: EffectPass;
  private readonly timer = new Timer();
  private readonly raycaster = new Raycaster();
  private readonly pointer = new Vector2();
  private readonly resizeObserver: ResizeObserver;
  private readonly intersection: IntersectionObserver;
  private readonly maxDpr: number;
  private dpr: number;
  private tier: QualityTier;
  private visible = true;
  private running = false;
  private disposed = false;
  private frames = 0;
  private windowStart = 0;
  private slowWindows = 0;
  private hoverPending: PointerEvent | null = null;

  constructor(
    private readonly host: HTMLElement,
    private readonly module: SceneModule,
    private readonly options: StageOptions,
  ) {
    this.tier = initialTier(options.mobile);
    this.maxDpr = Math.min(window.devicePixelRatio || 1, options.mobile ? 1.5 : 2);
    this.dpr = this.tier === 'low' ? Math.min(this.maxDpr, 1.25) : this.maxDpr;

    this.renderer = new WebGLRenderer({
      antialias: false,
      alpha: false,
      stencil: false,
      depth: true,
      powerPreference: 'high-performance',
    });
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = NoToneMapping;
    this.renderer.setClearColor(new Color('#05070a'), 1);
    this.renderer.setPixelRatio(this.dpr);
    const canvas = this.renderer.domElement;
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.touchAction = 'none';
    canvas.setAttribute('aria-hidden', 'true');
    host.appendChild(canvas);

    this.labels = new CSS2DRenderer();
    const labelsEl = this.labels.domElement;
    labelsEl.style.position = 'absolute';
    labelsEl.style.inset = '0';
    labelsEl.style.pointerEvents = 'none';
    labelsEl.classList.add('obs-labels');
    host.appendChild(labelsEl);

    this.composer = new EffectComposer(this.renderer, { frameBufferType: HalfFloatType });
    this.composer.addPass(new RenderPass(module.scene, module.camera));
    this.bloom = new BloomEffect({
      intensity: 1.1,
      luminanceThreshold: 0.32,
      luminanceSmoothing: 0.25,
      mipmapBlur: true,
      radius: 0.62,
      resolutionScale: this.tier === 'low' ? 0.25 : 0.5,
    });
    const vignette = new VignetteEffect({ offset: 0.32, darkness: 0.62 });
    this.bloomPass = new EffectPass(module.camera, this.bloom, vignette);
    this.composer.addPass(this.bloomPass);
    if (this.tier !== 'low') {
      this.composer.addPass(
        new EffectPass(module.camera, new SMAAEffect({ preset: SMAAPreset.MEDIUM })),
      );
    }

    this.controls = new OrbitControls(module.camera, canvas);
    this.controls.enableDamping = !options.reducedMotion;
    this.controls.dampingFactor = 0.08;
    this.controls.autoRotateSpeed = 0.35;
    module.configureControls?.(this.controls);
    if (options.reducedMotion) this.controls.autoRotate = false;
    this.controls.addEventListener('change', this.invalidate);
    this.controls.addEventListener('start', this.onControlStart);
    this.controls.addEventListener('end', this.onControlEnd);

    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerleave', this.onPointerLeave);
    canvas.addEventListener('click', this.onClick);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    this.intersection = new IntersectionObserver(([entry]) => {
      this.visible = !!entry?.isIntersecting;
      this.syncLoop();
    });
    this.intersection.observe(host);
    document.addEventListener('visibilitychange', this.onVisibility);
    this.resize();
    this.invalidate();
  }

  readonly invalidate = (): void => {
    if (this.disposed) return;
    this.wantFrame = true;
    this.syncLoop();
  };

  private wantFrame = false;

  private readonly onControlStart = (): void => {
    this.controls.autoRotate = false;
    this.controlsActive = true;
    this.interacted = true;
  };

  private interacted = false;

  private readonly onControlEnd = (): void => {
    this.controlsActive = false;
  };

  private readonly onVisibility = (): void => this.syncLoop();

  private syncLoop(): void {
    const shouldRun = this.visible && document.visibilityState === 'visible' && this.wantFrame;
    if (shouldRun && !this.running) {
      this.running = true;
      this.timer.reset();
      this.windowStart = performance.now();
      this.frames = 0;
      this.renderer.setAnimationLoop(this.frame);
    } else if (!shouldRun && this.running) {
      this.running = false;
      this.renderer.setAnimationLoop(null);
    }
  }

  private readonly frame = (timestamp: number): void => {
    this.timer.update(timestamp);
    const dt = Math.min(this.timer.getDelta(), 0.1);
    this.elapsed += dt;
    const animating = this.module.update(dt, this.elapsed);
    const moving = this.controls.update(dt);
    if (this.hoverPending) this.runHover();
    this.composer.render(dt);
    this.labels.render(this.module.scene, this.module.camera);
    this.sample();
    this.wantFrame = animating || moving || this.controls.autoRotate || this.controlsActive;
    if (!this.wantFrame) this.syncLoop();
  };

  private controlsActive = false;
  private elapsed = 0;

  private sample(): void {
    this.frames++;
    const now = performance.now();
    const span = now - this.windowStart;
    if (span < 1000) return;
    const fps = (this.frames * 1000) / span;
    this.frames = 0;
    this.windowStart = now;
    // Below 10 fps the page is being throttled (background tab, hidden pane), not GPU-bound.
    if (fps < 45 && fps >= 10 && this.wantFrame) this.slowWindows++;
    else this.slowWindows = 0;
    if (this.slowWindows >= 2) {
      this.slowWindows = 0;
      this.degrade();
    }
    this.options.onStats?.({
      fps: Math.round(fps),
      dpr: this.dpr,
      tier: this.tier,
      bloom: this.bloom.resolution.scale,
    });
  }

  private degrade(): void {
    if (this.dpr > 1) {
      this.dpr = Math.max(1, this.dpr - 0.25);
      this.renderer.setPixelRatio(this.dpr);
      this.resize();
      return;
    }
    if (this.bloom.resolution.scale > 0.25) {
      this.bloom.resolution.scale = 0.25;
      this.tier = 'low';
    }
  }

  resize(): void {
    const width = Math.max(1, this.host.clientWidth);
    const height = Math.max(1, this.host.clientHeight);
    this.module.camera.aspect = width / height;
    this.module.camera.updateProjectionMatrix();
    if (!this.interacted && this.module.fit) this.module.fit(width / height, this.controls);
    this.renderer.setSize(width, height, false);
    this.composer.setSize(width, height, false);
    this.labels.setSize(width, height);
    this.invalidate();
  }

  setAutoRotate(on: boolean): void {
    this.controls.autoRotate = on && !this.options.reducedMotion;
    this.invalidate();
  }

  private readonly onPointerMove = (event: PointerEvent): void => {
    if (!this.module.pick || !this.options.onHover) return;
    this.hoverPending = event;
    this.invalidate();
  };

  private readonly onPointerLeave = (): void => {
    this.hoverPending = null;
    this.options.onHover?.(null, 0, 0);
  };

  private readonly onClick = (event: MouseEvent): void => {
    if (!this.module.pick || !this.options.onClick) return;
    this.options.onClick(this.pickAt(event.clientX, event.clientY));
  };

  private runHover(): void {
    const event = this.hoverPending;
    this.hoverPending = null;
    if (!event) return;
    this.options.onHover?.(this.pickAt(event.clientX, event.clientY), event.clientX, event.clientY);
  }

  private pickAt(clientX: number, clientY: number): unknown {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.module.camera);
    return this.module.pick?.({ raycaster: this.raycaster, pointer: this.pointer }) ?? null;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    this.intersection.disconnect();
    document.removeEventListener('visibilitychange', this.onVisibility);
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointermove', this.onPointerMove);
    canvas.removeEventListener('pointerleave', this.onPointerLeave);
    canvas.removeEventListener('click', this.onClick);
    this.controls.removeEventListener('change', this.invalidate);
    this.controls.removeEventListener('start', this.onControlStart);
    this.controls.removeEventListener('end', this.onControlEnd);
    this.controls.dispose();
    this.timer.dispose();
    this.module.dispose();
    disposeTree(this.module.scene);
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    canvas.remove();
    this.labels.domElement.remove();
  }
}

export function disposeTree(root: Object3D): void {
  root.traverse((node) => {
    const mesh = node as Mesh;
    mesh.geometry?.dispose();
    const material = mesh.material as Material | Material[] | undefined;
    for (const m of Array.isArray(material) ? material : material ? [material] : []) {
      for (const value of Object.values(m)) if (value instanceof Texture) value.dispose();
      m.dispose();
    }
    if ('element' in node && node.element instanceof HTMLElement) node.element.remove();
  });
  root.clear();
}
