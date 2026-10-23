# Phase 3 · Spark — Scaling study and the next size (`p3-spark`)

- Area you own: `spark/**`, `make/spark.mk`, `apps/web/public/observatory/spark/**` (artifacts only), `docs/status/p3-spark.md`, ADRs 0600–0699.
- Runs in parallel with `p3-observatory` and `p3-deploy`. GPU lease priorities still apply (live inference and Candela Pro work come first).
- Inputs: `docs/status/p1-spark.md`, ADRs 0009, 0600, 0601, the running daemon's metrics, `docs/plan/00-master-plan.md` (section 5).

## Goal

Turn Spark from one small model into a scientifically grounded, growing family: measure how it scales, prove the QAT recipe with an ablation, and grow to the next size from the trained 35M checkpoint instead of starting over.

## Deliverables

1. **QAT ablation at tiny scale** (≈ 5–10M parameters, equal token budgets): bf16 then post-training int4 vs QAT from step 0 vs late QAT (last 10–20 % of tokens) vs QAT after a short warm-up; report final bf16 and int4 validation loss and the gap; confirm or revise ADR 0601.
2. **Scaling study**: at least three sizes from the family presets trained with the same recipe and compute-proportional token budgets; fit a power law of validation loss vs compute; plot and write `spark/reports/scaling.md`.
3. **Growth to the next size** (≈ 125M): implement a function-preserving or near-preserving growth operator from the 35M checkpoint (depth and width expansion per ADR 0600, e.g. HyperCloning-style width growth plus layer stacking), verify the grown model's initial loss matches the parent's, continue QAT pretraining under the daemon, and compare against a from-scratch 125M at equal tokens.
4. **Daemon upgrade**: the continuous trainer switches to the new size once growth is verified, keeping the 35M line archived; releases still come from short decay branches.
5. **Milestone 2** release (the larger size), exported to int4 MLX, evaluated, published to Hugging Face (`UmitVice/candela-spark-125m` or the actual size), Observatory artifacts updated (family tree, scaling chart, attention maps for the new size).
6. **Browser runtime spec**: a written design (no implementation yet) for running Spark int4 in the browser (WebGPU or WASM), including weight format, tokenizer, and expected speed, for a later web phase.

## Acceptance

- `make spark-check` passes; ablation, scaling and growth reports committed with plots.
- Milestone 2 published and visible in the Observatory artifacts.
- Report written to `docs/status/p3-spark.md`.
