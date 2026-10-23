# Candela — Master plan

Owner: Ümit Vice · Director: planning session · Started: 2026-10-23

## 1. Vision

Candela is a portfolio-grade, end-to-end AI product that shows what a senior AI engineer does: choose and adapt an open-weight model for a domain, build the data and evaluation machinery around it, serve it efficiently and safely, and ship a polished product that makes the model's behaviour visible.

- **Domain**: equity research on US-listed stocks. The model calls deterministic tools for every number and writes balanced, cited analyses. Later it consumes data from the owner's Vaniras platform (forecasts with P10/P50/P90 bands, scores, fundamentals for ~1 000 stocks).
- **Product**: *Candela Terminal*, a Bloomberg-inspired, mobile-first PWA (default view), and *Candela Observatory*, a 3D design view of the model (live layer activity, logit lens, LoRA adaptation across checkpoints, embedding galaxy, training and evaluation dashboards).
- **Engineering story**: zero cost, a shared 24 GB laptop, no hosted CI, honest evaluation, strong security hygiene.
- **Why fine-tune instead of pretraining an 8–12B model**: models like Gemma and Qwen are pretrained on 15–36 trillion tokens on thousands of GPUs; from scratch at that scale needs ~10²⁴ FLOPs and >128 GB of optimizer state, centuries on this laptop. Candela therefore adapts an open model with QLoRA for the product, and separately builds **Candela-Nano** (≈ 35M parameters) entirely from scratch — tokenizer, architecture, training loop, scaling study — to demonstrate first-principles depth.

## 2. Owner constraints (non-negotiable)

- Go backend, Python for AI, Angular frontend (responsive PWA); modern UI and visualisation libraries.
- Fine-tune an open-weight 8–12B model locally for free, without exhausting the machine; the owner keeps working on other projects.
- Public GitHub repository and Netlify site; regular English Conventional Commits; minimal comments; no tests until the owner asks.
- LTS / long-supported, mutually compatible versions (pinned in `CLAUDE.md`).
- Strict secret hygiene. No GitHub Actions. Few Netlify production deploys.
- The owner is away: the Director decides; phase sessions ask the Director, never the owner.

## 3. Architecture

See the diagram in `README.md` and ADRs 0001–0007.

| Component | Responsibility |
|---|---|
| `apps/web` | Terminal and Observatory; WebSocket chat (SSE locally), replay mode, PWA, IndexedDB history |
| `services/gateway` | Public API (`contracts/api.md`), chat orchestration and tool loop, deterministic market tools, rate limits, bounded queue, worker hub, OpenAI-compatible fallback upstream, internal tool API, metrics |
| `services/worker` | MLX inference for pro and lite models, lazy load and idle unload, admission control, telemetry, worker protocol client, OpenAI-compatible HTTP for local use |
| `ml` | Candela Lab: data, synthetic traces through the gateway's tool layer, resource-guarded LoRA training, evaluation, export, publishing, Observatory artifacts |
| `deploy` | Live supervisor (gateway + worker + cloudflared + endpoint Gist), Netlify rendering, operations |

Production topology (ADR 0002): static PWA on Netlify; gateway, worker and a Cloudflare quick tunnel on the owner's Mac; endpoint published to a public Gist; replay mode when the Mac is offline; models on Hugging Face.

## 4. Model strategy

Findings (2026-10-23): "Qwen3.8 8B" does not exist (Qwen3.8 ships 27B and larger only). Qwen3.5 small models train poorly on MLX today (Gated-DeltaNet runs token-by-token in training with high memory, and an open MLX bug yields wrong gradients on M5 Pro for 16 key heads). Gemma 4 is Apache-2.0 and includes a dense 12B with native function calling, a system role and a thinking mode; the owner already runs it locally.

| Tier | Default base | Fallback | Serving | Why |
|---|---|---|---|---|
| **Pro** | `google/gemma-4-12B-it` (start from the QAT unquantized checkpoint, quantized to MLX 4-bit) | `Qwen/Qwen3-8B` | MLX worker on the Mac (base 4-bit + adapter) | the owner's choice, strongest open model that can fit; Apache-2.0 |
| **Lite** | `Qwen/Qwen3-1.7B` | `ibm-granite/granite-4.2-3b` | MLX on the Mac when pro cannot be admitted; later in the browser via WebLLM (prebuilt `q4f16_1` library exists) | small, dense, mature MLX support, hybrid thinking, Hermes-style tool calls |

**Selection protocol** (`p1-ml`): run the fast baseline evaluation for both pro candidates and a 20-step training probe at the production sequence length under the resource guard. Keep Gemma 4 12B if its probe peak stays ≤ 9 GB with the memory techniques below and tool-call parsing works; otherwise switch to Qwen3-8B. Record the measurements in ADR 0003.

**Fine-tuning method**: QLoRA with mlx-lm (LoRA on the 4-bit base), rank 16, scale 2.0, dropout 0.05, all linear projections of the top 16 layers first (widen if memory allows), AdamW, cosine decay with warm-up, batch 1 × gradient accumulation 8, `max_seq_length` 2048, gradient checkpointing, prompt masking (one sample per assistant turn because only the final message is supervised). Memory techniques: supervised-positions-only LM head in a custom loss (compute vocabulary logits only where the mask is 1, which matters for Gemma's 262k vocabulary), MLX memory and cache limits, sequence packing off.

**Export**: pro adapters stay MLX for serving; for portability convert the adapter to PEFT layout and then to a GGUF LoRA with llama.cpp's `convert_lora_to_gguf.py`, applied at runtime on Google's official QAT GGUF (`--lora`), because fusing a 12B model in bf16 needs more memory than the machine can spare. Lite is fused (de-quantized) and exported to GGUF Q4_K_M, and later to MLC `q4f16_1` for the browser.

**Reasoning**: training traces are in non-thinking mode; the base model's native thinking remains available and is toggled at inference (`options.reasoning`).

## 5. Data strategy

Published weights must not inherit non-commercial terms, so training data is restricted to permissive sources; non-commercial sets are used for evaluation only.

| Purpose | Source | License | Use |
|---|---|---|---|
| Candela tool traces | synthetic, generated through the gateway's internal tool API on the price snapshot | own (Apache-2.0) | core of training; published as a dataset |
| Agentic finance | `nvidia/Nemotron-SFT-Agentic-Finance-v1` (7 878 SEC-tool runs) | OpenMDW-1.1 | train, split per assistant turn, ≤ 2 048 tokens |
| General function calling | ToolACE, Hermes Function Calling v1 | Apache-2.0 | train, includes "no tool needed" cases |
| Numeric reasoning | FinQA, ConvFinQA (MIT), TAT-QA (CC-BY-4.0) | permissive | train splits for training, test splits for evaluation |
| General retention | a permissive general SFT slice (for example `HuggingFaceTB/smoltalk`) | Apache-2.0 | ~1 k samples against forgetting |
| Sentiment / headlines | Financial PhraseBank, FiQA-SA, headline sets | non-commercial or unclear | evaluation only |
| Grounded QA | FinanceBench, financial-qa-10K | non-commercial or unclear | evaluation only |
| Filings text | EDGAR-CORPUS | Apache-2.0 | v0.2: source for grounded QA generation |

**v0.1 mix (~12 k supervised samples)**: 6 k Candela tool-trace turns (≥ 20 % multi-turn follow-ups, ≥ 10 % failure, unknown-company and personal-advice cases), 1.5 k Nemotron agentic finance, 1 k general function calling, 2.5 k numeric reasoning, 1 k general retention. Avoid FinGPT, Sujet-Finance-Instruct and finance-alpaca for training (license contamination or bundled test splits).

**Quality controls**: normalisation to OpenAI-style messages, exact and MinHash deduplication, 13-gram decontamination against every evaluation set, PII scrubbing, token-length caps, per-example source and license metadata, versioned manifests and data cards.

**Vaniras (later)**: once the owner provides an export or API, add the `vaniras` provider in the gateway and generate traces that interpret real P10/P50/P90 forecasts and Vaniras scores; the tool result shapes stay fixed, so the serving stack does not change.

## 6. Training on a shared laptop

- Budget: training peak ≤ 9 GB, inference ≤ 6 GB (pro 12B serving may take ~7.5 GB; admission control falls back to lite when headroom is short).
- Resource guard: start only with budget + 3 GB available; pause (checkpoint, release) when available < 1.5 GB or swap grows > 1 GB in 5 minutes; resume after 10 minutes of recovery. All pauses are logged and shown in the Observatory.
- `caffeinate -i nice -n 10`, background execution, checkpoints every 100–200 optimizer steps.
- Order: lite first (fast, small), then pro. If the pro run cannot start within 12 hours because the machine is busy, release lite as v0.1 and keep the pro run queued.

## 7. Evaluation and release gates

Deterministic fast suite (≤ 30 min per model; thinking off; temperature 0): FPB 500 (macro-F1), FiQA-SA (weighted F1), headlines 500 (F1), FinQA/ConvFinQA/TAT-QA 300 each (numeric exact match with tolerance), FinanceBench 150, Candela `tool_use` 300 held-out conversations (tool-choice F1, argument validity, grounding rate = share of numbers in the answer found in tool outputs), held-out loss, IFEval 200 as a forgetting check.

Release gate for a tuned model vs its base: `tool_use` grounding and tool-choice F1 improve by ≥ 10 points; no classic suite drops by more than 3 points; IFEval drops by no more than 3 points; manual review of 20 random answers finds no fabricated numbers.

## 8. Product experience

- Terminal (default): dense dark UI, amber "candle flame" accent, mono numbers, streaming reasoning and tool lines, financial cards (quote, candlesticks, indicators, fundamentals, forecast fan), watchlist, command palette, slash commands, replay mode, installable PWA.
- Observatory (opened from the top bar): Architecture Tower with live telemetry, Fine-tune Field across checkpoints, Embedding Galaxy, Lab HUD; split view with the terminal on wide screens.
- Disclaimers everywhere it matters; no personalized advice.

## 9. Security and privacy

Secrets only in git-ignored `.env` files; pre-commit gitleaks and file-type guards; GitHub secret scanning and push protection; CORS allowlist; rate limits; bounded inputs; tool results treated as data; sanitized Markdown; internal routes on a non-tunnelled listener; worker token auth with constant-time comparison; no message content in logs; feedback transcripts stored only with explicit consent; owner email never sent to third parties.

## 10. Phases

| Batch | Sessions (parallel) | Depends on | Milestone |
|---|---|---|---|
| 1 | `p1-web`, `p1-gateway`, `p1-ml` | contracts | terminal shell live in replay mode; gateway with tools and snapshot; Lab pipeline, baselines, model selection |
| 2 | `p2-train`, `p2-worker`, `p2-web` | batch 1 | Candela v0.1 models on Hugging Face; MLX worker; terminal wired to the gateway with rich cards |
| 3 | `p3-observatory`, `p3-deploy`, `p3-nano` | batch 2 | Observatory live; site chatting with the pro model through the tunnel; real recordings; Candela-Nano trained from scratch with a scaling study |
| 4 | `p4-polish` | batch 3 | portfolio polish, README, case study, release v0.1.0 |
| 5+ | `p5-train-v02`, `p5-edge-lite`, `p6-vaniras` | batch 4 / owner data | better data and preference tuning from feedback; in-browser lite model; Vaniras integration |

Each brief lives in `docs/plan/<phase>.md`; each session reports in `docs/status/<phase>.md`. The Director verifies every batch (status reports, commits, a smoke run) before starting the next.

## 11. Optional owner actions (never blocking)

- `SEC_USER_AGENT` with a contact email to enable live SEC fundamentals.
- A free key for an end-of-day price API for fresher data than the snapshot.
- A stable hostname (named Cloudflare tunnel on an owner domain such as `candela.umitvice.com`, or Dev Tunnels login).
- Installing the LaunchAgent so Candela goes live automatically at login.
- Vaniras data export or API access.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Machine busy (owner's 9 GB llama-server, other agents) | resource guard, lite-first ordering, pausable runs, admission control |
| Gemma 4 12B exceeds memory | supervised-positions-only loss, fewer adapted layers, fallback to Qwen3-8B |
| Quick tunnel instability | supervisor restarts, Gist discovery, replay mode, documented upgrade paths |
| Stale snapshot data | `asOf` everywhere, Vaniras or keyed provider later |
| Netlify credit exhaustion | ≤ 1 production deploy per phase, no Netlify builds, weights never on Netlify |
| License contamination | permissive-only training sources, per-example license metadata, data card |
