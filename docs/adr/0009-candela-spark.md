# 0009 — Candela Spark: a from-scratch, QAT-native model family

- Status: accepted
- Date: 2026-10-23

## Context

Fine-tuning Gemma 4 12B (Candela Pro) shows how to adapt a frontier open model. The owner also wants first-principles depth: a model whose tokenizer, architecture and training loop are built from zero, trained "knowing it will run in 4-bit", that can grow over time towards a Gemma 4 E2B-class model as far as a 24 GB laptop allows. Pretraining a 12B model from scratch is out of reach (~10²⁴ FLOPs and >128 GB of optimizer state), but a well-designed small model trained continuously is achievable and can scale through deliberate engineering.

## Decision

- Build **Candela Spark** in `spark/`, a decoder-only family in pure MLX with a frozen tokenizer and a Gemma-style architecture, starting at ≈ 35M parameters.
- Train it **quantization-aware** from the beginning: int4 weights (group size 32, MLX's export grid) via fake quantization and a straight-through estimator; the int4 export is the primary artifact.
- Design for growth: μP-style parametrization for hyperparameter transfer, warmup–stable–decay schedules for continuous training with releasable decay branches, size presets up to ≈ 2B, and growth operators (depth/width expansion from trained checkpoints) planned for later phases.
- Run continuously as a polite background daemon with exact-resume checkpoints, the memory guard and the GPU lease protocol at the lowest priority (milestone runs slightly higher).
- Use only reputable, permissively licensed, pinned and checksummed data; general educational text first, SEC filings as the domain share.
- Long term, Spark is Candela's on-device line: once a size is strong enough, it gets chat/tool-use fine-tuning and can run in the browser.

## Consequences

- Two very different training regimes coexist on one machine; the lease protocol keeps Candela Pro and live inference ahead of Spark.
- QAT costs some throughput (fake-quantization overhead) in exchange for a lossless int4 model and a measurable bf16-vs-int4 gap that becomes a showcase metric.

## Alternatives considered

- Post-training quantization only: simpler, but loses quality at small sizes and does not meet the owner's requirement.
- Ternary/1.58-bit (BitNet-style) training: more aggressive and research-heavy; int4 matches MLX and llama.cpp runtimes directly.
- Fine-tuning an existing small model instead: would not demonstrate building a model from scratch.
