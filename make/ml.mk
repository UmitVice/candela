ML_DIR := ml
ML_RUN := cd $(ML_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv run
ML_BG := caffeinate -i nice -n 10

.PHONY: ml-sync ml-doctor ml-data ml-gateway-up ml-gateway-down ml-traces ml-distill ml-probe ml-release ml-observatory ml-check ml-format

ml-sync: ## Install the pinned Candela Lab environment (uv)
	cd $(ML_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv sync --frozen

ml-doctor: ## Versions, Metal device, memory headroom and guard decision
	$(ML_RUN) lab doctor

ml-data: ## Fetch sources and build dataset d0.2 (run ml-traces and ml-distill first)
	$(ML_RUN) lab data fetch --version d0.2
	$(ML_RUN) lab data build --version d0.2

ml-gateway-up: ## Run Candela Lab's own gateway on 127.0.0.1:8730/8739 (internal tool API for traces)
	$(ML_DIR)/scripts/gateway-ml.sh start

ml-gateway-down: ## Stop Candela Lab's gateway
	$(ML_DIR)/scripts/gateway-ml.sh stop

ml-traces: ml-gateway-up ## Generate and validate the d0.2 train and held-out traces through the real gateway
	$(ML_RUN) lab traces generate --executor gateway --n 300 --split heldout --seed 7 --out data/eval/tool_use-d0.2.jsonl
	$(ML_RUN) lab traces generate --executor gateway --n 6000 --split train --seed 11 --out data/traces/d0.2/gateway-6000.jsonl
	$(ML_RUN) lab traces validate data/traces/d0.2/gateway-6000.jsonl

ml-distill: ## Base self-distilled retention samples for d0.2 (guarded GPU job, resumable)
	$(ML_RUN) $(ML_BG) lab data distill

ml-probe: ## 20-step QLoRA probes at 2048 and 3072 tokens
	$(ML_RUN) $(ML_BG) lab train run configs/train/probe-l16.yaml --run-id probe-l16-2k --probe
	$(ML_RUN) $(ML_BG) lab train run configs/train/probe-l16-3k.yaml --run-id probe-l16-3k --probe

ml-release: ## Candela Pro v0.1 GPU queue: baseline, training, evaluation, export (see ml/scripts/p2-gpu-queue.sh)
	cd $(ML_DIR) && $(ML_BG) scripts/p2-gpu-queue.sh all

ml-observatory: ## Rebuild the Observatory manifest and sync artifacts into apps/web
	$(ML_RUN) lab observatory export --sync

ml-format: ## Format Candela Lab sources
	cd $(ML_DIR) && uv run ruff format src && uv run ruff check --fix src

ml-check: ## Ruff format check, ruff lint and pyright for Candela Lab
	cd $(ML_DIR) && uv run --frozen ruff format --check src
	cd $(ML_DIR) && uv run --frozen ruff check src
	cd $(ML_DIR) && uv run --frozen pyright
