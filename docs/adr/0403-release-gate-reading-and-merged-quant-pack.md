# 0403 — Release-gate reading for v0.1 and the merged Candela Pro quant pack

- Status: accepted
- Date: 2026-10-27

## Context

The master plan's gate asks for "+10 points" of grounding and tool-choice F1 over the base and for no classic suite or IFEval drop above 3 points. The QAT base already grounds 93.9 % of the data numbers in its tool-use answers on the gateway-executed held-out set, so a +10-point grounding gain is arithmetically impossible. Every evaluation suite is small (100–500 items), so a 3-point difference is often within sampling noise. The owner also asked for a merged single-file model family next to the unmerged adapter (GGUF Q4_K_M/Q5_K_M/Q6_K/Q8_0, MLX 4-bit/8-bit). ADR 0003 kept the release unmerged because merging and re-quantizing loses part of Google's QAT int4 quality.

## Decision

- **Gate as applied** (`lab eval gate`, `candela_lab/eval/report.py`), on full-mode reports of the base and the tuned model with identical items:
  - Tool-choice F1 must gain at least 10 points.
  - Grounding must gain 10 points or, when the base is already above 0.90, the ungrounded share must at least halve.
  - FPB, FiQA-SA, headlines, FinQA, ConvFinQA, TAT-QA, FinanceBench and IFEval must not drop by more than 3 points.
  - A manual review of 20 tool-use answers must find no fabricated numbers.
  - The gate table prints two unpaired binomial standard errors next to each delta, so readers can tell signal from noise. The pass rule itself stays the strict 3 points.
- **Merged quant pack** (`lab export merged`, `candela_lab/export/merge.py`):
  - The adapter delta (`scale · (A·B)ᵀ`, float32) is added to the bf16 QAT reference in a copy-on-write copy of the checkpoint, one tensor at a time through mmap. Memory stays under 1 GB and the 22 GB checkpoint is never loaded.
  - Rounding the sum to bf16 keeps the delta with ≈ 11 % relative error (cosine 0.99 with the exact delta), far below the later quantization error.
  - GGUF goes through llama.cpp `convert_hf_to_gguf.py` (bf16) and `llama-quantize`. MLX goes through `mlx_lm.convert` (4-bit group 32, 8-bit group 64).
  - The cards state that these are merged and post-training quantized: Q4 variants lose part of the QAT advantage. The unmerged adapter on the QAT int4 base stays the reference release. A short QAT/distillation restore after merging is a later step.

## Consequences

- Grounding is judged by the error it removes, not by an impossible absolute gain.
- Users without LoRA support get single-file models, labelled with their trade-off.

## Alternatives considered

- Merging into the dequantized int4 weights: would bake the int4 grid into bf16 and then quantize twice.
- Publishing only the adapter: simpler, but not what the owner asked for.
