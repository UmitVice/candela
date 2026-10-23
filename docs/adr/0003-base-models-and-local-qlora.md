# 0003 — Base models and local QLoRA on Apple Silicon

- Status: proposed (accepted by `p1-ml` once the probe numbers below are filled in)
- Date: 2026-10-23

## Context

The owner asked for an 8–12B open model "like Qwen3.8 8B or Gemma 4 12B", trained locally for free on an Apple M5 Pro with 24 GB of unified memory that is shared with other work (often a 9 GB `llama-server`). Research on 2026-10-23:

- Qwen3.8 has open weights only at 27B and above; no 8B exists.
- Qwen3.5 (0.8–9B) uses Gated-DeltaNet layers that mlx-lm trains token-by-token with high memory (mlx-lm #1956, #1206), and MLX's fast backward kernel has an open wrong-gradient bug on M5 Pro for 16 key heads (mlx #4614).
- Gemma 4 (Apache-2.0) has a dense 12B with native function calling, system role and thinking; QAT checkpoints quantize to 4-bit with little loss; its 262k vocabulary makes full-sequence logits expensive.
- Qwen3-8B and Qwen3-1.7B are dense, Apache-2.0, mature in mlx-lm, and have prebuilt WebLLM libraries.
- mlx 0.32.4 / mlx-lm 0.32.2 support LoRA, QLoRA and DoRA for `gemma4`, `qwen3`, `granite`; core mlx-lm is SFT-only (mlx-lm-lora adds DPO/ORPO/GRPO).

## Decision

- Pro: Gemma 4 12B instruction model, quantized to MLX 4-bit from the QAT unquantized checkpoint; fallback Qwen3-8B.
- Lite: Qwen3-1.7B; fallback Granite 4.2 3B.
- QLoRA with mlx-lm through a Python wrapper that sets MLX memory limits, plugs in the resource guard, and replaces the loss with a supervised-positions-only LM head.
- Pro adapters are served as MLX adapters and exported as PEFT → GGUF LoRA for llama.cpp on the official QAT GGUF; lite is fused and exported to GGUF Q4_K_M and later MLC.

## Selection probe (filled in by `p1-ml`)

| Candidate | Fast-eval summary (base) | Probe peak memory @2048 | Probe tokens/s | Tool-call parsing | Verdict |
|---|---|---|---|---|---|
| Gemma 4 12B | | | | | |
| Qwen3-8B | | | | | |

Keep Gemma 4 12B if its peak is ≤ 9 GB and tool calls parse reliably; otherwise switch to Qwen3-8B and update `ml/configs/models.yaml`, the master plan and this ADR.

## Consequences

- The pro model is the owner's requested family and the strongest that fits, at the cost of slower training (pauses expected while the machine is busy).
- Mixed families (Gemma pro, Qwen lite) require per-family chat templates and tool-call parsers in the worker and in data rendering; the canonical data format stays OpenAI-style messages.

## Alternatives considered

- Qwen3.5-9B: best scores in its class but currently impractical and unreliable to train on MLX/M5 Pro.
- IBM Granite 4.2 8B: comfortable memory fit, weaker benchmarks and less recognisable.
- Ministral 3 8B/14B: viable; no advantage over the chosen pair for this domain.
- Cloud GPUs: cost money or new accounts.
- Full fine-tuning: impossible within the memory budget.
