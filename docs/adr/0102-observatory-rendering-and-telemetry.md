# 0102 — Observatory: rendering engine, telemetry pipeline and data honesty

- Status: accepted
- Date: 2026-10-26

## Context

Phase `p3-observatory` adds the 3D design view: Architecture Tower, Fine-tune Field, Embedding Galaxy, Lab HUD and Spark Lab. Constraints: plain three.js 0.186.1 (angular-three does not support Angular 22), three.js must stay out of the Terminal bundle, strict CSP with Trusted Types, a shared laptop GPU, mid-range phones, and the brief's rule that nothing decorative pretends to be data. The real MLX worker does not exist yet. The gateway's `fakeworker` emits a single-layer, single-candidate frame, which cannot exercise a 48-layer tower.

## Decision

- **Engine.** One `Stage` class owns the `WebGLRenderer`, the postprocessing `EffectComposer` (bloom with mipmap blur, vignette, SMAA unless the low tier), a `CSS2DRenderer` for labels, `OrbitControls`, resize and visibility observers, and disposal (`forceContextLoss` included). Scenes implement a small `SceneModule` interface: `update`, `pick`, `fit`, `dispose`. Heads, slabs, MLP cores, LoRA bars and galaxy points are `InstancedMesh` or `Points` with per-instance colour, so each scene is a handful of draw calls.
- **Loop policy.** `setAnimationLoop` runs only while the canvas intersects the viewport, the document is visible and the scene reports motion. `update()` returns false when idle under reduced motion, and controls or new frames re-arm it. Under `prefers-reduced-motion`, auto-rotation, ambient breathing, pulses and easing are off and values snap.
- **Adaptive quality.** DPR is capped at 2 on desktop and 1.5 on mobile. The initial tier comes from `hardwareConcurrency` and `deviceMemory`. Two consecutive one-second windows between 10 and 45 fps lower the DPR in 0.25 steps, then the bloom resolution. Windows below 10 fps are ignored, because they mean a throttled background page, not a slow GPU. Without WebGL2, every scene shows its data tables and a notice.
- **Camera framing.** Each scene fits its bounding sphere to the current aspect ratio on every resize until the user first touches the controls. Portrait phones and the 60 % split pane therefore frame the same content.
- **Telemetry pipeline.** `TelemetryStore` (main bundle, about 1 kB) holds a 256-frame ring buffer. `ChatService` pushes `telemetry` events into it instead of the turn reducer. Signals (`latest`, `count`) are republished at most every 50 ms. The tower consumes the ring by index in its render loop: each frame launches a pulse up the stack, and slab glow eases to the frame's residual norm divided by its largest norm as the pulse passes. When a frame's layer count differs from the tower's, indices map proportionally and the UI says so. `options.telemetry` is `prefs.telemetry || observatoryVisible`.
- **Streams survive view changes.** The navigation-start cancel from p2 is removed: switching between Terminal and Observatory, or between scenes, no longer cancels a generation. That is the point of watching the model think. Switching conversations still cancels.
- **Layout.** At ≥ 1440 px the Observatory embeds the real `TerminalPage` at 40 %. Below that, a compact prompt bar sends through the same `CommandService`/`ChatService` path.
- **Data honesty.** No starfield or decorative particles. The only non-data motion is a faint 0.02 ambient glow, smaller than any telemetry glow, and the entropy flame driven by the measured entropy. Missing artifacts show "awaiting" states. Replay mode says that live telemetry needs the gateway. The dev worker registers as "Dev telemetry worker (synthetic)", and the tower names the frame source whenever it differs from the displayed model.
- **Dev telemetry worker.** `apps/web/scripts/telemetry-worker.mjs` (`make web-telemetry-worker`) speaks `candela.worker.v1` with Node's built-in WebSocket and streams contract-shaped `TelemetryFrame`s for the architecture in `manifest.json` (48 layers, top-5, logit lens on four layers). The real worker replaces it without web changes.
- **Spark live status.** Spark Lab polls `GET /api/v1/lab/spark` every 30 s while visible, only when the gateway is live. It accepts only `schema: candela.spark.status.v1`, stops probing after a 404 and otherwise labels the static `observatory/spark/` export as its source.
- **Charts.** The Observatory has its own tree-shaken ECharts setup (line, bar, scatter, mark line/point/area, legend), shares the theme tokens with the Terminal and uses rich-text tooltips (Trusted Types, ADR 0101).

## Consequences

- three.js and postprocessing ship only in the lazy `observatory-routes` chunk (≈ 200 kB gzip). Initial JS grows 201.7 → 208.3 kB gzip (+3.3 %): the telemetry store and a chunk now shared because the Observatory embeds the Terminal.
- On the M5 Pro a synchronous tower frame (render + composer + labels, `gl.finish`) costs 0.74 ms at 2048 × 1166 and 0.57 ms at a 375 × 812 phone viewport with DPR 1.5. Real phone GPUs were not measured.
- The galaxy needs `galaxy.json`, which the ML lab has not exported yet. The scene is implemented and was verified against an in-page fixture.

## Alternatives considered

- **angular-three / troika-three-text.** The first does not support Angular 22. The second adds workers and SDF font loading that the CSP and bundle budget do not need; CSS2D labels are crisp, accessible and cheap at these counts.
- **Driving the tower from Angular signals per frame.** This would re-render views at token rate; the ring buffer keeps Angular at 20 Hz or less and the scene at display rate.
- **Patching the gateway `fakeworker`.** That file is in another area. A web-side dev worker keeps the change inside this phase and the protocol unchanged.
