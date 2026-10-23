STATUS: done

Summary:
Candela Spark is built from scratch in pure MLX: frozen tokenizer, a Gemma-3-compatible decoder family (35M to 2B presets), int4 QAT on the exact MLX export grid, our own Muon + AdamW, a WSD schedule, atomic exact-resume checkpoints, and a pinned, checksummed 2.5B-token data pool. Milestone 1 (`spark-35m-m1`) trained in 92 minutes of GPU time (144M tokens). Evaluation:
- int4 vs bf16 validation-loss gap: **0.088 %**.
- The exported MLX int4 model reproduces the QAT forward pass.
- The GGUF Q4_1 export runs unchanged in llama.cpp, with greedy output token-identical to MLX.

M1 is published at https://huggingface.co/UmitVice/candela-spark-35m. The LaunchAgent `com.candela.spark-trainer` is installed and continues the main run in the stable phase at lease priority 20.

Commits: 99465bd feat(spark): add Candela Spark QAT-native model family scaffold, 5a80ef3 feat(spark): pick probe learning rates, upweight EDGAR, cheaper step gate, 87a9f73 fix(spark): reseed deterministically on resume instead of restoring RNG, 7d90a58 feat(spark): add finance cloze probes with plausible distractors, 0f628f5 feat(spark): release milestone 1 (spark-35m-m1) with eval and Observatory data, plus the commit carrying this report.

Verified:
- `make spark-check` passes: ruff format, ruff lint, pyright (0 errors), pip-audit (no known vulnerabilities).
- **Data.** 10 files from 6 Hugging Face datasets, pinned to commit revisions in `spark/configs/data/v0.yaml`.
  - Each card license is checked at the pinned revision (odc-by, cc-by-sa-3.0, apache-2.0); gated or private repos are refused.
  - SHA-256 of every file is checked against the hub LFS pointers. Manifest: `spark/data/raw/manifest-v0.json`, 9.3 GB raw.
  - Only parquet/jsonl is read; nothing is executed. EDGAR's `edgar-corpus.py` loading script is never downloaded.
  - After filters, exact dedup (1,761) and MinHash dedup (109,288 near-duplicates out of 2.41M docs): **2.50B training tokens** in 5.4 GB of `uint16` mmap shards.
  - Train tokens per source: fineweb-edu-dedup 817M, fineweb-edu 747M, wikipedia-en 311M, cosmopedia-v2 256M, edgar 227M (sampled ×2), finemath 123M, fineweb-edu-finance 19M (sampled ×3). Finance is about 19 % of the mixture.
- **Tokenizer.** 32 768-token byte-level BPE with Qwen2 single-digit splitting and 128 special tokens (104 reserved). SHA-256 `cd803bdf515249f10c6cc2c24e1ea84241a56ea71a6d3c031010e969eeee6b3d`.
- **Throughput and memory** (35M, micro-batch 2 × 1024, 16 accumulation steps):
  - Raw benchmark: 31.8k tokens/s with QAT, 32.6k without, so QAT overhead is under 2 %. Micro-batch 8 peaks at 8 GB, over the 4 GB budget.
  - Real run: **26.0k tokens/s**, **peak MLX memory 2.42 GB**.
  - Under the LaunchAgent (`ProcessType Background`, Nice 10): 16.5k tokens/s.
- **LR probe** (250 steps, 8.2M tokens): Muon 0.01 / AdamW 0.001 → val 5.554; 0.02 / 0.002 → 5.342; 0.04 / 0.004 → 5.219. Picked 0.04 / 0.004.
- **Time to milestone.**
  - GPU training: main run to step 3600 in 75.5 min (118M tokens), then a 1−√ decay branch of 800 steps in 16.8 min, **92.3 min total** for 144M tokens.
  - Wall clock: about 2 h 05 min from the tokenized data being ready to the M1 checkpoint (including probes and the resume reference), and about 2 h 20 min to verified export.
  - Waiting: when the phase began, the owner's `evidencedesk_ml.train_mlx` Gemma 12B run held about 16 GB wired and 17 GB swap. My first benchmark stalled on memory, so I stopped it and did only CPU work (downloads, code). The run had ended by 10:57 local. This session was also paused by a usage limit in that window, so the pure foreign-training wait cannot be separated from it; it was under about 1.5 h.
- **Milestone 1 evaluation** (`spark/reports/spark-35m-m1.md`; 64 × 1024-token held-out windows per source):

  | Source | bf16 loss | int4 loss | int4 export |
  |---|---|---|---|
  | cosmopedia-v2 | 3.2586 | 3.2617 | 3.2619 |
  | edgar | 2.3583 | 2.3619 | 2.3619 |
  | finemath | 2.9665 | 2.9694 | 2.9690 |
  | fineweb-edu | 3.7548 | 3.7580 | 3.7579 |
  | fineweb-edu-dedup | 3.5944 | 3.5937 | 3.5937 |
  | fineweb-edu-finance | 3.4426 | 3.4453 | 3.4452 |
  | wikipedia-en | 3.4882 | 3.4936 | 3.4936 |

  - Mean 3.2662 bf16 vs 3.2691 int4: **gap +0.088 %**, target < 1 %. During the stable phase the gap reached 0.45 %; the decay branch brought it back to 0.11 %.
  - Zero-shot (n=500, BLiMP 1 000): LAMBADA acc 0.138, ARC-Easy 0.352 (chance 0.25), HellaSwag 0.278 (0.25), PIQA 0.582 (0.5), BLiMP 0.869 (0.5), finance cloze 1.000 (easy, 24 items), finance cloze with plausible finance distractors 0.8125 (16 items, chance 0.25).
  - Samples: grammatical English with finance register; weak on facts and repetitive, as expected at this scale.
- **Export.**
  - MLX int4: 21.9 MB. The exported model, run through `mx.quantized_matmul`, matches the QAT forward with max relative loss difference 2.8e-4; per-source export losses equal the int4 losses to 4 decimals.
  - bf16 reference: 70 MB.
  - GGUF Q4_1 under arch `gemma3`: 23.1 MB, with 0.0 deviation converting scales and biases from bf16 to fp16. `llama-simple` (Homebrew build) loads it and generates at about 400 tokens/s; on a probe checkpoint its greedy text was identical to MLX int4.
- **Kill and resume.** `kill -TERM` at step 152 wrote `step-00000152` in 0.18 s and the process exited 0. The restart resumed at step 152. Losses at steps 160–200 match an uninterrupted twin run within ±0.004, the same spread as GPU nondeterminism before the kill (−0.0037 at step 150).
- **No network.** Every training run used `sandbox-exec` with `(deny network*)`. Inside that profile Metal works and HTTPS fails with a DNS error; the trainer also sets `HF_HUB_OFFLINE`.
- **Gate tests on the live trainer.**
  - A simulated priority-80 lease paused it in the same second (next step boundary); it resumed 3 s after removal.
  - `{"simulateBattery": true}` in `~/.candela/spark/override.json` paused it within a second.
  - A fake process named `…evidencedesk_ml.train_mlx` paused it within the 10 s check window.
- **Daemon.** `spark daemon install` loaded `com.candela.spark-trainer`, which resumed `spark-35m-main` from step 3600 at priority 20.
  - After `kill -9`, launchd restarted it within a second (`runs = 2`) and it resumed from the last valid checkpoint.
  - It yielded to the priority-80 lease within a step and paused on simulated battery. It is still running.
- **Publish.** The card was scanned for local paths, tokens and emails, then pushed to `UmitVice/candela-spark-35m` (public, commit 79d58cf). Files: int4 `model.safetensors`, `config.json`, `tokenizer.json`, Q4_1 GGUF, `bf16-reference/`, `eval.json`, `README.md`.

Decisions:
- ADR 0600 covers architecture, tokenizer, parametrisation, optimiser, schedule, presets and checkpoint format. ADR 0601 covers QAT and int4 export.
- Gemma 3 block layout, including llama.cpp's `gemma3` local/global rule (`i % 6 == 5` is global), so GGUF needs no llama.cpp changes.
- All matrices are QAT int4, including the tied embedding/head. QAT is on from step 0.
- **GGUF Q4_1 instead of Q4_0.** Q4_0 has no offset and cannot express MLX's affine grid; Q4_1 is the same formula, so the export is exact.
- Own Muon implementation: `mlx.optimizers.Muon` puts weight decay inside the orthogonalised update. AdamW handles the embedding and norms. μP-style output multiplier (exactly 1 at the 35M base width).
- Pretokenizer: Qwen2's regex, so llama.cpp recognises it as `qwen2`.
- Micro-batch 2 × 16 accumulation steps to stay under 4 GB (2.4 GB peak).
- Checkpoint retention: milestone checkpoints older than the newest two drop optimizer state to bound disk use.
- Deviations from the brief and pins:
  - Python is Homebrew 3.14.6 inside `>=3.14,<3.15`. uv 0.11.21 offers no 3.14.9 build; the ml venv uses the same interpreter.
  - The frozen tokenizer is `spark/tokenizer/spark-bpe-32k.json`, because the root `.gitignore` pattern `token*.json` hides `tokenizer.json`. Exports still ship `tokenizer.json`.
  - PIQA uses the hub's parquet conversion (`refs/convert/parquet`, pinned commit) because the original repo only has a loading script.
  - The daemon wraps the trainer in `caffeinate -s` (stays awake only on AC) and `sandbox-exec` (no network).
- Owner and Director rules applied: never train alongside another training process; no Candela GPU training while foreign training runs (checked at start and every 10 s); data never executed.

Open issues / risks:
- The 2.5B-token pool lasts about 1.1 days of fully free GPU at 26k tokens/s, so the continuous run will repeat data (window boundaries shift each epoch). A v1 data pull should add more FineWeb-Edu and EDGAR years.
- Disk: `spark/data` is 15 GB (raw 9.3 GB can be deleted after tokenization if space is needed); `spark/runs` is 1.8 GB.
- Older milestone checkpoints (every 250M tokens) keep fp32 weights only, about 140 MB each.
- The daemon's Background priority costs about 35 % throughput, by design.
- Eval caveats: zero-shot subsets are small and web pretraining data may overlap benchmark text. The easy finance cloze set saturates; the hard set is the meaningful one.
- MLX pin matters: if MLX changes its quantisation rounding, the export check would catch it, but older QAT checkpoints would no longer map exactly.

Notes for the next phases:
- **Proposed Observatory schemas** (`candela.observatory.spark.v1`, already written to `apps/web/public/observatory/spark/`):
  - `manifest.json`: `{schema, generatedAt, current, models:[{id, displayName, status, parameters, files:{architecture, training, milestones, attention}, huggingFace}], liveStatus:{schema, servedBy}}`.
  - `spark-35m/architecture.json`: `layers[{index, attention:'local'|'global', window, ropeBase}]`, dimensions, `parameters{embedding, per_layer, blocks, total, …}`, `quantization`, `tokenizer`, `familyPresets[{id, parameters, hiddenSize, layers, heads, kvHeads, trained}]`.
  - `spark-35m/training.json`: `{modelId, main:{runId, train:[{step, tokens, loss, lr, tokensPerSec, peakMemGb, elapsedSec}] (≤ 2000), valid:[{step, tokens, bf16, int4, gapRel, perSource}], pauses[{step, reason, at}], checkpoints[]}, branches:[same shape for spark-35m-m1]}`.
  - `spark-35m/milestones.json`: `{modelId, milestones:[{id, step, tokens, evaluatedAt, validation{meanBf16, meanInt4, gapRel}, zeroShot[{id, metric, n, value, chance}], samples[], export{maxRelLossDiff, …}, huggingFace}]}`.
  - `spark-35m/attention.json`: 8 finance sentences × 12 layers × 6 heads. Each head is the row-major lower triangle of its T×T attention matrix, stored as uint8 (probability × 255) and base64-encoded; `layerTypes` marks local/global layers.
- **Gateway proposal**: serve `~/.candela/spark/status.json` (schema `candela.spark.status.v1`, already sanitised: state, runId, phase, step, tokens, pauseReason, train/valid summaries, milestones, leasePriority) read-only, e.g. `GET /v1/spark/status`, for the Spark Lab live view.
- **Candela Pro training (p2-train)** can start now. Spark holds `spark-trainer` at priority 20 and yields to `lab-train` (80) within one step; after 10 minutes of waiting it checkpoints and calls `mx.clear_cache()`. The daemon also pauses for any non-Candela `train_mlx` / `mlx_lm` training.
- Daemon controls: stop with `make spark-daemon-uninstall` (SIGTERM, checkpoint); pause with `{"pause": true}` in `~/.candela/spark/override.json`; check with `make spark-daemon-status`.
- **Next Spark release**: fork a new decay branch from a later main-run checkpoint (`spark/configs/train/spark-35m-m1.yaml` with a new `run_id` and `fork_step`), then run `spark export` / `spark eval` / `spark observatory export` / `spark publish`.
- **p3-spark**: scaling study (extend the LR grid above 0.04, coordinate checks for μP transfer) and growth operators to move to spark-125m.
