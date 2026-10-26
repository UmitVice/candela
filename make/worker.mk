WORKER_DIR := services/worker
WORKER_ENV := MACOSX_DEPLOYMENT_TARGET=14.0
WORKER_RUN := cd $(WORKER_DIR) && $(WORKER_ENV) uv run --frozen
WORKER_DOTENV := set -a; [ -f .env ] && . ./.env; set +a
WORKER_BENCH_ARGS ?=

.PHONY: worker-sync worker-serve worker-connect worker-bench worker-doctor worker-check worker-format

worker-sync: ## Install the pinned worker environment (uv)
	cd $(WORKER_DIR) && $(WORKER_ENV) uv sync --frozen

worker-serve: ## Development OpenAI-compatible API on 127.0.0.1:8711 (services/worker/.env)
	cd $(WORKER_DIR) && $(WORKER_DOTENV) && $(WORKER_ENV) exec uv run --frozen candela-worker serve

worker-connect: ## Connect the worker to the gateway (services/worker/.env: URL, token, model id)
	cd $(WORKER_DIR) && $(WORKER_DOTENV) && $(WORKER_ENV) exec caffeinate -i uv run --frozen candela-worker connect

worker-bench: ## TTFT, tokens/s, peak memory and telemetry overhead (WORKER_BENCH_ARGS="--model … --kv-tokens 6000")
	cd $(WORKER_DIR) && $(WORKER_DOTENV) && $(WORKER_ENV) uv run --frozen candela-worker bench $(WORKER_BENCH_ARGS)

worker-doctor: ## Versions, Metal device, memory headroom, leases and model paths
	cd $(WORKER_DIR) && $(WORKER_DOTENV) && $(WORKER_ENV) uv run --frozen candela-worker doctor

worker-format: ## Apply ruff formatting and safe fixes to the worker
	$(WORKER_RUN) ruff format src
	$(WORKER_RUN) ruff check --fix src

worker-check: ## Ruff format check, ruff lint, pyright and pip-audit for the worker
	$(WORKER_RUN) ruff format --check src
	$(WORKER_RUN) ruff check src
	$(WORKER_RUN) pyright
	cd $(WORKER_DIR) && uv export --frozen --format requirements-txt --no-emit-project --no-hashes -o /tmp/candela-worker-req.txt >/dev/null && \
		set -o pipefail; $(WORKER_ENV) uv run --frozen pip-audit --strict --progress-spinner off --cache-dir .venv/.pip-audit \
			-r /tmp/candela-worker-req.txt --disable-pip --no-deps 2>&1 | grep -v '^WARNING'
