# Candela — resume point

Snapshot: 2026-10-30. Read this first when resuming. The Director session plans and coordinates; phase sessions do the work.

## Owner rules (binding)

- The owner is away most of the time and must not be asked questions. Ask only for actions that need an explicit yes: public Gist/Space creation, Netlify production deploys, downloads, Hugging Face publishes.
- Exactly ONE chat session at a time, plus background training. Never train two models at once, including the owner's own `evidencedesk_ml.train_mlx` runs.
- Candela Pro = Gemma 4 12B on Google's QAT int4 weights + QLoRA (adapter never merged into the base for serving). Candela Spark = from-scratch QAT-native family in `spark/`. No lite tier. No Qwen models.
- Never touch `~/models` (read-only), the owner's `llama-server` on 8080, PostgreSQL 5432, or the owner's other processes.
- English only in repo files. No tests until the owner asks. No GitHub Actions. Netlify deploys: at most one per phase, `--no-build`.
- Security is binding (ADR 0008): visitors may only talk to the model; loopback-only listeners; internal routes never tunnelled.

## Where things stand

| Area | State | Where |
|---|---|---|
| Web terminal (Angular PWA) | Live at https://candela-terminal.netlify.app, with Observatory at `/observatory` | `docs/status/p1-web.md`, `p2-web.md`, `p3-observatory.md` |
| Go gateway | Done: chat, tools, market data, WebSocket, hardening | `docs/status/p1-gateway.md` |
| MLX worker | Done. The Gemma 4 12B check passed with the pilot adapter; telemetry speed-up and multimodal fix not re-checked on Gemma | `docs/status/p2-worker.md` |
| Live edge (Mac) | Built, sandboxed, verified through a real tunnel. **Currently offline**: the public Gist reports `status: offline` | `docs/status/p3-deploy.md`, `docs/operations.md` |
| Candela Spark | M1 (35M, int4 gap 0.088 % at M1) published: https://huggingface.co/UmitVice/candela-spark-35m. Trainer **stopped** at step 67 503 (SIGTERM at 2026-10-28 11:51 UTC); its LaunchAgent is not loaded. Last recorded int4-vs-bf16 gap was 1.0 %, not the 0.088 % of M1, so investigate before continuing | `docs/status/p1-spark.md`, `spark/` |
| Candela Pro data and pilot | d0.1 built; pilot trained; pilot regressed classic finance suites | `docs/status/p1-ml.md` |
| Candela Pro v0.1 training | Finished: 1 080 / 1 080 steps, final validation loss 0.170. Checkpoint `ml/runs/candela-pro-v0.1-lr5e5/checkpoints/step-001080`, adapter in `.../adapter/`. Observatory artifacts exported to `ml/artifacts/observatory/` | `docs/status/p2-train.md`, ADR 0403 |
| Candela Pro v0.1 evaluation | Base (QAT Q4) full evaluation finished: `ml/reports/eval/gemma-4-12b-qat-base-d0.2-full-20261027T062333Z.{json,md}` (uncommitted). **Tuned-model evaluation never finished**: its background job was stopped when the previous session ended. Stale lease `~/.candela/leases/lab-eval.json` points to a dead PID | — |
| Merged quant pack | Streaming merge and export code committed (`d1ead5e`). Not yet run for v0.1 | ADR 0403 |
| Hugging Face | Spark M1 published. The Candela Pro pilot adapter repo returns 401 (not published or private) | — |
| Dependabot | 0 open alerts | — |

## Pending owner decisions

1. **Move inference to a public ZeroGPU Space** (Gemma 4 12B + adapter, tools and market data inside the Space). Recommended, because the Mac would then not need to serve visitors. Creating a public Space needs explicit owner approval.
2. **Quant pack for Candela Pro** (GGUF Q4_K_M, Q5_K_M, Q6_K, Q8_0; MLX 4-bit and 8-bit). Owner requested it. Q4 from a merged model loses part of the QAT advantage unless a short QAT/distillation restore pass is run; label it honestly.
3. Whether to publish Candela Pro v0.1 even if the release gate fails (it would be labelled experimental with honest numbers).

## Resume steps (in order)

1. `git pull origin main`; check `git status`. Commit `ml/reports/eval/gemma-4-12b-qat-base-d0.2-full-*` only from the ML session, not here.
2. Remove the stale lease if its PID is dead: `~/.candela/leases/lab-eval.json` (check with `ps -p <pid>` first).
3. Start a p2-train session (cwd: this repo). Brief: finish the tuned-model full evaluation for `candela-pro-v0.1-lr5e5` with the same seed and decoding as the base, apply the release gate (ADR 0403), export GGUF-LoRA, sync Observatory including `galaxy.json`, publish only if the gate passes (otherwise labelled experimental), then the quant pack. One background job at a time, guard at 11 GB.
4. Spark: check why the trainer stopped and whether the 1.0 % gap is real. Reload the LaunchAgent only after the Candela Pro work is done (Candela Pro has priority). Spark continuous training resumes automatically from `step-00067503`.
5. Live stack: when the Mac is on and the owner wants it, `make live-up` (edge supervisor publishes the endpoint to the Gist). Until a ZeroGPU decision, the site stays in replay mode when offline.
6. After the tuned evaluation: record real chat recordings (`deploy/recordings`), then portfolio polish (`docs/plan/p4-polish.md`).

## Useful commands

- Pro resume (if training stopped again): `cd ml && MACOSX_DEPLOYMENT_TARGET=14.0 caffeinate -i nice -n 10 uv run --frozen lab train resume candela-pro-v0.1-lr5e5`
- Machine status: `make -C . help`, `make live-status`, `make ml-check`, `make worker-check`, `make spark-check`
- Spark daemon: `spark daemon status`, `spark daemon install` (after Pro work is done)
- Gist (public, contains only the endpoint document): `https://gist.githubusercontent.com/UmitVice/236f53f0313131e3c2ad11ecb75d46d3/raw/candela-endpoint.json`

## Known risks

- A sleep or shutdown stops every background job. Everything long-running checkpoints (Pro: step checkpoints; Spark: exact resume), but evaluations do not resume and must be restarted.
- Memory is shared with the owner's work. Gemma runs need about 11 GB free; the guard pauses on macOS pressure.
- `.claude/` and some eval reports are untracked in the working tree; do not commit them without checking.
- ADR numbers: Director 0001–0099, web 0100–0199, gateway 0200–0299, worker 0300–0399, ml 0400–0499, deploy 0500–0599, spark 0600–0699.
