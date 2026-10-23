# Phase 1 · Web — Terminal foundation (`p1-web`)

- Area you own: `apps/web/**`, `make/web.mk`, `docs/status/p1-web.md`, new ADRs.
- Runs in parallel with `p1-gateway` and `p1-ml`. Do not touch their paths.
- Inputs: `CLAUDE.md`, `docs/plan/00-master-plan.md`, `contracts/api.md`, `contracts/tools.md`, `contracts/observatory.md`.

## Goal

A production-grade, installable, mobile-first Angular PWA shell for **Candela Terminal**: a professional, Bloomberg-inspired chat terminal for equity research. It streams from a mock transport that follows the real SSE contract, so it can go live on Netlify today and switch to the real gateway by configuration later.

## Deliverables

1. Angular workspace at `apps/web` (pinned versions from `CLAUDE.md`), pnpm, strict TypeScript, standalone components, zoneless change detection, signals everywhere, OnPush, new control flow, `@defer` for heavy UI. ESLint (angular-eslint flat config) and Prettier clean.
2. Design system: CSS custom-property tokens + Tailwind CSS v4 theme mapping, self-hosted variable fonts via `@fontsource-variable/inter` and `@fontsource-variable/jetbrains-mono`, icon set (lucide via a maintained Angular package), primitives built on Angular CDK (overlay, a11y, dialog/bottom sheet, menu, scrolling).
3. App shell with responsive layouts, top bar with **Terminal | Observatory** mode switch (Terminal is the default; Observatory is a lazy route showing an elegant "coming online" teaser in this phase), model status pill, left rail (watchlist + conversations), right context panel, bottom status line.
4. Terminal experience: scrollback, prompt input with history and slash commands, streaming Markdown answers, collapsible reasoning, tool-call lines with expandable result cards, usage footer, copy and feedback actions, boot sequence.
5. Chat transport layer: `ChatTransport` interface with `WsChatTransport` (WebSocket `candela.chat.v1`, primary in production), `SseChatTransport` (fetch + `ReadableStream` SSE parser, `AbortController`) and `ReplayChatTransport` (plays recorded sessions as specified in `contracts/api.md`; this phase ships hand-written recordings shaped exactly like the stream events and `contracts/tools.md` UI views). Gateway discovery: read the endpoint document (`contracts/api.md`), probe `/api/v1/status`, and fall back to replay mode with a clear banner when offline.
6. Conversation state with `@ngrx/signals` SignalStore, persisted to IndexedDB (`idb`), multiple conversations, new/rename/delete, export as Markdown.
7. PWA: `@angular/service-worker`, web manifest, generated icons (192, 512, maskable 512, apple-touch 180, favicon SVG), offline app shell, update toast, install action.
8. Netlify: `public/_headers` (strict CSP whose `connect-src` comes from a `__CONNECT_SRC__` placeholder rendered at deploy time, HSTS, nosniff, referrer and permissions policies, immutable caching for hashed assets, no-cache for `index.html`, `ngsw.json`, `ngsw-worker.js`, `config.json`), `public/_redirects` (SPA fallback), runtime `public/config.json`, and `make web-deploy` that builds, renders the placeholders into `dist`, and deploys with the Netlify CLI to site `candela-terminal`. Deploy once at the end of the phase in replay mode with a visible "Replay — recorded demo" badge.
9. `make/web.mk`: `web-install`, `web-dev` (port 4200 with proxy `/api` → `http://localhost:8710`), `web-lint`, `web-build`, `web-check` (format check + lint + production build), `web-preview` (serves `dist` locally with the rendered headers), `web-deploy`.

## Visual identity

Dark-only in v1. Calm, dense, precise; glow only for brand and focus.

| Token | Value | Use |
|---|---|---|
| `--bg-0` | `#07090c` | app background |
| `--bg-1` | `#0c1015` | panels |
| `--bg-2` | `#121821` | raised, hover |
| `--line` / `--line-strong` | `#1d2633` / `#2a3646` | borders, dividers |
| `--fg-0` / `--fg-1` / `--fg-2` | `#e8edf3` / `#aab4c0` / `#6b7684` | text levels |
| `--accent` | `#f5a524` | candle-flame amber: prompt glyph, focus, primary actions |
| `--flame` | `linear-gradient(135deg,#ffd27a,#f5a524 45%,#ff6a2b)` | brand mark, active mode |
| `--up` / `--down` | `#2ebd85` / `#f6465d` | price moves |
| `--info` / `--tool` / `--reason` / `--warn` | `#38bdf8` / `#2dd4bf` / `#a78bfa` / `#fbbf24` | semantic accents |

- Mono (JetBrains Mono, tabular numbers) for terminal content and all numbers; Inter for chrome and labels. Base 13 px mono on desktop, 14 px on mobile, line height ≈ 1.55. 8 px grid, radii 4–6 px, 1 px borders.
- Motion 120–180 ms ease-out, blinking caret, streaming cursor `▋`; honour `prefers-reduced-motion`.
- Brand: SVG mark of a candlestick whose wick ends in a small flame; wordmark "candela" in lowercase mono. Generate all icons from it with a small Node script using `sharp` (dev dependency) and commit the PNGs.

## Layout

- Desktop ≥ 1280 px: top bar 44 px; left rail 260 px (collapsible to 56 px); centre terminal with content max-width ≈ 920 px and the prompt pinned to the bottom; right context panel 320 px (collapsible); status line 24 px.
- Tablet 768–1279 px: rail collapsed to icons, context panel as slide-over.
- Mobile < 768 px: compact top bar, full-width terminal, sticky prompt with a horizontally scrollable row of command chips, watchlist/context/conversations as bottom sheets, status details in a sheet. Use `100dvh`, safe-area insets, no horizontal scrolling, 44 px touch targets, input font ≥ 16 px to avoid iOS zoom.

## Terminal behaviour

- User turn: `❯ analyze NVDA` (amber glyph), muted timestamp.
- Assistant turn: header `candela · <version> · PRO|LITE`; collapsible reasoning `▸ thinking · 1.8 s` (dim violet, streams live, collapsed after the answer starts); tool lines `⚙ get_price_history NVDA · 6M  ✓ 126 bars · 42 ms` (teal) that expand into result cards (this phase: generic quote/table/JSON renderers; rich charts arrive in `p2-web`); answer Markdown rendered with `marked` + `DOMPurify` (never trust model HTML) and terminal-styled tables; footer `412 tok · 18.3 tok/s · TTFT 0.9 s` with copy, 👍/👎 and regenerate.
- Errors render inline in red with retry affordances (`rate_limited` shows a countdown from `retryAfterMs`).
- Input: multiline (Shift+Enter), Enter sends, ↑/↓ history, Esc stops generation, Cmd/Ctrl+K command palette, `/` opens slash-command autocomplete. Commands: `/analyze <SYM>`, `/compare <SYM> <SYM>…`, `/chart <SYM> [range]`, `/fundamentals <SYM>`, `/forecast <SYM>`, `/watch <SYM>`, `/unwatch <SYM>`, `/new`, `/clear`, `/model auto|pro|lite`, `/reasoning on|off`, `/observatory`, `/help`, `/about`. Analysis commands expand to natural-language prompts; the rest act locally.
- Boot sequence on first load per session (≈ 1.2 s, skippable, instant with reduced motion): product line, gateway connection, inference route, market data freshness, hint line with "Not financial advice."
- Accessibility: `aria-live="polite"` region announcing completed answers (not every token), focus management, visible focus rings, colour contrast ≥ 4.5:1 for text.

## Replay recordings (mock data in this phase)

Scenarios keyed by intent: single-stock analysis (reasoning → `get_quote`, `get_price_history`, `get_technical_indicators`, `get_forecast` → answer), comparison of two tickers, unknown company resolved through `search_symbols`, data unavailable, rate-limited error. Fixtures in `src/app/core/chat/mock/fixtures/` match `contracts/tools.md` UI views; token timing ≈ 25–40 tok/s with jitter so it feels real. `/status` and market endpoints are mocked by the same layer. Later phases replace these fixtures with real recordings from the fine-tuned model.

## Runtime configuration

`public/config.json` loaded before bootstrap: `{ "apiBaseUrl": "", "discoveryUrl": "", "chatTransport": "ws" | "sse", "mode": "replay" | "live" | "auto", "environment": "development" | "production", "release": "<semver>" }`. `auto` = discovery → live gateway when reachable, else replay. Production values are written into `dist` by `make web-deploy`; nothing environment-specific is compiled in.

## Acceptance (verify by running; no automated tests)

- `make web-check` passes with zero warnings that matter; initial JS ≤ 250 kB gzip for the Terminal route (Observatory and charts lazy).
- In a browser preview at desktop, tablet and mobile sizes the layout matches the spec, there is no horizontal scroll, and the replayed conversation streams with reasoning, tool lines, cards and footer.
- The app installs as a PWA, reloads offline into the shell, and shows the update toast after a redeploy.
- Exactly one production deploy at the end of the phase: `https://candela-terminal.netlify.app` serves the replay-mode build (replacing the current placeholder page) with the security headers present (`curl -I`).
- Report written to `docs/status/p1-web.md`.

## Out of scope

Real gateway integration, charts, Observatory 3D content, i18n, light theme, authentication, tests.
