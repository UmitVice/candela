# Phase 1 · ML — Candela Lab foundation (`p1-ml`)

- Area you own: `ml/**`, `make/ml.mk`, `apps/web/public/observatory/**` (artifacts only), `docs/status/p1-ml.md`, new ADRs.
- Runs in parallel with `p1-web` and `p1-gateway`. Do not touch their paths.
- Inputs: `CLAUDE.md`, `docs/plan/00-master-plan.md` (sections *Model strategy*, *Data strategy*, *Evaluation*), `contracts/tools.json`, `contracts/tools.md`, `contracts/system-prompt.md`, `contracts/observatory.md`.

## Goal

A reproducible, resource-aware ML pipeline on Apple Silicon for **Candela Pro** (Gemma 4 12B on Google's QAT int4 weights, QLoRA) — data → training → evaluation → export → publishing — validated end to end with a short pilot, plus a baseline evaluation of the untouched QAT base so every later number has a reference. (Revised 2026-10-23: no lite tier, no Qwen models; the from-scratch Candela Spark lives in `spark/` and is not your area.)

## Deliverables

1. uv project `ml/` (`candela-lab`, Python 3.14, ruff, pyright) with a Typer CLI `lab`: `doctor`, `data fetch|build|stats|card`, `traces generate|validate`, `train run|resume|status`, `eval run|compare`, `export fuse|gguf`, `observatory export`, `publish`.
2. `ml/configs/models.yaml`: Candela Pro only — base `~/models/gemma-4-12b-it-qat-mlx-q4` (path overridable with `CANDELA_PRO_BASE`; the owner's files, strictly read-only, never moved, modified or deleted), QAT bf16 reference `~/models/gemma-4-12b-it-qat-unquantized`, GGUF base `~/models/gemma-4-12b-it-qat/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf`, upstream ids (`google/gemma-4-12B-it-qat-q4_0-unquantized`) for reproducibility, chat-template notes for tools and thinking, context length, LoRA defaults. The worker reads this file too.
3. **Resource guard and GPU lease** (`candela_lab.resources`): implement `contracts/gpu-lease.md` (training priority 80, evaluation/export 60) next to the memory guard; available memory and swap trend via `psutil` plus macOS `vm_stat`/`sysctl vm.swapusage`/memory-pressure level; `wait_for_headroom(budget_gb)` with logged backoff; a pause signal checked at step boundaries; MLX memory, cache and wired limits; process niceness. Defaults: start training only when available ≥ budget + 3 GB; pause (checkpoint and release memory) when available < 1.5 GB or swap grew > 1 GB in 5 minutes; resume when recovered for 10 minutes. Every pause is logged into the run and the Observatory `training.json`.
4. **Data pipeline** for dataset version `d0.1` (sources, licenses and mix in the master plan):
   - fetch through `datasets` into the shared HF cache; normalise every source to `{"messages": [...], "tools"?: [...], "meta": {"source","license","task"}}`;
   - classic tasks become instructions in the Candela voice (sentiment, headline questions, numeric QA with short rationales);
   - quality filters, exact and MinHash near-duplicate removal, 13-gram decontamination against every eval set, PII scrubbing, token-length limits with the base tokenizer;
   - weighted mix from `ml/configs/data/d0.1.yaml`, deterministic splits (train/valid; eval sets are held out entirely);
   - outputs under `ml/data/processed/d0.1/` (git-ignored), committed manifest `ml/manifests/d0.1.json` (hashes, counts, config hash) and data card `ml/datacards/d0.1.md` (sources, licenses, counts, token stats, examples).
5. **Synthetic tool-use traces** framework (`candela_lab.traces`): intent planners (single-stock analysis, comparison, technical-only, fundamentals-only with and without data, forecast interpretation, follow-up turns, unknown company → `search_symbols`, tool failure, request for personal advice → educational answer, off-topic → brief redirect); executor client for the gateway internal API (`http://127.0.0.1:8739/internal/v1/tools/execute`, ml port pair from `CLAUDE.md`); grounded answer composer (Markdown sections from the system prompt, phrase banks for variety, numbers copied verbatim from model views); validators (arguments match schemas, every number in the answer is present in a tool output or derived by the composer, structure checks). Implement against a fake executor that serves contract examples; if the gateway internal API is already running at the end of the phase, generate a pilot batch of 200 traces.
6. **Evaluation harness** (`candela_lab.eval`), deterministic (temperature 0, fixed seeds and sample sizes), fast mode ≤ 30 min per model: suites `fpb`, `fiqa_sa`, `headlines`, `finqa`, `convfinqa`, `tool_use` (tool choice precision/recall, argument validity, grounding rate on held-out traces), `heldout_loss`. Reports to `ml/reports/eval/<modelId>-<utc>.json` and `.md` (committed) and Observatory `eval.json` when comparing base vs tuned.
7. **Baseline and probe**: run the fast eval on the untouched QAT base, then 20-step QLoRA probes at `max_seq_length` 2048 with the custom loss for the LoRA layer counts in ADR 0003, measuring peak memory, tokens/s and whether Gemma 4's chat template renders and parses tool calls reliably. Fill in the probe table in ADR 0003 and set the chosen configuration in `ml/configs/train/`. Commit the reports.
8. **Training wrapper** (`candela_lab.train`) over the mlx-lm LoRA Python API, with a custom loss that applies the LM head only at supervised positions (critical for Gemma's 262k vocabulary), one sample per supervised assistant turn, YAML configs in `ml/configs/train/`, resource-guard callbacks, metrics JSONL, checkpoints every N steps under `ml/runs/<run-id>/`, per-checkpoint LoRA delta norms, resume, and export of `architecture.json`, `training.json`, `lora-deltas.json` per `contracts/observatory.md`.
9. **Pilot**: a short QLoRA run (100–200 steps) of Candela Pro on a `d0.1` subset under the guard and lease, then its fast eval, and the MLX-adapter → PEFT → GGUF-LoRA conversion (llama.cpp converter at a pinned tag in git-ignored `ml/vendor/`), loaded with `llama-server --lora` on the QAT GGUF on a spare loopback port (8713). Adapters are never merged into the int4 base. Export its Observatory artifacts flagged as a pilot so the web phases have real data to render; write them into `apps/web/public/observatory/` only once `apps/web/package.json` exists (the web scaffold is done), otherwise keep them in `ml/artifacts/observatory/` and sync with `lab observatory export --sync`.
10. **Publishing** (`candela_lab.publish`) with `huggingface_hub`: model repos for adapters and GGUF, dataset repo for synthetic data, model and dataset cards rendered from templates with evaluation tables. Implement and dry-run only in this phase.
11. `make/ml.mk`: `ml-sync`, `ml-doctor`, `ml-data`, `ml-eval-baseline`, `ml-train-pilot`, `ml-check` (ruff format check, ruff lint, pyright).

## Acceptance (verify by running; no automated tests)

- `make ml-check` passes; `lab doctor` prints versions, Metal device, memory headroom and guard decision.
- `lab data build --version d0.1` produces splits, manifest and data card; licenses are recorded per example.
- The baseline report for the QAT base and the probe table are committed.
- The pilot run completes under the resource guard and GPU lease (including at least one simulated pause/resume), produces an adapter that loads in MLX and, converted to a GGUF LoRA, in the local `llama-server` with the QAT GGUF, and exports Observatory artifacts.
- Report written to `docs/status/p1-ml.md` with timings, peak memory and throughput.

## Out of scope

Full training runs and Hugging Face uploads (`p2-train`), serving (`p2-worker`), Candela Spark (`spark/`), tests. Your ADRs use numbers 0400–0499.
