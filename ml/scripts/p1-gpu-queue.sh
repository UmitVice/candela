#!/usr/bin/env bash
# p1-ml GPU work in order; every step waits for memory headroom, foreign trainings and the GPU lease.
set -euo pipefail
cd "$(dirname "$0")/.."
step="${1:-all}"
lab() { uv run --frozen lab "$@"; }
peak() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['peak_mem_gb'])" "runs/$1/state.json"; }

if [[ "$step" == all || "$step" == probes ]]; then
  lab train run configs/train/probe-l16.yaml --run-id probe-l16-2k --probe
  lab train run configs/train/probe-l24.yaml --run-id probe-l24-2k --probe
  lab train run configs/train/probe-l16-4k.yaml --run-id probe-l16-4k --probe
  if python3 -c "import sys; sys.exit(0 if float('$(peak probe-l16-4k)') <= 9.0 else 1)"; then
    echo "4096 fits: pilot keeps maxSeqLength 4096"
  else
    sed -i '' 's/^maxSeqLength: 4096/maxSeqLength: 2048/' configs/train/pilot.yaml
    echo "4096 exceeds 9 GB: pilot falls back to 2048"
  fi
fi
if [[ "$step" == all || "$step" == baseline ]]; then
  lab eval run gemma-4-12b-qat --mode fast --label gemma-4-12b-qat-base
fi
if [[ "$step" == all || "$step" == pilot ]]; then
  lab train run configs/train/pilot.yaml --run-id pilot-candela-pro --simulate-pause-at 30 --simulate-recover-sec 30
  lab eval run gemma-4-12b-qat --mode fast --adapter runs/pilot-candela-pro/adapter --label candela-pro-pilot
fi
if [[ "$step" == all || "$step" == export ]]; then
  lab export gguf pilot-candela-pro --lora --check
  base=$(ls -t reports/eval/gemma-4-12b-qat-base-*.json | head -1)
  tuned=$(ls -t reports/eval/candela-pro-pilot-*.json | head -1)
  lab eval compare "$base" "$tuned" --model-id candela-pro-pilot
  lab observatory export pilot-candela-pro --sync
  lab publish pilot-candela-pro --dry-run
fi
echo "queue step '$step' finished"
