# p1-web — status

STATUS: done

Summary:
Candela Terminal is live at https://candela-terminal.netlify.app in replay mode, replacing the placeholder. `apps/web` is an Angular 22 PWA (zoneless, OnPush, signals, standalone, new control flow) with pnpm 11.28.6, strict TypeScript 6.0.3, angular-eslint flat config and Prettier. Design system: CSS tokens mapped into Tailwind 4, self-hosted Inter and JetBrains Mono variable fonts, `@lucide/angular` icons, CDK overlay/dialog/menu/a11y/scrolling/clipboard/layout primitives.

- Shell: top bar (brand, Terminal | Observatory switch, model pill `PRO · <model> <version> · GPU` / `BUSY` / `REPLAY` / `OFFLINE` with a reasoning toggle, palette, install, context toggle), left rail (watchlist with quotes, sessions with new/rename/export/delete), right context panel (focus quote, session status, shortcuts), status line. Desktop ≥ 1280 inline panels (rail collapsible to 56 px); tablet icon rail plus slide-overs; mobile compact bar, sticky prompt with command chips, bottom sheets for navigation, context and status, `100dvh`, safe areas, 44 px targets, 16 px input.
- Terminal: boot sequence (once per session, skippable, instant under reduced motion), scrollback that pins only until the user scrolls, user turns `❯`, assistant header `candela · <version> · PRO`, live-then-collapsed reasoning with timer, tool lines that expand into quote, history (sparkline + bars), indicators, fundamentals, forecast, symbols and raw-JSON cards, Markdown via `marked` + DOMPurify with terminal tables and streaming cursor, footer with tokens, tok/s, TTFT, copy, 👍/👎, regenerate; inline errors with retry and a `retryAfterMs` countdown; prompt with Shift+Enter, ↑/↓ history, Esc stop, `/` autocomplete, Ctrl/Cmd+K palette; all slash commands from the brief (`/model` reports the single tier).
- Transports: `ChatTransport` with `WsChatTransport` (`candela.chat.v1`, start/cancel frames), `SseChatTransport` (fetch + incremental WHATWG SSE parser + `AbortController`, error bodies and `Retry-After`) and `ReplayChatTransport` playing `RecordedSession` events with timing. Discovery reads the endpoint document, probes `/api/v1/status`, falls back to replay with a banner and rechecks every 2 min and on `online`.
- Replay fixtures (`src/app/core/chat/mock/fixtures/`): single-stock analysis, comparison, company-name resolution through `search_symbols`, unknown ticker (`not_found`), fundamentals `data_unavailable`, forecast, chart, general help and rate limiting (8 requests/min or the phrase "rate limit"); 25–40 tok/s with jitter; `/status` and quotes mocked by the same layer. Numbers are generated deterministically and labelled illustrative (ADR 0100).
- State: `@ngrx/signals` SignalStore persisted to IndexedDB (`idb`), multiple sessions, Markdown export; preferences, watchlist and prompt history in localStorage.
- PWA: service worker (prefetch shell, lazy assets, freshness for `config.json`), manifest, generated icons (32, 192, 512, maskable 512, apple-touch 180, favicon SVG) from the brand mark via `sharp`, update toast, install action.
- Netlify: `_headers` (strict CSP with `__CONNECT_SRC__` rendered at deploy, Trusted Types, HSTS, nosniff, frame deny, referrer, permissions, COOP/CORP, immutable hashed bundles, no-cache for `index.html`, `ngsw.json`, `ngsw-worker.js`, `config.json`), `_redirects` SPA fallback, runtime `config.json`.
- `make/web.mk`: `web-install`, `web-dev` (4200, `/api` and WebSocket proxy to 8710), `web-lint`, `web-format`, `web-build` (with the initial-JS gzip gate), `web-check`, `web-render`, `web-preview` (4210, rendered headers), `web-deploy`, `web-icons`.

Commits: 9d750ae build(web): scaffold Angular 22 workspace with pinned toolchain, f23b1ae feat(web): add brand mark, PWA icons, manifest and Netlify headers, 0349ba7 feat(web): add chat transports, replay fixtures and conversation store, ef09e58 feat(web): build terminal shell, streaming turns and observatory teaser, 9cda165 fix(web): stabilize scroll pinning, mobile layout and replay intents, 80dff94 feat(web): adopt single PRO tier pill states and Trusted Types policy, 7d376cc docs(adr): record web terminal foundation decisions, plus the commit adding this report and the `/observatory` cache-rule fix.

Verified:
- `make web-check`: Prettier clean, `ng lint` with zero warnings, production build without budget warnings; initial JS 196.4 kB gzip (main 115.5 + shared chunk 80.8; limit 250). The Observatory route is a 2.4 kB lazy chunk.
- Browser preview at 1440×900, 768×1024 and 375×812: layouts match the spec, `scrollWidth == clientWidth` with no element overflowing at any size, sheets and slide-overs work. Replayed sessions stream with reasoning, tool lines, expandable cards, tables, footer, Esc stop, regenerate, rate-limit countdown, unknown-ticker handling, company-name resolution, `/help`, palette and autocomplete.
- `make web-preview` with production headers: no CSP or Trusted Types violations from app code; the service worker registers and controls the page; with the preview server stopped (`curl` → 000) the app and the lazy `/observatory` route reload offline; after a rebuild with a changed service-worker manifest, the "A new version of Candela is ready" toast appears and Reload activates it.
- One production deploy (`make web-deploy`, netlify-cli 27.14.2, `--no-build`, replay mode). `curl -I` shows the CSP (`connect-src 'self'`, Trusted Types), nosniff, `X-Frame-Options: DENY`, referrer and permissions policies, COOP/CORP, HSTS, `immutable` on hashed bundles, `no-cache` on `/`, `ngsw.json`, `config.json`. The live site streams `/analyze NVDA` and its service worker is active.

Decisions:
- ADR 0100: `--fg-2` is `#7a8592` (the brief's `#6b7684` is 4.3:1 on `--bg-0`); generated deterministic fixtures; DOMPurify as the trust boundary; a `default` Trusted Types policy limited to the worker scripts; runtime-rendered config and `connect-src`; single-tier pill; local preview server.
- Following the Director: no lite tier. `/model` reports the model instead of switching tiers; the tier menu is gone; the pill uses the four states above. The brief's `PRO|LITE` header now always shows `PRO`.
- `dist/` is the deploy root (`outputPath.browser = ""`).

Open issues / risks:
- The `/observatory/*` cache rule also matched the `/observatory` SPA route on the deployed build (`max-age=300` on `index.html` there). Fixed in the repo (`/observatory/*.json`); it reaches production with the next deploy. The service worker serves navigations, so returning visitors are unaffected.
- Netlify keeps its own HSTS (`max-age=31536000`) instead of our two-year value.
- Netlify's injected HUD script (`/.netlify/scripts/hud`) is blocked by Trusted Types when a Netlify-logged-in browser views the site. This is harmless and intended.
- WS and SSE transports were exercised only through types and code review, not against the running gateway (out of scope for this phase). `p2-web` should run them against `make gateway-run`.
- PWA installability rests on the criteria (manifest with 192/512/maskable icons, controlling service worker, HTTPS); the install prompt itself cannot be triggered in the embedded preview browser.
- An untracked `.claude/launch.json` (preview launch configs `web-dev` and `web-preview`) exists at the repository root; it is not committed.

Notes for the next phases:
- Replace fixtures with real recordings: `ReplayChatTransport.play(session)` accepts any `RecordedSession`; add a loader for recorded JSON (for example `/recordings/*.json`) and route by intent.
- Live mode: deploy with `WEB_MODE=auto WEB_DISCOVERY_URL=<gist raw URL>`. `render-dist` then adds the discovery origin and `*.trycloudflare.com` (https and wss) to `connect-src`. Local dev uses `config.json` `mode: auto` with the proxy to 8710.
- `GatewayService` probes status once per connect; `p2-web` adds the 30 s and on-focus polling. The pill already derives `BUSY` from `route: 'unavailable'` or no idle worker.
- Cards are generic; `p2-web` swaps `HistoryCard` and `ForecastCard` for lightweight-charts and ECharts behind `@defer`.
- Proposal for `contracts/api.md` (Director-owned): drop `'lite'` from `ModelInfo.tier` and the "else lite" wording in `ChatRequest.model` to match the single-tier decision.
