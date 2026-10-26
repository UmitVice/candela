WEB_DIR := apps/web
WEB_NETLIFY_SITE := 29663355-ecbd-43e8-8b32-9fade3ae572b
WEB_NETLIFY := pnpm --package=netlify-cli@27.14.2 dlx netlify
WEB_VERSION = $(shell node -p "require('./$(WEB_DIR)/package.json').version")

.PHONY: web-install web-dev web-lint web-format web-build web-check web-render web-preview web-deploy web-icons web-telemetry-worker

web-install: ## Install web dependencies from the lockfile
	cd $(WEB_DIR) && pnpm install --frozen-lockfile

web-dev: ## Serve the web app on :4200, proxying /api to the gateway on :8710
	cd $(WEB_DIR) && pnpm exec ng serve --port 4200

web-lint: ## Lint TypeScript and templates
	cd $(WEB_DIR) && pnpm exec ng lint

web-format: ## Format the web sources with Prettier
	cd $(WEB_DIR) && pnpm exec prettier --write .

web-build: ## Production build into apps/web/dist and check the initial JS budget
	cd $(WEB_DIR) && GOMAXPROCS=4 pnpm exec ng build --configuration production
	node $(WEB_DIR)/scripts/check-bundle.mjs

web-check: ## Format check, lint, production build and bundle budget
	cd $(WEB_DIR) && pnpm exec prettier --check .
	$(MAKE) --no-print-directory web-lint
	$(MAKE) --no-print-directory web-build

web-render: ## Render config.json and the CSP connect-src into dist (WEB_MODE, WEB_API_BASE_URL, WEB_DISCOVERY_URL, ...)
	node $(WEB_DIR)/scripts/render-dist.mjs

web-preview: web-build web-render ## Serve the rendered production dist with Netlify headers on :4210
	node $(WEB_DIR)/scripts/preview.mjs

web-deploy: web-check web-render ## Deploy the locally built dist to Netlify (production, no remote build)
	cd $(WEB_DIR) && $(WEB_NETLIFY) deploy --prod --no-build --dir dist --site $(WEB_NETLIFY_SITE) --message "candela-web $(WEB_VERSION) $$(git rev-parse --short HEAD)"

web-icons: ## Regenerate PNG icons from the brand mark
	cd $(WEB_DIR) && node scripts/generate-icons.mjs

web-telemetry-worker: ## Dev only: synthetic telemetry worker for the Observatory, dialing the local gateway (8719)
	@set -a; [ -f services/gateway/.env ] && . services/gateway/.env; set +a; exec node $(WEB_DIR)/scripts/telemetry-worker.mjs
