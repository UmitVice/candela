# p3-observatory — status

STATUS: done

Summary:
The Observatory is live at https://candela-terminal.netlify.app/observatory. It is a lazy-loaded 3D design view with five scenes, and each scene renders the real artifacts in `apps/web/public/observatory/`.

- **Architecture Tower** (`/observatory/tower`):
  - Built from `architecture.json` (Candela Pro pilot: 48 slabs, 16 heads on a ring coloured by 8 KV groups, MLP core sized by intermediate/hidden). Choosing a Spark model in the version selector builds the Spark tower instead, with its local and global layers marked. Without artifacts, the tower falls back to `/status` `architecture`.
  - Fixed parts: a token-embedding base, amber edges with a label on the LoRA layers, and an LM-head crown with top-5 bars.
  - With live telemetry, every frame sends a pulse up the stack. As the pulse passes, each slab's glow eases to that layer's residual norm divided by the token's largest norm. Logit-lens labels sit on the sampled layers, a top-5 list sits above the crown, and the entropy-driven flame burns above the crown. The tooltip shows the layer kind, LoRA state and last norm.
  - Telemetry is requested automatically while the Observatory is visible. Its status overlay names the frame source and states replay or idle honestly.
- **Fine-tune Field** (`/observatory/field?model=…&step=…`):
  - 336 instanced bars: x = projection, z = layer, y = log-scaled ‖scale·B·A‖_F.
  - Amber-to-flame ramp, with frozen cells drawn flat and grey.
  - Checkpoint slider and play button that eases between checkpoints. Deep links for model and step.
  - Hover tooltips show the exact values.
- **Embedding Galaxy** (`/observatory/galaxy`):
  - Points coloured by sector and sized by market cap, with labels on the 12 largest, sector toggles and find by symbol or name.
  - Clicking a point selects it. "pin in context" sets the Terminal context symbol, and `/analyze SYM` prefills the prompt (it switches to the Terminal below 1440 px).
  - It shows "Awaiting the first galaxy export" until `galaxy.json` exists, which it does not yet (see open issues).
- **Lab HUD** (`/observatory/lab`):
  - A model card: run, window, hardware and guard, data, schedule, adapter, held-out loss.
  - Charts: train and validation loss, learning rate, and tokens/s with peak memory against the guard limit. Dashed marks show resource-guard pauses, with their reasons.
  - Base vs tuned evaluation bars: amber improved, red regressed, with ▲/▼ and the delta. Side-by-side samples when present.
- **Spark Lab** (`/observatory/spark`):
  - A family tree (35M training with m1 released; 125M → 2B planned).
  - Training progress from `GET /api/v1/lab/spark` when the gateway serves it, otherwise from the static export, with the source labelled.
  - Charts: train loss vs tokens (main and m1 branch), bf16 vs int4 validation with the relative QAT gap, throughput with pauses, and loss vs compute (C ≈ 6·N·D).
  - Zero-shot bars against chance.
  - An attention explorer for the 8 finance sentences: a 3D stack of 12 × 6 real heatmaps (click a tile) with a 2D drill-down that shows query/key/probability on hover. Selects make it keyboard-accessible.
- **Experience**:
  - At ≥ 1440 px, split view: the real Terminal at 40 %, the Observatory at 60 %. Below that, a full-screen Observatory with a compact prompt bar.
  - Streams keep running when you switch views or scenes.
  - Version selector driven by `manifest.json` plus the Spark manifest.
  - A "Data" toggle on every scene shows the same numbers as tables.
  - WebGL2 missing: tables and a notice. `prefers-reduced-motion`: animation frozen.
- **Engine**:
  - Plain three.js 0.186.1, postprocessing 6.39.5 (bloom, vignette, SMAA), CSS2D labels, instancing.
  - The loop runs only while the scene is visible and has motion; it pauses on `visibilitychange`. GPU resources are disposed on destroy.
  - DPR cap 2 / 1.5, adaptive degradation, and auto-framing per aspect ratio.
- **Telemetry pipeline**: chat `telemetry` events → `TelemetryStore` ring buffer (256 frames, signals republished at ≤ 20 Hz) → the scene reads by index each frame and interpolates. Nothing in the web code is specific to a worker. A real worker that emits contract `TelemetryFrame`s needs no web change.
- **Dev tooling**: `make web-telemetry-worker` runs `apps/web/scripts/telemetry-worker.mjs`. It speaks `candela.worker.v1` and streams synthetic, contract-shaped frames for the manifest's architecture. It registers as "Dev telemetry worker (synthetic)", and the UI shows that name.

Commits: b768a37 build(web): add three.js 0.186.1 and postprocessing 6.39.5, 30089ae feat(web): telemetry ring buffer fed by chat streams, 338a47a feat(web): Observatory with five 3D and HUD scenes from real artifacts, 2a2ab80 feat(web): synthetic dev telemetry worker for the Observatory, eff1caa fix(web): frame Observatory scenes, mobile bar, compact prompt bar, 75ecdd1 docs(adr): record Observatory rendering and telemetry decisions, plus the commit adding this report.

Verified:
- **Quality gates.**
  - `make web-check` passes: Prettier, `ng lint` with no errors, production build. `pnpm audit --audit-level high` finds no known vulnerabilities.
  - three.js and postprocessing appear only in the lazy `observatory-routes` chunk (≈ 200 kB gzip). No initial chunk contains `WebGLRenderer` or `EffectComposer`.
- **Terminal bundle.** HEAD before this phase was rebuilt from `git archive` for a baseline.
  - Initial JS: 201.7 → 208.3 kB gzip (+3.3 %, within 5 %). Angular's estimate: 180.3 → 187.9 kB (+4.2 %).
  - `check-bundle.mjs` had missed chunk names containing `_` or `-`; it is fixed and both builds were re-measured with it.
- **Live telemetry.** My gateway (`make gateway-run`, 8710/8719) and the dev telemetry worker, through `ng serve`, over WS:
  - Compact prompt bar, split-view Terminal and a 375 × 812 mobile viewport all streamed. Status read "live telemetry · token #27 · … · entropy … nats". Pulses travelled up the stack, logit-lens labels showed on L12/L24/L36/L47 and the top-5 list updated. Up to 74 frames arrived per answer (the gateway's 50 ms throttle drops some).
  - Screenshots: `docs/media/p3-observatory-split-tower-live.png`, `p3-observatory-mobile-tower-live.png`.
- **Frame cost.** The browser pane was hidden (background page, rAF throttled), so fps counters were meaningless there. Instead I timed 60 synchronous frames (scene update + composer + labels, synced with `readPixels`) on the Apple M5 Pro: 0.74 ms/frame at 2048 × 1166 (DPR 2) and 0.57 ms/frame at the 375 × 812 phone viewport (DPR 1.5). That is far under the 16.7 ms that 60 fps needs.
- **Field.** Hover tooltips match `lora-deltas.json` exactly: layer 47 at step 120 gives gate_proj 3.329391, up_proj 2.948224, down_proj 2.233173. `?step=40` deep links restore the checkpoint. Screenshot: `p3-observatory-field.png`.
- **Lab HUD.** 4 charts with both pauses (step 29 simulated, step 75 swap growth) and the 10.5 GB guard line. 9 evaluation suites are coloured by direction. Screenshot: `p3-observatory-lab.png`.
- **Spark Lab.** Charts and the attention explorer render the real export. The 2D drill-down decodes the base64 lower-triangular uint8 maps. Screenshot: `p3-observatory-spark-attention.png`.
- **Galaxy.** `galaxy.json` does not exist yet, so the scene was verified with an in-page fixture: `fetch` was stubbed in the browser and nothing was written to disk. Checked: points, sizes, sector colours, find, selection label, pin, and `/analyze NVDA` prefilling the Terminal prompt. Production shows the awaiting state.
- **Data and fallbacks.**
  - Data toggle: tables for every scene (architecture 15 rows, LoRA norms 16 adapted layers, train 120 / valid 3 / pauses 2 / eval 9, Spark valid 16 / pauses 3 / zero-shot 7).
  - Forcing `getContext('webgl2')` to null shows the notice and tables, with the toggle disabled.
  - With the reduced-motion flag set, the loop stops after the first frame and auto-rotate is off.
- **Layout.** At 1600 × 900 the split is 639 / 960 px. At 375 × 812, `scrollWidth == clientWidth` after fixing the scene bar.
- **Production headers.** `make web-preview` assets on :4210 (after clearing a stale service worker from an earlier preview): all five scenes, 0 `securitypolicyviolation` events, no errors, rich-text ECharts tooltips.
- **Deploy.** One production deploy: `WEB_MODE=auto make web-deploy`, netlify-cli 27.14.2 `--no-build`, deploy `6ade9b5591cba015d2cd0202`. On the live site all five scenes load real artifacts, the galaxy shows its awaiting state, and there are 0 CSP violations and no errors.
- **Cleanup.** My gateway, dev telemetry worker, `ng serve` and the preview server are stopped. Ports 4200, 4210, 8710 and 8719 are free. No foreign process, `~/models` or training job was touched.

Decisions:
- ADR 0102 (Observatory rendering, telemetry pipeline, data honesty), covering:
  - The `Stage` and `SceneModule` engine, the loop policy, adaptive quality with a guard against throttled pages, and auto-framing.
  - The ring-buffer telemetry store and `options.telemetry = prefs || observatoryVisible`.
  - The web-side dev telemetry worker, Spark live polling with a 404 fallback, and no decorative noise.
- Deviations from the brief:
  - p2's "navigation cancels the stream" is removed, so you can chat in the Terminal and watch in the Observatory. Switching conversations still cancels.
  - CSS2D labels are used, not troika.
  - Fps was measured as synchronous frame cost, not with a live counter: the pane was hidden.
  - The galaxy is verified on a fixture because its artifact is missing.

Open issues / risks:
- **No `galaxy.json` yet.** The ML lab has `lab observatory galaxy <model>`, which needs the 12B on the GPU, so it has to queue behind training. Until then the galaxy shows "awaiting".
- **No `GET /api/v1/lab/spark` on the gateway.** Spark Lab uses the static export and says so.
- **Replay has no telemetry.** Public visitors see the tower in ambient mode with a replay note until the live gateway is published.
- **Mid-range phone fps was not measured on hardware.** Only the emulated viewport on the M5 Pro was measured. The low tier (no SMAA, quarter-resolution bloom, DPR ≤ 1.25) and runtime degradation are in place.
- **Reduced motion was checked by flipping the service flag,** not the OS setting (the pane cannot emulate media features).
- **Pre-existing Dependabot alert #7** (cel-go, medium) is in `services/gateway/go.mod`; that is the gateway's area.

Notes for the next phases:
- **Director / ml:**
  - Run `lab observatory galaxy candela-pro-pilot` when the GPU queue allows, then list it as `galaxy` in `manifest.json` (`make ml-observatory`). The scene picks it up with no web change.
  - Proposed for `contracts/observatory.md`: document the Spark schemas (`candela.observatory.spark.v1`, as in p1-spark) and the optional `pilot` flag.
- **Director / gateway:**
  - Serve `GET /api/v1/lab/spark` returning the sanitised `~/.candela/spark/status.json` (`schema: candela.spark.status.v1`) and add it to `contracts/api.md`. The web client already polls it every 30 s while Spark Lab is visible and validates the schema.
- **p2-worker:**
  - Emit every decoder layer in `layers[]` (layer indices 0..N-1) and a few `logitLens` layers (the web labels any it receives) at ≤ 20 frames/s, and register `supportsTelemetry: true` with `architecture`.
  - `make web-telemetry-worker` shows the expected frame shape end to end.
- **Replay:** record a real telemetry trace from the worker into the replay fixtures, labelled as recorded, so the public tower can animate honestly.
