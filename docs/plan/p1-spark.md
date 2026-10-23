# Phase 1 · Spark — Candela Spark v0, a QAT-native model family built from scratch (`p1-spark`)

- Area you own: `spark/**`, `make/spark.mk`, `apps/web/public/observatory/spark/**` (artifacts only; stage only that subfolder under `apps/web`), `docs/status/p1-spark.md`, ADRs numbered 0600–0699.
- Runs in parallel with `p1-web`, `p1-gateway` and `p1-ml`. Do not touch their paths. `ml/` is a different project (Candela Pro); share nothing by import — copy small utilities if needed.
- Inputs: `CLAUDE.md`, `docs/plan/00-master-plan.md` (sections on Candela Spark and quantization), `docs/adr/0009-candela-spark.md`, `contracts/gpu-lease.md`, `contracts/observatory.md`.

## Goal

Lay the foundation of **Candela Spark**: a decoder-only language-model family whose tokenizer, model code, training loop and data pipeline are written from scratch in MLX, designed to grow from ~35M parameters today towards ~2B (Gemma 4 E2B class) as the hardware allows, and trained **quantization-aware** so that int4 is its native, default format with no quality loss. Reach a first milestone within the first 1–2 hours of GPU training, then keep training continuously in the background — resumable, reboot-proof, network-independent and polite to the owner's other work.

## Owner requirements (do not trade these away)

- From scratch: no `mlx-lm` or Hugging Face model classes; MLX primitives only (plus `tokenizers` for BPE training).
- "Train it knowing it will run in Q4": QAT throughout; the int4 export is the primary artifact.
- 35M is a starting target, not the product: architecture, tokenizer, data pipeline, parametrization and checkpoint format must carry over to larger sizes without restarting the family.
- Continuous training on the Mac that survives shutdowns, reboots and network loss by checkpointing and resuming.
- Data only from safe, reputable, permissively licensed sources, pinned and verified; high-quality general educational text first, finance-domain text (SEC filings) as a significant share; no raw news in early pretraining.

## Phase 0 — design (time-boxed to 45 minutes)

Read the inputs, research only what you need, and record the spec in ADR 0600 (architecture, tokenizer, parametrization, optimizer, schedule, size presets) and ADR 0601 (QAT recipe and int4 export). The Director forwards additional research notes by message; incorporate them when they arrive without blocking. Start data downloads early in the background while you design.

## Deliverables

1. uv project `spark/` (`candela-spark`, Python 3.14, ruff, pyright, `pip-audit` in `spark-check`) with a Typer CLI `spark`: `doctor`, `data fetch|process|stats`, `tokenizer train`, `train`, `eval`, `sample`, `export`, `status`, `daemon install|uninstall|status`, `observatory export`, `publish`.
2. **Data** (pinned, checksummed, permissive):
   - General: FineWeb-Edu (`HuggingFaceFW/fineweb-edu`), Cosmopedia v2 and FineWeb-Edu-dedup from `HuggingFaceTB/smollm-corpus`, English Wikipedia (`wikimedia/wikipedia`), FineMath (`HuggingFaceTB/finemath`). Verify each license on its card at the pinned revision.
   - Finance: EDGAR-CORPUS (`eloukas/edgar-corpus`, Apache-2.0) business, risk-factor and MD&A sections with boilerplate removed, plus finance/economics pages selected from FineWeb-Edu and upsampled.
   - Integrity: download with `huggingface_hub` at an explicit commit `revision` recorded in `spark/configs/data/*.yaml`; write a manifest with byte sizes and SHA-256 of every file; parquet/JSON only; never use dataset loading scripts, pickles or `trust_remote_code`; nothing from a dataset is ever executed.
   - Processing: language, length and quality filters; exact and MinHash document dedup; deterministic shuffling; tokenization into memory-mapped `uint16` shards with an index; validation split per source. Download pool for v0 ≈ 2–3 B tokens (≤ 20 GB on disk) so continuous training runs for weeks without the network.
3. **Tokenizer** (frozen for the whole family once trained; record its hash): byte-level BPE trained on a balanced sample of the mixture, vocabulary 32 768 unless your ADR argues otherwise, individual digit splitting, reserved special tokens for future chat and tool use (BOS/EOS/PAD, turn markers, tool call/response, thinking, ≥ 64 reserved).
4. **Architecture** (config-driven family, pure MLX): Gemma-style decoder — RMSNorm before and after each sublayer, QK-norm, grouped-query attention, RoPE with separate bases for local and global layers, interleaved local sliding-window and global attention, gated FFN, no biases, tied embeddings with √d scaling, deep-and-thin proportions at small sizes. Size presets with exact parameter counts for ≈ 35M, 125M, 350M, 1B and 2B; only 35M trains now.
5. **QAT**: every linear weight in the blocks trains through int4 fake quantization with group size 32 on exactly the grid MLX uses for 4-bit export, via a straight-through estimator; embedding/LM-head precision per ADR 0601; QAT active from the start or after a short warm-up per the ADR. Track validation loss of the bf16 master weights and of the exact int4 export side by side for the whole run; the exported int4 model must reproduce the QAT forward pass within tolerance.
6. **Optimisation and scaling**: μP-style parametrization (or a justified alternative) so hyperparameters transfer across sizes; Muon for hidden matrices with AdamW for embeddings and norms (implement Muon if MLX lacks it); warmup–stable–decay schedule so the continuous run stays in the stable phase and releases come from short decay branches; gradient clipping; bf16 compute with fp32 master weights; `mx.compile` for the training step.
7. **Robust trainer**: checkpoints every 10 minutes and on SIGTERM/SIGINT (model, optimizer, RNG, data cursor, step, tokens, schedule) written atomically (temp dir, fsync, rename) with a manifest hash; keep the last 3 plus milestone checkpoints every 250 M tokens; exact resume with integrity check and fallback; no network calls during training; memory resource guard; GPU lease (`contracts/gpu-lease.md`) at priority 20, or 70 while chasing milestone 1 so it is not starved by evaluations (Candela Pro training at 80 still preempts it); pause on battery power and on serious thermal pressure; metrics JSONL; sanitized `~/.candela/spark/status.json` for the Observatory and gateway.
8. **Continuous operation**: user LaunchAgent `com.candela.spark-trainer` (RunAtLoad, KeepAlive on crash, `ProcessType` Background, LowPriorityIO, Nice 10, logs in `~/Library/Logs/Candela/`) with `make spark-daemon-install` / `spark-daemon-uninstall`. The owner asked for continuous training, so install it at the end of this phase, only after milestone 1 is verified.
9. **Milestone 1** (≈ 1–2 hours of GPU training once data is ready): the 35M model producing coherent English on general and finance prompts; a short decay branch produces `spark-35m-m1`, exported to MLX int4 (plus bf16 for reference) and, if the grid maps exactly, GGUF Q4_0 (otherwise document why). The main run then continues in the stable phase under the daemon.
10. **Evaluation**: per-source validation perplexity (bf16 and int4), a small zero-shot suite that gives signal at this scale (for example LAMBADA, ARC-Easy, PIQA, HellaSwag subsets, BLiMP), finance cloze probes, fixed-seed samples; reports in `spark/reports/`.
11. **Observatory artifacts** in `apps/web/public/observatory/spark/` (propose the schemas in your status report; the web phase renders them): architecture, training curves (bf16 vs int4 validation), milestones, and attention maps for every layer and head on 6–8 curated finance sentences (compact encoding).
12. **Publish** milestone 1 to Hugging Face `UmitVice/candela-spark-35m` (int4 MLX weights, tokenizer, config, model card covering architecture, data sources with licenses and revisions, QAT recipe, evaluation and limitations) after checking the card contains no secrets or local paths.
13. `make/spark.mk`: `spark-sync`, `spark-doctor`, `spark-data`, `spark-tokenizer`, `spark-train`, `spark-status`, `spark-sample`, `spark-daemon-install`, `spark-daemon-uninstall`, `spark-check`.

## Acceptance (verify by running; no automated tests)

- `make spark-check` passes.
- Milestone 1 exported, evaluated and published; the int4-vs-bf16 validation-loss gap is reported (target < 1 % relative).
- `kill -TERM` during training writes a checkpoint; restarting resumes at the same step with a matching loss trajectory; training runs with networking disabled for the process.
- The daemon is installed, restarts after a crash, yields to a higher-priority lease within one step, and pauses on battery (simulated through a config override).
- Report written to `docs/status/p1-spark.md` with throughput, peak memory, tokens, time to milestone and the decisions.

## Out of scope

Chat/SFT for Spark, training larger sizes, gateway or web changes (propose them), tests.
