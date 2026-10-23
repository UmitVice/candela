# Phase 3 · Web — Observatory, the 3D design view (`p3-observatory`)

- Area you own: `apps/web/**` (read-only for `apps/web/public/observatory/`), `make/web.mk`, `docs/status/p3-observatory.md`, new ADRs.
- Runs in parallel with `p3-deploy` (which owns `deploy/**` and gateway deployment tooling).
- Inputs: `CLAUDE.md`, `contracts/observatory.md`, `contracts/api.md` (`TelemetryFrame`, `ModelInfo.architecture`), status reports of earlier phases, artifacts in `apps/web/public/observatory/`.

## Goal

A professional, cinematic but data-honest 3D view of the model that the owner can open from the top bar (**Observatory**) while Terminal stays the default. Everything shown comes from real artifacts or live telemetry; nothing is decorative noise pretending to be data.

## Scenes

1. **Architecture Tower** (default). The decoder stack as N translucent slabs (one per layer) built from `architecture.json`. Each slab holds a ring of attention-head nodes (KV groups as colour clusters) around an MLP core. Token embeddings enter at the base; the LM head "crown" at the top shows the live top-5 next-token distribution as bars; distribution entropy drives a subtle flame turbulence above the crown (the Candela motif). With telemetry on, each generated token sends a pulse up the stack, slab glow follows the normalised residual norm for that layer, and logit-lens labels float beside sampled layers with their top-3 tokens. Idle: slow ambient motion.
2. **Fine-tune Field**. 3D bars (x = module, z = layer, y = log-scaled ‖scale·B·A‖_F) from `lora-deltas.json`, amber-to-flame colour ramp, a checkpoint timeline that animates how adaptation grows during training, version switcher, hover tooltips with exact values.
3. **Embedding Galaxy**. Points from `galaxy.json` coloured by sector, sized by market cap, orbit controls, hover labels, click to focus a symbol in the terminal context and offer `/analyze`.
4. **Lab HUD**. 2D ECharts overlays: train/validation loss, learning rate, tokens/s and peak memory with resource-guard pause markers; base vs tuned evaluation bars per suite; model card summary.

## Experience

- Desktop ≥ 1440 px: split view (terminal 40 %, Observatory 60 %) so the owner can chat and watch the model think; telemetry is requested automatically while the Observatory is visible. Smaller screens: full-screen Observatory with a compact prompt bar.
- Version selector driven by `manifest.json`; deep links (`/observatory/tower`, `/observatory/field?model=…&step=…`, `/observatory/galaxy`).
- Accessible alternative: each scene has a "data" toggle that shows the same numbers as tables; `prefers-reduced-motion` freezes animation.
- Visual language from `p1-web` tokens: near-black space, amber/flame highlights, thin cyan data lines, restrained bloom.

## Engineering

- Plain three.js 0.186.x with `postprocessing` (bloom, SMAA, vignette); `InstancedMesh` for heads, bars and points; CSS2D labels or troika text if compatible.
- Lazy route chunk; three.js never in the Terminal bundle. Render loop runs only while visible and animating; pause on `visibilitychange`; dispose GPU resources on destroy.
- Adaptive quality: DPR cap 2 (desktop) / 1.5 (mobile), reduced effects on low-end devices, WebGL2 required with a graceful 2D fallback message.
- Telemetry pipeline: chat events → signal store → scene (ring buffer, ≤ 20 Hz updates, interpolation between frames).
- If artifacts are missing, derive the tower from `/api/v1/status` `architecture` and show the other scenes as "awaiting first training run".

## Acceptance (verify by running; no automated tests)

- `make web-check` passes; Terminal route bundle unchanged within 5 %.
- All four scenes render real artifacts; the tower animates with live telemetry from the local gateway and worker; 60 fps on the owner's Mac, ≥ 30 fps on a mid-range phone preview.
- One production deploy at the end.
- Report with screenshots in `docs/media/` written to `docs/status/p3-observatory.md`.

## Out of scope

Changes to artifacts or their generation (propose them in your report), tests.
