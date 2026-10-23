SHELL := /bin/bash
.DEFAULT_GOAL := help

-include make/*.mk

.PHONY: help hooks secrets-scan

help: ## List available targets
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

hooks: ## Use the versioned git hooks in .githooks
	git config core.hooksPath .githooks

secrets-scan: ## Scan the full git history for secrets
	gitleaks git --redact --no-banner .
