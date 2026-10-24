# p2-train — status

STATUS: partial — paused by owner

## Paused by owner (2026-10-24 15:37 UTC)

The Director asked to pause the Candela Pro v0.1 run because the owner may shut the Mac down. The trainer was already paused by the resource guard (memory pressure, available memory below 11 GB). The guard had checkpointed at step 281 and released the model. I then stopped the process with SIGTERM; its `lab-train` lease file was removed. No Candela GPU job and no Candela Lab gateway is running.

- Run `candela-pro-v0.1-lr5e5` (`ml/configs/train/candela-pro-v0.1-lr5e5.yaml`): step 281 / 1 080, latest checkpoint `ml/runs/candela-pro-v0.1-lr5e5/checkpoints/step-000281`. The checkpoint holds the adapter, the optimizer state and the data cursor. 1.96 M tokens trained in 1.6 h of compute at ≈ 345 tokens/s, peak 10.99 GB, 22 guard pauses so far.
- Validation loss (d0.2 valid, 64 samples): 0.254 at step 100 with lr 1e-4; 0.218 at step 100 and 0.200 at step 200 with lr 5e-5.
- Resume command (from the repository root):

```bash
cd ml && MACOSX_DEPLOYMENT_TARGET=14.0 caffeinate -i nice -n 10 uv run --frozen lab train resume candela-pro-v0.1-lr5e5
```

- What remains after training, in order (`ml/scripts/p2-gpu-queue.sh`, `RUN_ID=candela-pro-v0.1-lr5e5`):
  1. Full-mode evaluation of the base and the tuned model (`baseline` and `eval` steps).
  2. Release gate (`lab eval gate`), plus a manual review of 20 tool-use answers.
  3. GGUF-LoRA export and check.
  4. Observatory artifacts and `galaxy.json`.
  5. Hugging Face publish, `ml/configs/models.yaml`, `ml/reports/release-v0.1.md`.

## Done so far

- Traces: 6 000 train and 300 held-out conversations through the real gateway executor (own instance, `ml/scripts/gateway-ml.sh`, 8730/8739). Validator: 0 invalid. Multi-turn 21.9 %. Failure, unknown-company, missing-data, advice and off-topic cases ≈ 28 %. New `quick_analysis` intent.
- Sequence length: the 3 072 probe peaked at 11.99 GB at 187 tok/s, and full analysis answers have a median of 3 412 tokens, so training stays at 2 048 (ADR 0401).
- Retention data by base self-distillation (ADR 0402): 2 585 answers from the frozen base kept: 1 197 numeric, 750 labels, 638 general. It took 4.2 h of GPU time.
- Dataset `d0.2`: 8 673 train and 381 valid samples, 7.63 M tokens (`ml/manifests/d0.2.json`, `ml/datacards/d0.2.md`).
- New eval suites: IFEval (strict, prompt level) and FinanceBench (evidence given). Eval batches are smaller (8 short / 4 long, prefill 2); baseline peak 10.95 GB.
- Learning-rate trial at step 150, fast suites against the base (`ml/reports/eval/`):

| Suite | Base | lr 1e-4 | lr 5e-5 |
|---|---:|---:|---:|
| Tool-choice F1 (40 conv.) | 0.717 | 0.929 | 0.909 |
| Grounding | 0.939 | 0.985 | 0.975 |
| FPB | 0.855 | 0.817 | 0.847 |
| FiQA-SA | 0.757 | 0.806 | 0.791 |
| Headlines | 0.750 | 0.755 | 0.751 |
| FinQA | 0.660 | 0.650 | 0.680 |
| ConvFinQA | 0.260 | 0.300 | 0.270 |
| TAT-QA | 0.880 | 0.870 | 0.880 |
| FinanceBench | 0.770 | 0.706 | 0.754 |
| IFEval | 0.860 | 0.847 | 0.860 |

  lr 5e-5 passes every gate check at step 150, so it continues to the full schedule; lr 1e-4 fails FPB and FinanceBench.
