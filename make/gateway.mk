GATEWAY_DIR       := services/gateway
GATEWAY_BIN       := $(GATEWAY_DIR)/bin
GATEWAY_DATA      := $(GATEWAY_DIR)/data
GATEWAY_GO        := cd $(GATEWAY_DIR) && GOMAXPROCS=4 GOFLAGS=-mod=mod
GATEWAY_VERSION   ?= 0.1.0-dev
GATEWAY_COMMIT    ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
GATEWAY_LDFLAGS   := -s -w -X main.version=$(GATEWAY_VERSION) -X main.commit=$(GATEWAY_COMMIT)
GATEWAY_CONTRACTS := tools.json system-prompt.md

LITE_REPO     ?= unsloth/Qwen3-1.7B-GGUF
LITE_FILE     ?= Qwen3-1.7B-Q4_K_M.gguf
LITE_ADDR     ?= 127.0.0.1
LITE_PORT     ?= 8712
LITE_THREADS  ?= 4
LITE_CTX      ?= 16384
LITE_PID      := $(GATEWAY_DATA)/llama-server.pid
LITE_LOG      := $(GATEWAY_DATA)/llama-server.log

.PHONY: gateway-contracts gateway-contracts-check gateway-sqlc gateway-build gateway-run gateway-snapshot \
	gateway-lite-up gateway-lite-down gateway-fakeworker gateway-workerctl gateway-check

gateway-contracts: ## Copy contracts/ files embedded by the gateway
	@for f in $(GATEWAY_CONTRACTS); do cp contracts/$$f $(GATEWAY_DIR)/internal/contracts/$$f; done
	@echo "gateway contracts refreshed"

gateway-contracts-check:
	@for f in $(GATEWAY_CONTRACTS); do \
		cmp -s contracts/$$f $(GATEWAY_DIR)/internal/contracts/$$f || { echo "contract drift: $$f (run make gateway-contracts)"; exit 1; }; \
	done

gateway-sqlc: ## Regenerate sqlc query code
	$(GATEWAY_GO) go tool sqlc generate

gateway-build: ## Build gateway, snapshot, workerctl and fakeworker binaries
	$(GATEWAY_GO) CGO_ENABLED=0 go build -trimpath -ldflags "$(GATEWAY_LDFLAGS)" -o bin/ ./cmd/...

gateway-run: gateway-build ## Run the gateway on 8710/8719 with services/gateway/.env
	@set -a; [ -f $(GATEWAY_DIR)/.env ] && . $(GATEWAY_DIR)/.env; set +a; exec $(GATEWAY_BIN)/gateway

gateway-snapshot: gateway-build ## Build the market snapshot SQLite file from Hugging Face datasets
	@mkdir -p $(GATEWAY_DATA)
	@set -a; [ -f $(GATEWAY_DIR)/.env ] && . $(GATEWAY_DIR)/.env; set +a; \
		caffeinate -i nice -n 10 $(GATEWAY_BIN)/snapshot

gateway-lite-up: ## Download the lite GGUF and run llama-server on 127.0.0.1:8712
	@mkdir -p $(GATEWAY_DATA)
	@if [ -f $(LITE_PID) ] && kill -0 $$(cat $(LITE_PID)) 2>/dev/null; then echo "llama-server already running (pid $$(cat $(LITE_PID)))"; exit 0; fi; \
	model=$$(hf download $(LITE_REPO) $(LITE_FILE) --quiet) || exit 1; \
	nohup nice -n 10 llama-server --model "$$model" --alias qwen3-1.7b --host $(LITE_ADDR) --port $(LITE_PORT) \
		--jinja --ctx-size $(LITE_CTX) --threads $(LITE_THREADS) --parallel 1 --n-gpu-layers 0 --no-webui \
		>$(LITE_LOG) 2>&1 & echo $$! > $(LITE_PID); \
	for i in $$(seq 1 60); do curl -sf http://$(LITE_ADDR):$(LITE_PORT)/health >/dev/null && { echo "llama-server ready on $(LITE_ADDR):$(LITE_PORT) (pid $$(cat $(LITE_PID)))"; exit 0; }; sleep 1; done; \
	echo "llama-server did not become ready; see $(LITE_LOG)"; exit 1

gateway-lite-down: ## Stop the llama-server started by gateway-lite-up
	@if [ -f $(LITE_PID) ]; then kill $$(cat $(LITE_PID)) 2>/dev/null || true; rm -f $(LITE_PID); echo "llama-server stopped"; else echo "llama-server not running"; fi

gateway-fakeworker: gateway-build ## Run the scripted fake worker against the local gateway
	@set -a; [ -f $(GATEWAY_DIR)/.env ] && . $(GATEWAY_DIR)/.env; set +a; exec $(GATEWAY_BIN)/fakeworker

gateway-workerctl: gateway-build ## Generate a worker token and print a sample hello
	@$(GATEWAY_BIN)/workerctl

gateway-check: gateway-contracts-check ## Format check, vet, lint, build and vulnerability-scan the gateway
	@out=$$(cd $(GATEWAY_DIR) && gofmt -l .); if [ -n "$$out" ]; then echo "gofmt needed:"; echo "$$out"; exit 1; fi
	$(GATEWAY_GO) go vet ./...
	$(GATEWAY_GO) golangci-lint run ./...
	$(GATEWAY_GO) CGO_ENABLED=0 go build -trimpath ./...
	$(GATEWAY_GO) go tool govulncheck ./...
