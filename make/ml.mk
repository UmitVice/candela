ML_DIR := ml
ML_RUN := cd $(ML_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv run
ML_BG := caffeinate -i nice -n 10

.PHONY: ml-sync ml-doctor ml-data ml-traces-fake ml-eval-baseline ml-probe ml-train-pilot ml-observatory ml-check ml-format

ml-sync: ## Install the pinned Candela Lab environment (uv)
	cd $(ML_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv sync --frozen

ml-doctor: ## Versions, Metal device, memory headroom and guard decision
	$(ML_RUN) lab doctor

ml-data: ## Fetch sources and build dataset d0.1 (splits, manifest, data card)
	$(ML_RUN) lab data fetch --version d0.1
	$(ML_RUN) lab data build --version d0.1

ml-traces-fake: ## Generate 200 synthetic traces against the fake executor and validate them
	$(ML_RUN) lab traces generate --n 200 --executor fake --out data/traces/fake-200.jsonl
	$(ML_RUN) lab traces validate data/traces/fake-200.jsonl

ml-eval-baseline: ## Fast baseline evaluation of the lite base and both pro candidates (guarded, slow)
	$(ML_RUN) $(ML_BG) lab eval run qwen3-1.7b --mode fast
	$(ML_RUN) $(ML_BG) lab eval run qwen3-8b --mode fast
	$(ML_RUN) $(ML_BG) lab eval run gemma-4-12b --mode fast

ml-probe: ## 20-step QLoRA probes of both pro candidates at max_seq_length 2048
	$(ML_RUN) $(ML_BG) lab train run configs/train/probe-qwen3-8b.yaml --probe
	$(ML_RUN) $(ML_BG) lab train run configs/train/probe-gemma-4-12b.yaml --probe

ml-train-pilot: ## Lite pilot run with a simulated pause, then eval, fuse and GGUF export
	$(ML_RUN) $(ML_BG) lab train run configs/train/pilot-qwen3-1.7b.yaml --run-id pilot-qwen3-1.7b --simulate-pause-at 60
	$(ML_RUN) $(ML_BG) lab eval run qwen3-1.7b --adapter runs/pilot-qwen3-1.7b/adapter --label candela-1.7b-pilot
	$(ML_RUN) lab export fuse pilot-qwen3-1.7b
	$(ML_RUN) lab export gguf pilot-qwen3-1.7b --quant Q4_K_M
	$(ML_RUN) lab observatory export pilot-qwen3-1.7b --sync

ml-observatory: ## Rebuild the Observatory manifest and sync artifacts into apps/web
	$(ML_RUN) lab observatory export --sync

ml-format: ## Format Candela Lab sources
	cd $(ML_DIR) && uv run ruff format src && uv run ruff check --fix src

ml-check: ## Ruff format check, ruff lint and pyright for Candela Lab
	cd $(ML_DIR) && uv run --frozen ruff format --check src
	cd $(ML_DIR) && uv run --frozen ruff check src
	cd $(ML_DIR) && uv run --frozen pyright
