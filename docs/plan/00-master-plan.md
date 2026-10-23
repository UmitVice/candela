# Candela — Master plan

Owner: Ümit Vice · Director: planning session · Started: 2026-10-23 · Revised: 2026-10-23 (two-model plan, QAT, hardened exposure)

## 1. Vision

Candela is a portfolio-grade, end-to-end AI product that shows what a senior AI engineer does: adapt a frontier open model to a domain, build a model from first principles, own the data and evaluation machinery, serve models efficiently and safely, and ship a polished product that makes model behaviour visible.

- **Domain**: equity research on US-listed stocks. The product model calls deterministic tools for every number and writes balanced, cited analyses. Later it consumes data from the owner's Vaniras platform (forecasts with P10/P50/P90 bands, scores, fundamentals for ~1 000 stocks).
- **Two models**:
  - **Candela Pro** — Gemma 4 12B on Google's 4-bit QAT weights, fine-tuned with QLoRA: the model visitors chat with.
  - **Candela Spark** — a decoder-only family built entirely from scratch, trained 4-bit-aware from step one, growing from ≈ 35M parameters towards a Gemma 4 E2B-class model as far as the hardware allows.
- **Product**: *Candela Terminal*, a Bloomberg-inspired, mobile-first PWA (default view), and *Candela Observatory*, a 3D design view (live layer activity and logit lens of Pro, LoRA adaptation across checkpoints, embedding galaxy, Spark's training and attention maps).
- **Engineering story**: zero cost, a shared 24 GB laptop, no hosted CI, honest evaluation, quantization-aware everything, and a public endpoint on a personal laptop that is safe by design.
- **Why not pretrain a 12B model from scratch**: Gemma- and Qwen-class models are pretrained on 15–36 trillion tokens on thousands of GPUs (~10²⁴ FLOPs, >128 GB of optimizer state for 8B parameters) — centuries on this laptop. Candela therefore adapts Gemma for the product and builds Spark from scratch to demonstrate first-principles depth.

## 2. Owner constraints (non-negotiable)

- Go backend, Python for AI, Angular frontend (responsive PWA); modern UI and visualisation libraries.
- Train locally for free without exhausting the machine; the owner keeps working on other projects.
- Both models are built around 4-bit: Pro on Google's QAT checkpoint, Spark with QAT from scratch.
- Spark trains continuously on the Mac and survives shutdowns and network loss.
- Training data only from safe, reputable, current sources with verified integrity.
- Visitors can only talk to the model: no path to files, credentials, other services or the LAN.
- Public GitHub repository and Netlify site; regular English Conventional Commits; minimal comments; no tests until the owner asks.
- LTS / long-supported, mutually compatible versions (pinned in `CLAUDE.md`). No GitHub Actions. Few Netlify production deploys.
- The owner is away: the Director decides; phase sessions ask the Director, never the owner.

## 3. Architecture

See the diagram in `README.md` and the ADRs.

| Component | Responsibility |
|---|---|
| `apps/web` | Terminal and Observatory; WebSocket chat (SSE locally), replay mode, PWA, IndexedDB history |
| `services/gateway` | Public API (`contracts/api.md`), chat orchestration and tool loop, deterministic market tools with an egress allowlist, rate limits, bounded queue, worker hub, internal tool API on a loopback-only listener, metrics |
| `services/worker` | MLX inference for Candela Pro (QAT int4 base + adapter), lazy load and idle unload, admission control, GPU lease, telemetry, worker protocol client |
| `ml` | Candela Lab for Pro: data, synthetic traces through the gateway's tool layer, guarded QLoRA training, evaluation, export, publishing, Observatory artifacts |
| `spark` | Candela Spark: tokenizer, from-scratch MLX architecture, QAT pretraining daemon, evaluation, export, scaling |
| `deploy` | Live supervisor (gateway + worker + cloudflared + endpoint Gist), Seatbelt sandboxes, kill switch, Netlify rendering, recordings, operations |

Production topology (ADR 0002): static PWA on Netlify; gateway, worker and a Cloudflare quick tunnel on the owner's Mac; endpoint published to a public Gist; replay mode when the Mac is offline or busy; models on Hugging Face. Security model: ADR 0008.

## 4. Candela Pro — Gemma 4 12B QAT + QLoRA

Findings (2026-10-23): "Qwen3.8 8B" does not exist; Qwen3.5 small models are currently impractical to train on MLX/M5 Pro. Gemma 4 12B (Apache-2.0) has native function calling, a system role, a thinking mode and official QAT checkpoints. The owner already has the QAT weights locally (ADR 0003): `~/models/gemma-4-12b-it-qat-mlx-q4` (MLX affine int4, group 32), the bf16 QAT reference, and the QAT Q4 GGUF.

- **Method**: QLoRA — the QAT int4 base stays frozen exactly as Google trained it; bf16 LoRA adapters (rank 16, scale 2.0, dropout 0.05, top layers sized by the `p1-ml` probe) are learned with AdamW, cosine decay with warm-up, batch 1 × accumulation 8, sequences up to 2048, gradient checkpointing, prompt masking (one sample per supervised assistant turn) and a supervised-positions-only LM head (262k vocabulary).
- **Serving**: int4 QAT base + unmerged adapter in the MLX worker → 4-bit by default with the base's QAT quality intact. Portability: adapter → PEFT → GGUF LoRA on the QAT Q4 GGUF.
- **Reasoning**: training traces use non-thinking mode; the base's native thinking stays available at inference.
- **Later**: a merged single-file release would get a short QAT/distillation pass after merging so int4 robustness is restored; KV-cache quantization for long contexts if it proves lossless in our evals.

## 5. Candela Spark — from scratch, 4-bit native

- **Family**: Gemma-style decoder (sandwich RMSNorm, QK-norm, GQA, RoPE with local/global bases, interleaved sliding-window/global attention, gated FFN, no biases, tied embeddings), size presets ≈ 35M → 125M → 350M → 1B → 2B; deep-and-thin at small sizes. Frozen byte-level BPE tokenizer (≈ 32k vocabulary, digit splitting, reserved chat/tool tokens) shared by every size.
- **QAT**: int4 fake quantization (group 32, the exact MLX export grid) with a straight-through estimator on all block weights; validation loss tracked for bf16 master weights and the exact int4 export side by side.
- **Scaling discipline**: μP-style parametrization for hyperparameter transfer, Muon for hidden matrices + AdamW for the rest, warmup–stable–decay schedule (continuous stable phase, releases from short decay branches), growth from trained checkpoints when moving up a size.
- **Continuous operation**: a LaunchAgent daemon with atomic exact-resume checkpoints every 10 minutes and on shutdown, no network during training, memory guard, GPU lease at the lowest priority, pauses on battery or thermal pressure.
- **Milestones**: M1 = 35M after ≈ 1–2 hours of GPU training (coherent English, finance vocabulary, int4 ≈ bf16); then steady growth in tokens, then sizes. Each milestone is published to Hugging Face and shown in the Observatory.

## 6. Data strategy

Every source must be reputable and permissive; every download is pinned to a Hugging Face commit revision (or an official URL with a published checksum) and verified by SHA-256; only parquet/JSON/CSV formats; no dataset scripts, pickles or remote code.

**Candela Pro (SFT)** — published weights must not inherit non-commercial terms, so training uses permissive sources only:

| Purpose | Source | License | Use |
|---|---|---|---|
| Candela tool traces | synthetic, generated through the gateway's internal tool API on the price snapshot | own (Apache-2.0) | core of training; published |
| Agentic finance | `nvidia/Nemotron-SFT-Agentic-Finance-v1` | OpenMDW-1.1 | train, per assistant turn, ≤ 2 048 tokens |
| Function calling | ToolACE, Hermes Function Calling v1 | Apache-2.0 | train, incl. "no tool needed" |
| Numeric reasoning | FinQA, ConvFinQA (MIT), TAT-QA (CC-BY-4.0) | permissive | train splits; test splits for evaluation |
| General retention | permissive general SFT slice (e.g. `HuggingFaceTB/smoltalk`) | Apache-2.0 | ~1 k samples |
| Sentiment, headlines, grounded QA | Financial PhraseBank, FiQA-SA, headline sets, FinanceBench | non-commercial / unclear | evaluation only |

v0.1 mix ≈ 12 k supervised samples: 6 k tool-trace turns (≥ 20 % multi-turn, ≥ 10 % failure/unknown/advice cases), 1.5 k agentic finance, 1 k function calling, 2.5 k numeric reasoning, 1 k retention. FinGPT, Sujet-Finance-Instruct and finance-alpaca are excluded (license contamination or bundled test splits).

**Candela Spark (pretraining)**: FineWeb-Edu, SmolLM-Corpus (Cosmopedia v2, FineWeb-Edu-dedup), English Wikipedia, FineMath, EDGAR-CORPUS 10-K sections, finance/economics pages selected from FineWeb-Edu. Raw news is excluded from early pretraining (noisy, time-sensitive, duplicative); dated market data belongs in tools, not weights.

**Live market data**: Nasdaq symbol directory; price snapshot from a permissive public dataset with `asOf` labels; SEC EDGAR company facts once the owner approves a contact address for the SEC-required User-Agent; Vaniras when provided.

## 7. Training on a shared laptop

- Memory: Pro training ≤ 9 GB, Pro inference ≤ 8 GB (on demand), Spark ≤ 4 GB. Memory guard everywhere; nothing Candela does may push the owner's work into swap storms.
- GPU lease (`contracts/gpu-lease.md`): live inference 100 > Pro training 80 > Spark milestone run 70 > evaluation/export 60 > Spark continuous 20.
- Order requested by the owner: Spark M1 first (≈ 1–2 h of GPU time), then Candela Pro training; afterwards Spark keeps training in the background whenever the GPU is free.
- Long jobs: `caffeinate -i nice -n 10`, background execution, checkpoints every 100–200 optimizer steps (Pro) or 10 minutes (Spark).

## 8. Evaluation and release gates

**Pro** (deterministic fast suite, ≤ 30 min, thinking off): FPB, FiQA-SA, headlines, FinQA/ConvFinQA/TAT-QA (numeric exact match with tolerance), FinanceBench, Candela `tool_use` (tool-choice F1, argument validity, grounding rate), held-out loss, IFEval as a forgetting check. Gate vs base: grounding and tool-choice F1 +10 points; no classic suite or IFEval drop above 3 points; manual review of 20 answers finds no fabricated numbers.

**Spark**: per-source validation perplexity in bf16 and int4 (int4 gap < 1 % relative), small zero-shot suite with signal at this scale (LAMBADA, ARC-Easy, PIQA, HellaSwag subsets, BLiMP), finance cloze probes, fixed-seed samples; scaling-law fits across sizes.

## 9. Product experience

- Terminal (default): dense dark UI, amber "candle flame" accent, mono numbers, streaming reasoning and tool lines, financial cards, watchlist, command palette, slash commands, replay mode, installable PWA.
- Observatory (opened from the top bar): Architecture Tower with live telemetry, Fine-tune Field, Embedding Galaxy, Lab HUD, Spark Lab (live training, scaling, attention explorer); split view with the terminal on wide screens.
- Disclaimers where they matter; no personalized advice.

## 10. Security and privacy

ADR 0008 is binding: single narrow ingress (cloudflared → loopback public listener only), no dangerous capabilities (no files, no exec, no client URLs, read-only tools), egress allowlist with private-address blocking, Seatbelt sandboxes for gateway/worker/cloudflared, rate limits and size/token caps, kill switch, no information leaks, supply-chain hygiene (lockfiles, `govulncheck`, `pip-audit`, safetensors only, pinned datasets), strict CSP and URL validation on the client, adversarial verification and a security review before every public exposure. Secrets only in git-ignored `.env` files; owner email never sent to third parties without explicit approval.

## 11. Phases

| Batch | Sessions (parallel) | Depends on | Milestone |
|---|---|---|---|
| 1 | `p1-web`, `p1-gateway`, `p1-ml`, `p1-spark` | contracts | terminal shell live in replay mode; gateway with tools and snapshot; Lab pipeline, Pro baseline and probe; Spark M1 and its daemon |
| 2 | `p2-train`, `p2-worker`, `p2-web` | batch 1 | Candela Pro v0.1 on Hugging Face; MLX worker; terminal wired to the gateway with rich cards |
| 3 | `p3-observatory`, `p3-deploy`, `p3-spark` | batch 2 | Observatory live; hardened public chat with Pro through the tunnel; real recordings; Spark scaling study and next size |
| 4 | `p4-polish` | batch 3 | portfolio polish, README, case study, release v0.1.0 |
| 5+ | `p5-pro-v02`, `p5-spark-grow`, `p6-vaniras` | owner data / batch 4 | better data and preference tuning from feedback; larger Spark sizes and Spark chat tuning; Vaniras integration |

Each brief lives in `docs/plan/<phase>.md`; each session reports in `docs/status/<phase>.md`. The Director verifies every batch (status reports, commits, a smoke run) before starting the next.

## 12. Optional owner actions (never blocking)

- Approve a contact address for the SEC User-Agent to enable live SEC fundamentals.
- A free key for an end-of-day price API for fresher prices than the snapshot.
- A stable hostname (named Cloudflare tunnel on an owner domain such as `candela.umitvice.com`, or a Dev Tunnels login).
- Installing the live LaunchAgent so Candela goes online automatically at login.
- Vaniras data export or API access.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Machine busy (owner's 9 GB llama-server, other agents) | memory guard, GPU lease, pausable runs, admission control, replay mode |
| Gemma 4 12B training exceeds memory | supervised-positions-only loss, fewer adapted layers, shorter sequences |
| Spark training unstable under QAT | short bf16 warm-up option, QK-norm, gradient clipping, int4-vs-bf16 gap monitoring, ablations at tiny scale |
| Laptop sleep, shutdown or network loss | atomic exact-resume checkpoints, local data shards, LaunchAgent, `caffeinate` |
| Public endpoint abuse | ADR 0008 layers, kill switch |
| Quick tunnel instability | supervisor restarts, Gist discovery, replay mode, upgrade paths |
| Stale snapshot data | `asOf` everywhere; SEC, Vaniras or keyed provider later |
| Netlify credit exhaustion | ≤ 1 production deploy per phase, no Netlify builds, weights never on Netlify |
| License contamination | permissive-only training sources, per-example license metadata, data cards |
