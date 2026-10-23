# Phase 2 · ML — Train and release Candela v0.1 (`p2-train`)

- Area you own: `ml/**`, `make/ml.mk`, `apps/web/public/observatory/**`, `docs/status/p2-train.md`, new ADRs.
- Runs in parallel with `p2-worker` and `p2-web` (they use small models briefly; the resource guard arbitrates memory).
- Inputs: `CLAUDE.md`, master plan (*Model strategy*, *Data strategy*, *Evaluation*, *Release gates*), `docs/status/p1-ml.md`, `docs/status/p1-gateway.md`.

## Goal

The first real Candela models: a lite and a pro LoRA fine-tune that measurably beat their base models on tool use and grounding without regressing on classic finance tasks, published on Hugging Face with honest cards, and visualised in the Observatory.

## Steps

1. Run a gateway instance on the ml port pair (`8730/8739`, internal tool API only, own SQLite file, shared snapshot) and generate the synthetic tool-use traces (target 6 000–8 000 conversations across all intents, multi-turn share ≥ 20 %, failure and refusal cases ≥ 10 %). Validate them, drop failures, and finalise dataset `d0.1` (manifest, data card).
2. Train the **lite** model (full run) under the resource guard; fast eval vs base; export fused MLX 4-bit and GGUF Q4_K_M.
3. Train the **pro** model under the resource guard (expect several hours; run in the background with `caffeinate -i nice -n 10`; you are notified when it exits). Use checkpoints so pauses lose little work.
4. Evaluate pro and lite against their bases (fast suites, then full `tool_use` and `finqa`). Apply the release gate from the master plan. If a model fails it, iterate at most twice (data mix, learning rate, rank, epochs) and record each attempt.
5. Export the pro model for the worker (base 4-bit + adapter, or a fused 4-bit model if it serves faster at equal quality; measure) and as a GGUF LoRA (PEFT conversion) for llama.cpp on the official QAT GGUF base. Lite: fused GGUF Q4_K_M.
6. Observatory artifacts for both models (`architecture.json`, `training.json`, `lora-deltas.json`, `eval.json`, `manifest.json`), plus `galaxy.json`: mean last-layer hidden state of the pro model over a short description of each S&P 500 company (public constituent list with GICS sectors), reduced to 3D with PCA (or UMAP if it adds clarity), market cap if available from the snapshot.
7. Publish to Hugging Face under `UmitVice`: `candela-<size>-v0.1-lora` (MLX adapter), `candela-<size>-v0.1-GGUF` (GGUF LoRA for pro, full Q4_K_M for lite), and `candela-finance-traces` (synthetic traces only; never redistribute sources whose license forbids it). Cards include intended use, limitations, evaluation tables, training details, hardware and time, license inheritance, and a not-financial-advice note.
8. Update `ml/configs/models.yaml` with released ids and local artifact paths so the worker can switch, and write `ml/reports/release-v0.1.md`.

## Acceptance

- `make ml-check` passes; reports and Observatory JSON committed and pushed.
- Release gate met (or the best attempt documented with reasons).
- Hugging Face repos exist and load (`mlx_lm.generate` on the adapter, `llama-server` on the GGUF).
- Report written to `docs/status/p2-train.md` with wall time, tokens/s, peak memory, pauses, and the evaluation table.
