DEPLOY_DIR      := deploy
DEPLOY_ENV      := $(DEPLOY_DIR)/.env
DEPLOY_ENDPOINT := $(DEPLOY_DIR)/local/endpoint.json
EDGE_BIN        := services/gateway/bin/edge
EDGE_LOG_DIR    := $(HOME)/Library/Logs/Candela
EDGE_STATE      := $(HOME)/.candela/edge/state.json
EDGE_AGENT      := $(HOME)/Library/LaunchAgents/com.candela.edge.plist
EDGE_PID         = $$(jq -r '.supervisorPid // 0' $(EDGE_STATE) 2>/dev/null || echo 0)

.PHONY: live-init live-tokens live-up live-down live-status live-logs live-agent-install live-agent-uninstall \
	live-web-deploy live-sandbox-proof live-adversarial deploy-check

live-init: live-tokens ## Generate live tokens and create the public discovery Gist once
	@$(EDGE_BIN) init

live-tokens: gateway-build ## Generate deploy/.env with fresh tokens (openssl rand) if it is missing
	@umask 077; if [ ! -f $(DEPLOY_ENV) ]; then \
		cp $(DEPLOY_DIR)/.env.example $(DEPLOY_ENV); \
		sed -i '' "s|^CANDELA_WORKER_TOKEN=.*|CANDELA_WORKER_TOKEN=$$(openssl rand -base64 32)|; s|^CANDELA_METRICS_TOKEN=.*|CANDELA_METRICS_TOKEN=$$(openssl rand -base64 32)|" $(DEPLOY_ENV); \
		echo "generated $(DEPLOY_ENV) (tokens not shown)"; \
	else echo "$(DEPLOY_ENV) exists"; fi

live-up: gateway-build ## Start gateway, worker and the Cloudflare quick tunnel; publish the endpoint
	@[ -f $(DEPLOY_ENV) ] || { echo "run make live-init first"; exit 1; }
	@pid=$(EDGE_PID); if [ "$$pid" -gt 0 ] && kill -0 $$pid 2>/dev/null; then echo "edge already running (pid $$pid)"; exit 0; fi; \
	mkdir -p $(EDGE_LOG_DIR); start=$$(date +%s); \
	nohup $(EDGE_BIN) run >>$(EDGE_LOG_DIR)/edge.log 2>&1 & pid=$$!; \
	nohup /usr/bin/caffeinate -i -w $$pid >/dev/null 2>&1 & \
	for i in $$(seq 1 120); do \
		state=$$(jq -r 'select(.supervisorPid == '$$pid') | .state' $(EDGE_STATE) 2>/dev/null); \
		case "$$state" in online|local) echo "live: $$state in $$(( $$(date +%s) - start )) s $$(jq -r '.gatewayUrl // ""' $(EDGE_STATE))"; exit 0;; esac; \
		kill -0 $$pid 2>/dev/null || { echo "edge exited; see make live-logs"; tail -n 5 $(EDGE_LOG_DIR)/edge.log; exit 1; }; \
		sleep 1; \
	done; echo "edge still $$state after 120 s; see make live-logs"; exit 1

live-down: ## Publish offline, close the tunnel and stop gateway and worker
	@pid=$(EDGE_PID); if [ "$$pid" -gt 0 ] && kill -0 $$pid 2>/dev/null; then \
		kill -TERM $$pid; for i in $$(seq 1 200); do kill -0 $$pid 2>/dev/null || { echo "edge stopped"; exit 0; }; sleep 1; done; \
		echo "edge did not stop in 200 s"; exit 1; \
	else echo "edge not running"; fi

live-status: ## Supervisor state, gateway URL, per-process RSS and gateway route
	@$(EDGE_BIN) status

live-logs: ## Follow the edge, gateway, worker and cloudflared logs
	@tail -n 20 -F $(EDGE_LOG_DIR)/edge.log $(EDGE_LOG_DIR)/gateway.log $(EDGE_LOG_DIR)/worker.log $(EDGE_LOG_DIR)/cloudflared.log

live-agent-install: gateway-build ## Install the optional login agent (owner decision; not done automatically)
	@sed -e "s|__REPO__|$$(pwd -P)|g" -e "s|__HOME__|$(HOME)|g" $(DEPLOY_DIR)/local/com.candela.edge.plist > $(EDGE_AGENT)
	@plutil -lint $(EDGE_AGENT) && launchctl bootstrap gui/$$(id -u) $(EDGE_AGENT) && echo "installed $(EDGE_AGENT)"

live-agent-uninstall: ## Remove the optional login agent (stops the live stack)
	@launchctl bootout gui/$$(id -u) $(EDGE_AGENT) 2>/dev/null || true; rm -f $(EDGE_AGENT); echo "login agent removed"

live-web-deploy: ## Production web deploy with discovery, WebSocket transport and the live CSP
	@[ -f $(DEPLOY_ENDPOINT) ] || { echo "run make live-init first"; exit 1; }
	@set -a; . ./$(DEPLOY_DIR)/netlify/production.env; set +a; \
		WEB_DISCOVERY_URL=$$(jq -r .rawUrl $(DEPLOY_ENDPOINT)) $(MAKE) --no-print-directory web-deploy

live-sandbox-proof: gateway-build ## Prove that each Seatbelt profile denies secrets, exec and foreign ports
	@$(DEPLOY_DIR)/security/sandbox-proof.sh

live-adversarial: ## Run the ADR 0008 adversarial checks against the live tunnel (URL from the edge state)
	@$(DEPLOY_DIR)/security/adversarial.sh "$$(jq -r '.gatewayUrl // ""' $(EDGE_STATE))"

deploy-check: ## Compile the Seatbelt profiles, lint scripts, plist and JSON, scan deploy/ for secrets
	@for p in gateway cloudflared; do \
		sandbox-exec -f $(DEPLOY_DIR)/sandbox/$$p.sb -D BIN=/usr/bin/true -D HOME=$(HOME) -D SNAPSHOT=/dev/null \
			-D STATE_DIR=/nonexistent -D SPARK_STATUS=/dev/null /usr/bin/true || { echo "profile $$p failed"; exit 1; }; done
	@sandbox-exec -f $(DEPLOY_DIR)/sandbox/worker.sb -D PYTHON=/usr/bin/true -D PYTHON_HOME=/nonexistent -D VENV=/nonexistent \
		-D WORKER_DIR=/nonexistent -D MODELS_CONFIG=/dev/null -D LEASE_DIR=/nonexistent -D TMP_DIR=/nonexistent -D USER_CACHE=/nonexistent/ \
		-D HOME=$(HOME) -D READ_0=/x -D READ_1=/x -D READ_2=/x -D READ_3=/x -D READ_4=/x -D READ_5=/x -D PYTHON_APP=/usr/bin/true /usr/bin/true || { echo "profile worker failed"; exit 1; }
	@echo "sandbox profiles compile"
	shellcheck $(DEPLOY_DIR)/security/*.sh
	plutil -lint $(DEPLOY_DIR)/local/com.candela.edge.plist
	@if [ -f $(DEPLOY_ENDPOINT) ]; then jq -e '.gistId and .rawUrl' $(DEPLOY_ENDPOINT) >/dev/null && echo "$(DEPLOY_ENDPOINT) OK"; fi
	@for f in $(DEPLOY_DIR)/recordings/*.json; do [ -f "$$f" ] || continue; jq -e '.version == 1 and (.events | length > 0)' "$$f" >/dev/null || { echo "bad recording $$f"; exit 1; }; done
	@git ls-files -co --exclude-standard $(DEPLOY_DIR) | while read -r f; do gitleaks dir "$$f" --no-banner --redact --log-level error || exit 1; done && echo "gitleaks: no leaks in tracked or unignored deploy files"
