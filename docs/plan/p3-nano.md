# Phase 3 · ML — Candela-Nano, a language model built and trained from scratch (`p3-nano`)

- Area you own: `ml/nano/**` (a separate uv project or a subpackage of `ml/`, your call via ADR), `make/ml.mk` (nano targets only), `apps/web/public/observatory/nano/**` (artifacts only), `docs/status/p3-nano.md`, new ADRs.
- Runs in parallel with `p3-observatory` and `p3-deploy`. The resource guard arbitrates the GPU with the live worker.
- Inputs: `CLAUDE.md`, master plan, `ml/` Lab utilities (resource guard, run logging), `contracts/observatory.md`.

## Goal

Show first-principles mastery next to the fine-tuned product model: a small decoder-only transformer whose tokenizer, architecture, training loop and evaluation are written from scratch in MLX (no `mlx-lm` model classes, no Hugging Face model code), pretrained on financial filings, with a mini scaling study and real attention data for the Observatory.

## Deliverables

1. Corpus: EDGAR-CORPUS (Apache-2.0) 10-K sections (business, risk factors, MD&A), cleaned (boilerplate, tables, page artefacts), deduplicated, split by company and year into train/validation; ~0.5–1 B tokens available, versioned manifest and data card.
2. Tokenizer: byte-level BPE (16k vocabulary) trained with the `tokenizers` library on the training split; report compression (bytes/token) against GPT-style baselines.
3. Model (pure MLX): token embeddings (tied output), RoPE, RMSNorm pre-norm, grouped-query attention with causal masking via a fused attention op where available, SwiGLU MLP, configurable depth/width; parameter count printed.
4. Training loop: AdamW with decoupled weight decay, cosine schedule with warm-up, gradient clipping, gradient accumulation, bf16 where stable, deterministic data loader over memory-mapped token shards, checkpoints, resume, resource-guard integration, metrics JSONL (loss, perplexity, tokens/s, LR, grad norm, peak memory).
5. Mini scaling study: three sizes (≈ 5M, 15M, 35M parameters) trained with a compute-proportional token budget (≈ 20 tokens per parameter); validation loss vs compute plot and a fitted power law, written up honestly in `ml/nano/REPORT.md`.
6. Evaluation: held-out perplexity, sample completions for finance prompts (fixed seeds), and a comparison against the same prompts on a public small model of similar size, if one fits the license.
7. Observatory artifacts under `apps/web/public/observatory/nano/`: architecture, training curves for all three sizes, and attention maps (every layer and head) for 6–8 curated finance sentences from the 35M model; schemas proposed in `docs/status/p3-nano.md` for the web phase to render.
8. Export the final weights (fp16 safetensors + tokenizer + config) to Hugging Face `UmitVice/candela-nano` with a model card; stretch: a self-contained TypeScript/WebGPU or WASM-free JS forward pass spec so the web app can run Nano in the browser in a later phase.

## Acceptance

- `make ml-check` passes; runs complete under the resource guard; total GPU wall time ≤ 12 hours.
- Validation perplexity decreases monotonically with model size; scaling plot and report committed.
- Hugging Face repo published; Observatory artifacts committed.
- Report written to `docs/status/p3-nano.md`.
