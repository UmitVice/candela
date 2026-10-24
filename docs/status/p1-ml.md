# p1-ml — status

STATUS: done

Summary:
Candela Lab (`ml/`, uv project `candela-lab`, Typer CLI `lab`) runs the Candela Pro pipeline end to end on Gemma 4 12B with Google's QAT int4 weights (owner's read-only `~/models/gemma-4-12b-it-qat-mlx-q4`, never merged). The pipeline covers pinned and decontaminated dataset `d0.1`, synthetic tool-use traces (fake executor and the real gateway), guarded QLoRA training with a supervised-positions-only LM head, a deterministic eval harness, MLX → PEFT → GGUF-LoRA export checked in `llama-server`, Observatory artifacts, and a publish dry run. Base vs pilot after 120 QLoRA steps: tool-choice F1 0.780 → 0.871, grounding 0.941 → 0.981, held-out loss 1.319 → 0.510, ConvFinQA 0.26 → 0.72. Classic sentiment and FinQA regress, so the pilot is a pipeline validation, not a release.

**Model selection:** Candela Pro = Gemma 4 12B QAT int4 + rank-16 LoRA on the top 16 layers (32–47) at `max_seq_length` 2 048, training budget 10.5 GB (ADR 0003, accepted).

Commits: be70f3d feat(ml): scaffold Candela Lab with resource guard and doctor; c96db92 feat(ml): add pinned data pipeline and synthetic tool-use traces; 43c714b feat(ml): add training loop, eval harness, GGUF-LoRA export and publish; b1b9305 style(ml): apply ruff format; f1ce23f feat(ml): add probe and pilot configs, fix completion boundary, cap 4096; dd6778d fix(ml): stop scrubbing SEC accession numbers and table columns as PII; 14cb48a fix(ml): wait for memory headroom before taking a GPU lease; 2349467 perf(ml): bound LM-head chunks, skip frozen-layer backprop, probe configs; 45c7047 docs(adr): record Candela Pro QLoRA probe results; e7cdf86 fix(ml): let paused jobs recover while holding a model and cache eval suites; 1fb22c4 feat(ml): reserve GPU leases while waiting for memory (gpu-lease v1.1); 8218ebe feat(ml): pressure-based guard for Candela Pro jobs (11 GB start); plus the final commit with reports, Observatory artifacts and this report.

Verified:
- `make ml-check` (ruff format check, ruff lint, pyright: 0 errors). `lab doctor` prints versions (mlx 0.32.4, mlx-lm 0.32.2, transformers 5.20.2, …), Metal device (Apple M5 Pro, 17.8 GB recommended working set), memory headroom, live GPU leases and the guard decision.
- **Data** `lab data fetch --pin` → every file pinned to a commit revision and SHA-256 in `ml/configs/data/d0.1.lock.json`. `lab data build --version d0.1` → 12 208 train / 492 valid samples (one supervised assistant turn each), all mix targets met (traces 6 000, agentic finance 1 500, function calling 1 000, numeric 2 500, sentiment 400, headlines 300, retention 1 000). Licenses per sample: Apache-2.0 8 000, MIT 2 450, OpenMDW-1.1 1 500, CC-BY-4.0 750. 13-gram decontamination removed FinQA 3 734, ConvFinQA 1 864, TAT-QA 2 777, smoltalk 16 346 (IFEval overlap), Nemotron 43. Tokens (Gemma tokenizer): p50 890, p95 3 478, max 4 096. Build: 63 min CPU. Manifest `ml/manifests/d0.1.json`, data card `ml/datacards/d0.1.md`.
- **Traces**: 2 600 fake-executor + 200 gateway conversations (own gateway on 127.0.0.1:8730/8739, `POST /internal/v1/tools/execute`). Validator: 0 invalid; it rejects injected fabricated numbers and malformed tickers. Multi-turn 23–25 %, failure/unknown/advice ≈ 19 %. Chat template: 3 687/3 687 tool-call turns render and parse back exactly.
- **Probes** (20 steps, 2 048 tokens, longest samples): top-16 layers peak 10.46 GB at 332 tok/s; top-24 layers 10.77 GB at 271 tok/s. Single-step peaks: 9.45 GB @1 024 and 12.50 GB @4 096. Frozen base: 7.44 GB, 11.9 B parameters.
- **Pilot** `pilot-candela-pro`: 120 optimizer steps (batch 1 × accumulation 8), 799 k tokens, 40 min of compute at 336 tok/s, peak 10.96 GB. Validation loss 0.749 → 0.683 → 0.659 at steps 40/80/120. One simulated pause at step 29: checkpoint, release, 30 s recovery, resume. One real pause at step 75 (swap growth), resumed from checkpoint 75 later with the new guard. LoRA delta max-norm 0 → 4.66. Checkpoints every 20 steps.
- **Baseline vs pilot** (fast mode, greedy, thinking off; `ml/reports/eval/`):

| Suite | n | Base | Pilot |
|---|---:|---:|---:|
| FPB macro-F1 | 300 | 0.855 | 0.789 |
| FiQA-SA weighted-F1 | 235 | 0.754 | 0.697 |
| Headlines weighted-F1 | 300 | 0.750 | 0.752 |
| FinQA numeric EM | 100 | 0.650 | 0.590 |
| ConvFinQA numeric EM | 100 | 0.260 | 0.720 |
| TAT-QA arithmetic EM | 100 | 0.880 | 0.850 |
| Tool-choice F1 (precision / recall) | 40 conv. | 0.780 (0.86 / 0.71) | 0.871 (0.87 / 0.88) |
| Grounding rate | 40 conv. | 0.941 | 0.981 |
| Argument validity / malformed calls | | 1.00 / 0 | 1.00 / 0 |
| Held-out loss (d0.1 valid) | 88 | 1.319 | 0.510 |

  Durations: base 32 min, peak 12.74 GB; pilot 47 min including two short pressure pauses, peak 13.04 GB.
- **GGUF LoRA**: MLX adapter → PEFT (218 tensors) → `convert_lora_to_gguf.py` at llama.cpp `b9960` (`ml/vendor/`, git-ignored) → 43.7 MB F16 in 9 s. `llama-server --lora` on the owner's QAT Q4_K_XL GGUF at 127.0.0.1:8713 loads in 2–3 s, `/lora-adapters` lists it, and answers with LoRA scale 1 differ from scale 0. The server was stopped.
- **Observatory**: `manifest.json` and `models/candela-pro-pilot/{architecture,training,lora-deltas,eval}.json` in `apps/web/public/observatory/` (contract shapes, 0.5–14 KB each). Flagged as a pilot through `version: v0.1-pilot`. Spark's `observatory/spark/` was left untouched.
- **Publish**: `lab publish pilot-candela-pro --dry-run` stages model cards and files for `UmitVice/candela-pro-v0.1-pilot-mlx-adapter` (87.5 MB), `…-gguf-lora` (43.7 MB) and the dataset `UmitVice/candela-tool-traces` (22.4 MB). Nothing uploaded.
- **GPU lease v1.1**: Spark logged `yield_exit` to `lab-eval (priority 60)` and to `lab-train (priority 80, waiting)` and released its memory, and our leases were deleted on exit. All my gateway, `llama-server` and queue processes are stopped.

Decisions:
- ADR 0400 — `d0.1` keeps samples up to 4 096 tokens. With the Gemma tokenizer a full analysis turn is ≈ 4 000 tokens, and only 64 % of trace turns fit 2 048. Analyses request `get_fundamentals` with `limit: 2`. The pilot still trains at 2 048 (ADR 0003 probe).
- ADR 0003 — probe table filled in and status accepted. **Deviation:** no useful configuration stays ≤ 9 GB (frozen base 7.44 GB plus attention-backward activations), so the training budget is 10.5 GB. Guard per the owner's decision (`PRO_POLICY`): start/resume at ≥ 11 GB available (free + inactive + purgeable + speculative), pause only on kernel memory pressure warn/critical, resume after 2 minutes at normal. Lease reservations and foreign-training detection stay in force.
- Training loop written on top of mlx-lm's LoRA layers rather than `mlx_lm.tuner.train`, for checkpoint/resume with optimizer state, guard and lease checks at step boundaries, pause-and-release, and the custom loss. The loss computes the LM head only at supervised positions in 64-position checkpointed chunks (256 caused 12 GB spikes); frozen layers skip the backward pass.
- Prompt/completion split cuts at a template token boundary, so samples match inference exactly (Gemma's empty thought channel; `<|tool_call>` is never split).
- Fake executor: internally consistent synthetic market series with the contract's key order and rounding (checked against `contracts/tools.md` at start). Contract examples are served verbatim only with `serve_contract_examples`, because mixing them with synthetic views gave inconsistent numbers within one conversation.
- Grounding metric: "data numbers" (decimals, %, $, K/M/B/T units, integers ≥ 1 000, dates) must match a tool output after rounding or unit scaling, or be listed as composer-derived. Bare small integers ("14-day", "RSI above 70") are vocabulary.
- Numeric EM: 1 % relative tolerance; ratio and percent scalings are both accepted (FinQA stores 14.1 % as 0.141).
- Eval-only sets use ungated mirrors (ChanceFocus FLARE parquet) to avoid accepting terms. FinQA and ConvFinQA training data come from the authors' MIT GitHub repos pinned to a commit. Twitter financial sentiment and topic sets (MIT) provide the Candela-voice classic tasks.
- PII scrubbing restricted to card-shaped and explicitly separated phone patterns, after the first build scrubbed SEC accession numbers in Nemotron URLs.
- torch 2.14.1 lives only in the optional `convert` dependency group for llama.cpp's converter. `lab export fuse` refuses for Candela Pro (never merged).
- Python 3.14.6: uv 0.11.21 offers no 3.14.9 download; `requires-python` stays `>=3.14,<3.15`.

Open issues / risks:
- **Pilot regressions**: FPB −6.6, FiQA −5.7, FinQA −6.0 and TAT-QA −3.0 points would fail the release gate (≤ 3 points). Likely causes: the short run, phrase-bank answers in sentiment and numeric samples (the pilot reproduces template phrasing such as "a read of the wording only"), and eval prompts that ask for one-word labels. The ConvFinQA jump (+46) partly reflects learning the "Answer: <number>" format. `p2-train` should diversify the composers, lower the classic-task share or add more varied permissive data, and add IFEval/FinanceBench suites (both only used for decontamination so far).
- **Eval memory**: batched generation (batch 16 short / 4 long prompts) peaks at 12.7–13.0 GB, above the 8 GB inference budget. The pressure guard handled it here; use smaller batches if the machine is tighter.
- Final answers of full analyses (≈ 4 000 tokens) are not trained at 2 048. 3 072 tokens (≈ 11 GB) is untested.
- The 300 held-out `tool_use` traces come from the fake executor (synthetic prices). Regenerate them through the gateway for release numbers.
- I ran one diagnostic probe with gradient checkpointing off. It peaked at 24.9 GB and grew swap by 6.25 GB before the guard paused it after one step; it was killed and must not be repeated.
- GitHub reported 7 Dependabot alerts on push; the API was unreachable from here, so I could not check whether any are in `ml/uv.lock`.

Notes for the next phases:
- **p2-train**: `lab train run configs/train/<cfg>.yaml` (resume with `lab train resume <run-id>`, pause with `touch ml/runs/<id>/PAUSE` or SIGUSR1). Regenerate the 6 000 trace turns through the gateway (`lab traces generate --executor gateway --out data/traces/d0.1/…`, then `lab data build`) and replace the fake traces. The 24-layer LoRA costs only +0.3 GB. Queue example: `ml/scripts/p1-gpu-queue.sh`.
- **p2-worker**: `ml/configs/models.yaml` (schema 2) has base/reference/GGUF paths with env overrides (`CANDELA_PRO_BASE`, …), chat-template notes (Gemma 4 `<|tool_call>call:NAME{…}<tool_call|>`, stop `<turn|>` / `<|tool_response>`, `enable_thinking`) and the inference budget. The pilot adapter is at `ml/runs/pilot-candela-pro/adapter/` (`mlx_lm.load(base, adapter_path=…)`).
- **p2-web / p3-observatory**: real pilot data is in `apps/web/public/observatory/` (`current: candela-pro-pilot`). `training.json` has two pauses (simulated and swap growth) and seven LoRA-delta checkpoints. Re-sync with `make ml-observatory`.
- **Director**: proposal for `contracts/observatory.md` — an optional `pilot: boolean` on manifest models instead of encoding it in `version`.
