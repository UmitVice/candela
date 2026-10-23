# Phase 2 · ML — Train and release Candela Pro v0.1 (`p2-train`)

- Area you own: `ml/**`, `make/ml.mk`, `apps/web/public/observatory/**`, `docs/status/p2-train.md`, new ADRs.
- Runs in parallel with `p2-worker` and `p2-web`; Candela Spark's continuous trainer (`spark/`) yields the GPU to you through the lease protocol (your priority 80).
- Inputs: `CLAUDE.md`, master plan (*Model strategy*, *Data strategy*, *Evaluation*, *Release gates*), `docs/status/p1-ml.md`, `docs/status/p1-gateway.md`.

## Goal

The first real Candela Pro model: a QLoRA adapter on Google's Gemma 4 12B QAT int4 base that measurably beats the base on tool use and grounding without regressing on classic finance tasks, published on Hugging Face with an honest card, and visualised in the Observatory.

## Steps

1. Run a gateway instance on the ml port pair (`8730/8739`, internal tool API only, own SQLite file, shared snapshot) and generate the synthetic tool-use traces (target 6 000–8 000 conversations across all intents, multi-turn share ≥ 20 %, failure and refusal cases ≥ 10 %). Validate them, drop failures, and finalise dataset `d0.1` (manifest, data card).
2. Train **Candela Pro** with the configuration chosen by the `p1-ml` probe, under the resource guard and GPU lease (expect several hours; run in the background with `caffeinate -i nice -n 10`; you are notified when it exits). Use checkpoints so pauses lose little work.
3. Evaluate against the QAT base (fast suites, then full `tool_use` and `finqa`). Apply the release gate from the master plan. If a model fails it, iterate at most twice (data mix, learning rate, rank, epochs) and record each attempt.
4. Export for the worker (QAT int4 base + adapter, unmerged) and as a GGUF LoRA (PEFT conversion) for llama.cpp on the QAT Q4 GGUF base.
5. Observatory artifacts (`architecture.json`, `training.json`, `lora-deltas.json`, `eval.json`, `manifest.json`), plus `galaxy.json`: mean last-layer hidden state of Candela Pro over a short description of each S&P 500 company (public constituent list with GICS sectors), reduced to 3D with PCA (or UMAP if it adds clarity), market cap if available from the snapshot.
6. Publish to Hugging Face under `UmitVice`: `candela-pro-12b-v0.1-mlx-lora` (MLX adapter), `candela-pro-12b-v0.1-gguf-lora` (GGUF LoRA, usage instructions with the QAT Q4 GGUF), and `candela-finance-traces` (synthetic traces only; never redistribute sources whose license forbids it). Cards include intended use, limitations, evaluation tables, training details, hardware and time, license inheritance, and a not-financial-advice note.
7. Update `ml/configs/models.yaml` with released ids and local artifact paths so the worker can switch, and write `ml/reports/release-v0.1.md`.

## Acceptance

- `make ml-check` passes; reports and Observatory JSON committed and pushed.
- Release gate met (or the best attempt documented with reasons).
- Hugging Face repos exist and load (`mlx_lm.generate` with the adapter on the QAT base, `llama-server --lora` on the QAT GGUF).
- Report written to `docs/status/p2-train.md` with wall time, tokens/s, peak memory, pauses, and the evaluation table.
