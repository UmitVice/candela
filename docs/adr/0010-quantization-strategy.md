# 0010 — Quantization strategy: 4-bit by design

- Status: accepted
- Date: 2026-10-23

## Context

The owner wants both models to run in 4-bit by default "without losing intelligence", following Google's practice of training models for 4-bit. Three different techniques are often conflated:

- **Quantization-aware training (QAT)**: the forward pass sees weights rounded to the target low-bit grid (fake quantization, with a straight-through estimator for gradients), so the network learns weights that survive quantization. Google ships Gemma QAT checkpoints produced this way (int4, Q4_0-style blocks), which lose very little quality at 4-bit.
- **Post-training quantization (PTQ)**: quantize a finished model (round-to-nearest, GPTQ/AWQ, MLX DWQ-style distillation). Cheap, but small models in particular lose quality.
- **TurboQuant** (Google Research, ICLR 2026, arXiv 2504.19874): a training-free vector quantizer for the KV cache (random rotation + optimal scalar codebooks), quality-neutral around 3.5 bits per channel. It reduces inference memory for long contexts; it does not change weights or training. As of October 2026 mainline llama.cpp does not support it (community forks and an MLX implementation exist; vLLM does).

QAT does not reduce the memory needed to pretrain from scratch (full-precision master weights and optimizer state are still required); it makes the finished model lossless at 4-bit. Training memory is reduced when fine-tuning on top of an int4 base (QLoRA).

## Decision

- **Candela Pro**: build on Google's Gemma 4 12B QAT int4 weights; QLoRA keeps that base frozen and the adapter unmerged, so served weights are exactly the QAT int4 weights plus a small bf16 adapter. If a merged model is ever released, run a short QAT/distillation pass after merging to restore int4 robustness.
- **Candela Spark**: QAT-native pretraining with int4 fake quantization on MLX's export grid (group size 32) for all block weights; track bf16 and exact-int4 validation loss throughout; the int4 export is the primary artifact. The exact schedule (from step 0 vs after warm-up) is fixed by ADR 0601 and verified by the ablation in `p3-spark`.
- **KV cache**: start with mlx-lm's built-in KV-cache quantization (8-bit) only where measurements show no quality loss; evaluate a TurboQuant implementation for MLX when it is maintained and verifiable, since long-context memory is the remaining large consumer when serving a 12B model on 24 GB.

## Consequences

- 4-bit is the default for every Candela model artifact, and quality claims are backed by side-by-side bf16 vs int4 numbers.
- Spark training pays a modest fake-quantization overhead per step.

## Alternatives considered

- PTQ only: simpler, measurably worse at small scale, not what the owner asked for.
- Ternary/1.58-bit QAT: possible future experiment for Spark; no mainstream runtime support on MLX/llama.cpp grids today.
