# 0003 — Candela Pro: Gemma 4 12B QAT with QLoRA on Apple Silicon

- Status: accepted (probe numbers and guard settings filled in by `p1-ml`, 2026-10-24)
- Date: 2026-10-23 (revised the same day by owner decision)

## Context

The owner asked for an 8–12B open model "like Qwen3.8 8B or Gemma 4 12B", trained locally for free on an Apple M5 Pro with 24 GB of unified memory shared with other work, and explicitly asked that it be built on Google's 4-bit quantization-aware-trained (QAT) release so that 4-bit is the default with no loss of intelligence. Research on 2026-10-23:

- Qwen3.8 has open weights only at 27B and above; no 8B exists. Qwen3.5 small models are currently impractical to train on MLX/M5 Pro (token-by-token Gated-DeltaNet training, an open wrong-gradient bug in MLX's fast backward kernel on M5 Pro).
- Gemma 4 (Apache-2.0) ships a dense 12B instruction model with native function calling, a system role and a thinking mode, plus QAT checkpoints whose int4 quantization keeps near-bf16 quality.
- The owner already has, locally and read-only for Candela: `~/models/gemma-4-12b-it-qat-mlx-q4` (MLX affine 4-bit, group size 32, 7.0 GB), `~/models/gemma-4-12b-it-qat-unquantized` (QAT weights in bf16, 22 GB) and `~/models/gemma-4-12b-it-qat/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf` (6.3 GB). Architecture: `gemma4_unified`, 48 layers, hidden 3840, 16 query / 8 KV heads, 262 144 vocabulary, sliding window 1024.

## Decision

- **Candela Pro = Gemma 4 12B instruction model on Google's QAT int4 weights**, fine-tuned with QLoRA: the QAT int4 base stays frozen and exactly as Google trained it; only bf16 LoRA adapters are learned; adapters are never merged into the int4 weights. Serving loads the same int4 base plus the adapter, so 4-bit is the default and the base keeps its QAT quality.
- Memory techniques: supervised-positions-only LM head in a custom loss (the 262k vocabulary makes full-sequence logits expensive), gradient checkpointing, MLX memory and cache limits, the resource guard and the GPU lease protocol.
- Portability: the MLX adapter is converted to PEFT layout and then to a GGUF LoRA (`convert_lora_to_gguf.py`), applied with `llama-server --lora` on the QAT Q4 GGUF.
- There is no lite chat tier (owner decision). The from-scratch Candela Spark family (ADR 0009) is the long-term small/on-device line.

## Probe (filled in by `p1-ml`)

Measured by `p1-ml` on 2026-10-23 (Apple M5 Pro, 24 GB, mlx 0.32.4 / mlx-lm 0.32.2): 20 optimizer steps (batch 1, no accumulation) on the 400 longest `d0.1` samples that fit 2 048 tokens, gradient checkpointing on adapted layers, frozen layers without backward, supervised-positions-only LM head in 64-position chunks. The frozen QAT int4 base alone occupies 7.44 GB (11.9 B parameters).

| Setting | Peak memory @2048 | Tokens/s | Tool-call parsing | Notes |
|---|---|---|---|---|
| LoRA rank 16, top 16 layers (32–47, 21.9 M trainable) | 10.46 GB | 332 | 3 687 / 3 687 tool-call turns render and parse back exactly (Gemma 4 template + mlx-lm `gemma4` parser) | single-step peaks: 9.45 GB @1 024, 12.50 GB @4 096 |
| LoRA rank 16, top 24 layers (24–47, 32.8 M trainable) | 10.77 GB | 271 | same template | single-step peak 13.04 GB @4 096 |

No configuration that trains on realistic sequence lengths stays ≤ 9 GB: the frozen base already takes 7.44 GB and activation memory (attention backward) grows with sequence length, not with the number of supervised positions. **Chosen: rank 16 on the top 16 layers at `max_seq_length` 2 048 with a 10.5 GB training budget** (`trainBudgetGb` in `ml/configs/models.yaml`). The 24-layer variant costs only +0.3 GB but ~18 % throughput; `p2-train` may widen it. 4 096-token training (≥ 12.5 GB) is too heavy for the shared machine; see ADR 0400.

Guard settings for Candela Pro training, evaluation and export (owner decision, 2026-10-23: "start Gemma training at about 11 GB free and pause only when macOS reports memory pressure"): start or resume when ≥ 11 GB is available (free + inactive + purgeable + speculative pages); pause — checkpoint and release the model — only when the kernel memory-pressure level (`kern.memorystatus_vm_pressure_level`) is warn or critical, not on swap growth alone; resume after the level has been normal for 2 minutes with ≥ 11 GB available. GPU lease reservations (`contracts/gpu-lease.md` v1.1) and the foreign-training check stay in force (`candela_lab.resources.PRO_POLICY`).

## Consequences

- Training is slower than with an 8B model and pauses when the machine is busy; checkpoints make pauses cheap.
- A merged single-file model would require a short QAT/distillation pass after merging to recover int4 robustness; deferred until there is a reason to ship a merged model.

## Alternatives considered

- Qwen3-8B / Granite 4.2 8B: easier memory fit, but not the owner's choice and no official QAT int4 release to build on.
- Merging the adapter and post-training-quantizing the result: loses the QAT advantage the owner asked for.
- Full fine-tuning: impossible within the memory budget.
