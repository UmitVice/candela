#!/usr/bin/env bash
# p2-train GPU work in order (Candela Pro v0.1); every step waits for memory headroom, foreign trainings and the
# GPU lease. Usage: p2-gpu-queue.sh <step>  with step in distill | baseline | ablate | train | eval | export | all.
set -euo pipefail
cd "$(dirname "$0")/.."
step="${1:-all}"
lab() { uv run --frozen lab "$@"; }
base_label=gemma-4-12b-qat-base-d0.2
# The ablation winner continues to the full schedule and becomes the release run.
run_id="${RUN_ID:-candela-pro-v0.1-lr5e5}"
latest() { ls -t reports/eval/"$1"-2*.json | head -1; }

if [[ "$step" == all || "$step" == distill ]]; then
  lab data distill
  lab data build --version d0.2
fi
if [[ "$step" == all || "$step" == baseline ]]; then
  lab eval run gemma-4-12b-qat --mode fast --label "$base_label"
  lab eval run gemma-4-12b-qat --mode full --label "$base_label-full"
fi
if [[ "$step" == all || "$step" == ablate ]]; then
  for lr in 1e4 5e5; do
    lab train run "configs/train/candela-pro-v0.1-lr$lr.yaml" --run-id "candela-pro-v0.1-lr$lr" --stop-at 150
    lab eval run gemma-4-12b-qat --mode fast --adapter "runs/candela-pro-v0.1-lr$lr/adapter" --label "ablate-lr$lr-s150" \
      --suite fpb --suite fiqa_sa --suite headlines --suite finqa --suite convfinqa --suite tatqa \
      --suite financebench --suite ifeval --suite tool_use
  done
fi
if [[ "$step" == all || "$step" == train ]]; then
  lab train resume "$run_id"
fi
if [[ "$step" == all || "$step" == eval ]]; then
  lab eval run gemma-4-12b-qat --mode full --adapter "runs/$run_id/adapter" --label "$run_id-full"
fi
if [[ "$step" == all || "$step" == export ]]; then
  lab export gguf "$run_id" --lora --check
  lab eval compare "$(latest "$base_label-full")" "$(latest "$run_id-full")" --model-id candela-pro-v0.1
  lab observatory galaxy candela-pro-v0.1 --adapter "runs/$run_id/adapter"
  lab observatory export "$run_id" --sync
  lab publish "$run_id" --dry-run --base-report "$(latest "$base_label-full")" \
    --tuned-report "$(latest "$run_id-full")"
fi
echo "queue step '$step' finished"
