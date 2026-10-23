SPARK_DIR := spark
SPARK_RUN := cd $(SPARK_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv run --frozen
SPARK_BG := caffeinate -i nice -n 10
# Seatbelt profile that denies all network access: training must work offline.
SPARK_NONET := sandbox-exec -p '(version 1)(allow default)(deny network*)'

.PHONY: spark-sync spark-doctor spark-data spark-tokenizer spark-train spark-train-m1 spark-status spark-sample spark-eval spark-export spark-observatory spark-publish spark-daemon-install spark-daemon-uninstall spark-daemon-status spark-format spark-check

spark-sync: ## Install the pinned Candela Spark environment (uv)
	cd $(SPARK_DIR) && MACOSX_DEPLOYMENT_TARGET=14.0 uv sync --frozen

spark-doctor: ## Versions, Metal device, memory headroom, power, leases and data state
	$(SPARK_RUN) spark doctor

spark-data: ## Fetch pinned sources (SHA-256 verified), then filter, dedup, tokenize and index data v0
	$(SPARK_RUN) $(SPARK_BG) spark data fetch --version v0
	$(SPARK_RUN) $(SPARK_BG) spark data process --version v0 --stage all
	$(SPARK_RUN) spark data stats --version v0

spark-tokenizer: ## Build the balanced sample and train the frozen 32k byte-level BPE (once per family)
	$(SPARK_RUN) $(SPARK_BG) spark data process --version v0 --stage sample
	$(SPARK_RUN) $(SPARK_BG) spark tokenizer train

spark-train: ## Run or resume the continuous 35M run in the foreground, offline (no network for the process)
	$(SPARK_RUN) $(SPARK_BG) $(SPARK_NONET) spark train configs/train/spark-35m-main.yaml

spark-train-m1: ## Milestone-1 decay branch from the main run (lease priority 70), then export
	$(SPARK_RUN) $(SPARK_BG) $(SPARK_NONET) spark train configs/train/spark-35m-m1.yaml
	$(SPARK_RUN) spark export spark-35m-m1 spark-35m-m1

spark-status: ## Sanitised trainer status (~/.candela/spark/status.json)
	$(SPARK_RUN) spark status

spark-sample: ## Fixed-seed samples from the latest main-run checkpoint
	$(SPARK_RUN) spark sample spark-35m-main

spark-eval: ## Full evaluation of milestone 1 into spark/reports/
	$(SPARK_RUN) $(SPARK_BG) spark eval spark-35m-m1 --label spark-35m-m1

spark-export: ## Export milestone 1 to MLX int4, bf16 and GGUF Q4_1
	$(SPARK_RUN) spark export spark-35m-m1 spark-35m-m1

spark-observatory: ## Write Spark Observatory artifacts into apps/web/public/observatory/spark
	$(SPARK_RUN) spark observatory export

spark-publish: ## Publish milestone 1 to Hugging Face UmitVice/candela-spark-35m
	$(SPARK_RUN) spark publish --name spark-35m-m1

spark-daemon-install: ## Install the continuous-training LaunchAgent com.candela.spark-trainer
	$(SPARK_RUN) spark daemon install

spark-daemon-uninstall: ## Stop (checkpointing) and remove the LaunchAgent
	$(SPARK_RUN) spark daemon uninstall

spark-daemon-status: ## launchd state plus trainer status
	$(SPARK_RUN) spark daemon status

spark-format: ## Format Candela Spark sources
	cd $(SPARK_DIR) && uv run ruff format src && uv run ruff check --fix src

spark-check: ## Ruff format check, ruff lint, pyright and pip-audit for Candela Spark
	cd $(SPARK_DIR) && uv run --frozen ruff format --check src
	cd $(SPARK_DIR) && uv run --frozen ruff check src
	cd $(SPARK_DIR) && uv run --frozen pyright
	cd $(SPARK_DIR) && uv export --frozen --no-hashes --no-emit-project --format requirements-txt > .audit-requirements.txt && uv run --frozen pip-audit --strict --progress-spinner off -r .audit-requirements.txt; status=$$?; rm -f .audit-requirements.txt; exit $$status
