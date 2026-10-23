# 0600 — Candela Spark architecture, tokenizer and training spec

- Status: accepted
- Date: 2026-10-23

## Context

ADR 0009 asks for a from-scratch decoder family in pure MLX that starts at about 35M parameters and grows towards about 2B without restarting the family. Every choice that is hard to change later (tokenizer, block layout, parametrisation, checkpoint format) is fixed here. The machine is a shared 24 GB M5 Pro; Spark gets at most 4 GB.

## Decision

**Tokenizer** (frozen for the whole family; SHA-256 in `spark/tokenizer/tokenizer.meta.json`):
- Byte-level BPE, vocabulary 32 768, trained with `tokenizers` on a balanced sample of every source (about 24 MB each, EDGAR ×1.5).
- Pre-tokenizer: Qwen2's split regex, which splits digits one by one, then ByteLevel. llama.cpp knows this regex as `tokenizer.ggml.pre = "qwen2"`, so a GGUF export tokenizes the same way without new llama.cpp code.
- 128 special tokens with ids 0–127: pad, bos, eos, unk, turn markers (`<|start_of_turn|>`, `<|end_of_turn|>`, system/user/assistant/tool roles), tool call/response pairs, think pair, FIM triple, sep/mask/image/audio/doc, plus 104 reserved tokens. Documents are packed as `<|bos|> … <|eos|>`.

**Architecture**: Gemma 3 block layout, chosen so that llama.cpp's `gemma3` graph runs exports unchanged.
- Pre- and post-norm around attention and FFN (four RMSNorms per block, Gemma `1 + w` scale, eps 1e-6), QK-norm over the head dimension, GQA, NeoX-style RoPE, GeGLU (tanh GELU) FFN, no biases, tied embeddings scaled by √d, final RMSNorm.
- Attention pattern: llama.cpp's `gemma3` rule, where layer `i` is global iff `i % 6 == 5`; the other layers use a sliding window. RoPE base 10 000 for local layers and 1 000 000 for global ones (Gemma 3 values). Scale is 1/√head_dim.
- Presets (exact parameter counts include the tied embedding):

| Preset | d | layers | heads / kv | head dim | FFN | context / window | parameters |
|---|---|---|---|---|---|---|---|
| spark-35m | 384 | 12 | 6 / 2 | 64 | 1 280 | 1 024 / 256 | 35 016 576 |
| spark-125m | 640 | 24 | 10 / 2 | 64 | 1 728 | 2 048 / 512 | 124 255 872 |
| spark-350m | 1 024 | 24 | 8 / 2 | 128 | 3 456 | 2 048 / 512 | 351 378 432 |
| spark-1b | 1 536 | 30 | 12 / 4 | 128 | 5 504 | 4 096 / 1 024 | 1 000 141 824 |
| spark-2b | 2 048 | 36 | 16 / 4 | 128 | 7 040 | 4 096 / 1 024 | 2 002 037 760 |

All sizes are deep and thin: d/layers is 32 at 35M and 27–57 above, against 64 for GPT-2 small. Layer counts are multiples of 6, so every size keeps the 5:1 local/global ratio. All matrix dimensions are multiples of 32, which int4 group 32 requires.

**Parametrisation (μP-style)**: hidden matrices are initialised with std 1/√fan_in and trained with Muon. Muon updates are orthogonalised and scaled by √max(1, fan_out/fan_in), so their spectral norm meets the spectral condition for feature learning, and the Muon learning rate carries across widths. The tied embedding and the norm gains use AdamW with a width-independent learning rate. Logits are multiplied by `base_width / d` (base width 384), the μP output multiplier; at 35M it is exactly 1. Larger sizes untie or fold the multiplier before a GGUF export. The p3 scaling study checks transfer with coordinate checks and short sweeps.

**Optimiser**: our own Muon (Nesterov momentum 0.95, quintic Newton–Schulz with 5 steps in bf16, decoupled weight decay 0.01) for every 2D block weight. `mlx.optimizers.Muon` folds weight decay into the gradient before orthogonalisation, where normalisation cancels it. AdamW (β 0.9/0.95, eps 1e-10, no weight decay) for the embedding and norms. Global gradient-norm clip at 1.0. Base learning rates: Muon 0.04, AdamW 0.004, picked by a three-point probe at the base width (250 steps, 8.2M tokens, warmup 60). Validation loss was 5.554 at Muon 0.01 / AdamW 0.001, 5.342 at 0.02 / 0.002 and 5.219 at 0.04 / 0.004, with the int4 gap ≤ 0.13 % at every point. The optimum sits at the probe's upper edge; the p3 sweep should extend the grid upwards and check it at longer horizons.

**Schedule**: warmup–stable–decay. The continuous run warms up for 300 steps and then stays at the stable learning rate indefinitely. Releases come from decay branches that fork a stable checkpoint, take the 1−√ shape down to 0 over about 15–20 % of the parent's steps, and leave the main run untouched.

**Precision and step**: fp32 master weights and optimizer state, bf16 compute (weights cast, or fake-quantised, to bf16 per step), fp32 loss. Micro-batch 2 × 1 024 tokens with 16 accumulation steps gives 32 768 tokens per optimizer step. Micro-step and update are both compiled with `mx.compile`. Peak memory is 2.6 GB at about 31k tokens/s on the M5 Pro; micro-batch 8 needs 8 GB, over the Spark budget.

**Checkpoints**: `candela.spark.checkpoint.v1`, a directory holding `model.safetensors` (fp32), `optimizer.safetensors`, `state.json` (step, tokens, data cursor, RNG, schedule, configs, tokenizer hash, data version, milestones) and `manifest.json` (SHA-256 per file). It is written to a temp directory, fsynced, renamed, and the `latest` pointer is replaced atomically. Resume verifies the hashes and falls back to older checkpoints. The trainer saves every 10 minutes, on SIGTERM/SIGINT and on long pauses. It keeps the last 3 checkpoints and every 250M-token milestone.

**Data loading**: each source is a frozen shuffled list of documents over memory-mapped `uint16` shards. Optimizer row `r` picks a source from `splitmix64(seed, r)`, weighted by tokens × mixture multiplier, and takes that source's next 1 025-token window. The cursor (rows plus a per-source window counter) is the entire data position, so resume is exact. Repeated epochs shift window boundaries by `epoch · 7919 mod 1024`.

## Consequences

- One code path serves every size; growing means a new preset plus a growth operator (depth duplication or width expansion from a trained checkpoint) in later phases, with the same tokenizer and checkpoint format.
- Gemma 3 compatibility gives llama.cpp support for free, but any change to the block layout means dropping GGUF portability or writing a llama.cpp graph.
- Micro-batch 2 keeps Spark well under its memory budget at a 3 % throughput cost.

## Alternatives considered

- Llama-style pre-norm only with SwiGLU: simpler, but drifts from the Gemma 4 family the owner targets and loses the sandwich-norm stability.
- 50k–64k vocabulary: costs 37–50 % of the 35M budget in embeddings; 32k is the usual small-model compromise (SmolLM uses 49k at 135M).
- Standard μP with AdamW everywhere: well understood, but Muon gives about 1.3–2× better sample efficiency at small scale, and spectral scaling gives the same transfer property.
- Cosine schedule: needs a fixed horizon, which a continuous run does not have.
