# p2-web — status

STATUS: done

Summary:
Candela Terminal now runs live against the gateway and is deployed to https://candela-terminal.netlify.app in `auto` mode. Discovery is still empty, so production shows replay with the banner "The live gateway has not been published yet."

- Live mode: `/status` is polled every 30 s while the tab is visible, and again on focus or `visibilitychange` (throttled to 5 s). The pill shows `PRO · <displayName> <version> · GPU|CPU` or one of `BUSY`, `REPLAY`, `OFFLINE`. The status line shows `live · ws|sse`, `queue d/max`, `queued #n` for the active turn and a market-throttle warning.
- Streams: a WebSocket that drops before the first reasoning, token or tool event is reopened once. Esc cancels, and so does any router navigation or switching to another conversation. A `rate_limited` or `overloaded` error with `retryAfterMs` shows a countdown and a "retry automatically" checkbox (on by default, last turn only). Queued turns show their position, ETA and a single-GPU note. An `upstream_unavailable` or `upstream_timeout` error, or a failed poll, re-probes the gateway and switches to replay without a reload.
- Cards: tool lines that carry UI data open by default. Each card loads inside `@defer (on viewport)` with a placeholder sized for its kind, and a `ResizeObserver` keeps the log pinned.
  - Quote: day-range bar with an open→close span, 52-week marker, volume against the 30-day average, distance from the 52-week high.
  - Price chart (Lightweight Charts): candlesticks and volume, a 1M–5Y range switcher that refetches, a crosshair OHLCV legend, a TradingView link.
  - Indicators: three panes (price with SMA 20/50/200 and Bollinger bands, RSI 14 with 30/70 lines, MACD histogram with line and signal), a 6M/1Y/2Y switcher, a crosshair legend, the indicator table and signal chips coloured by tone.
  - Fundamentals: periods as columns, B/M formatting, "—" for missing values, highlighted margin and YoY growth rows.
  - Forecast fan (ECharts): P10–P90 band and P50 line from the base price, a base mark line, badges for source ("Statistical baseline") and method, plus the table.
  - Symbol search: selectable chips that focus the symbol and prefill `/analyze`.
- Context panel: follows the most recent tool symbol, or the watchlist or chip selection when that is newer. It shows the quote, a 3M mini chart on canvas, key indicators and signals, a forecast mini-fan, the source and `asOf`.
- Watchlist: add and remove (persisted) and batch quote refresh. The refresh runs every 5 min and backs off exponentially from 15 s to 10 min when a batch fails, keeping the last quotes and showing a "delayed" hint. Each row has a 1M canvas sparkline and an aria label with up/down. Keyboard: roving tabindex, ↑/↓/Home/End, Enter prefills `/analyze`, Delete removes.
- Prompt: symbol autocomplete for `$sym` anywhere and for the arguments of slash commands, through `/api/v1/market/search` (160 ms debounce, 10 min cache, replay uses the fixture universe).
- Palette (Cmd/Ctrl+K): commands, live symbol search, conversations, settings (reasoning on/off, telemetry on/off, model `auto` or Candela Pro only) and layout actions.
- Feedback: 👍/👎 opens an inline form with an optional reason (≤ 500 characters) and an explicit consent checkbox. It posts `/api/v1/feedback` and sends a transcript only with consent. It shows a confirmation once and never sends twice.
- Market data layer: `MarketService` handles quote, history, indicators, fundamentals, forecast and search. It caches per gateway origin (quotes 5 min, other data 1 h), caches 404s as "no data", pauses all market calls on 429 using `Retry-After`, and uses fixtures in replay.
- Accessibility and performance:
  - Up/down cues use ▲/▼ plus colour everywhere.
  - Charts carry `role="img"` with summary labels. `aria-live` announces finished answers, including token-limit stops without text.
  - Lazy chunks: Lightweight Charts 48 kB gzip, ECharts (tree-shaken setup) 149 kB, cards 11 kB. Initial JS is 201.7 kB gzip (limit 250).
  - Turns use `contain: layout style` and plots use `contain: strict`, so streaming does not shift the layout.
- Dependabot: `vite` is overridden to 8.3.5 in `pnpm-workspace.yaml`, because `@angular/build` 22.2.4 pins 8.3.0. `pnpm audit` reports no known vulnerabilities.
- Fixed p1 bugs found while testing:
  - The CDK live announcer was not visually hidden: `a11y-prebuilt.css` was missing, so it added page height and showed text.
  - The reasoning timer stuck at 0.0 s once streams reach about 10 tok/s.
  - `sr-only` labels escaped the scrollback clip and made the whole shell scroll in long sessions.

Commits: 2fb1393 build(web): override vite to 8.3.5 and add chart libraries, 4b12fef fix(web): hide live announcer and keep the reasoning timer ticking, de0d233 feat(web): live market data, status polling and resilient chat streams, ed6b39b feat(web): chart cards with Lightweight Charts and ECharts behind defer, 482faf7 feat(web): context panel, watchlist sparklines, symbol autocomplete, d20fb0e fix(web): contain scrollback overflow and let the wheel scroll the log, c49441b fix(web): admit empty HTML in Trusted Types and skip probing without a gateway, bcd219f docs(adr): record terminal live charts and Trusted Types decisions, plus the commit adding this report and `docs/media/`.

Verified:
- `make web-check`: Prettier clean, `ng lint` with no errors, production build. `check-bundle` reports initial JS of 201.7 kB gzip. `pnpm audit --audit-level high` found no known vulnerabilities, and the lockfile resolves `vite@8.3.5`.
- Local stack: my own gateway (`make gateway-run`, 8710/8719) and the dev `llama-server` (Qwen3 1.7B Q4_K_M, CPU) on 8712, with `ng serve` proxying.
  - WS: `/analyze NVDA` streamed reasoning, then tool lines with quote, indicators (three panes), forecast fan and fundamentals cards from real snapshot data, and ended with a usage footer (`1024 tok · 13.3 tok/s · TTFT 13.5 s · truncated · max tokens`; the base model spends its budget thinking). `/chart TSLA 1Y` rendered the candlestick card; the 5Y switch loaded 1 255 bars, the crosshair legend tracked OHLCV and the headline and stats followed the range.
  - SSE (`chatTransport: sse`, local config only): a company-name question produced the `search_symbols` chips card, a written answer and a usage footer.
  - Every card type rendered real gateway data at least once across these turns.
- Feedback: 👎 with a reason and consent returned 202. The gateway row has `rating -1`, the reason, `consent 1` and the transcript JSON.
- Robustness:
  - `kill -9` on the gateway mid-stream showed an inline `upstream_unavailable — The connection to the gateway closed early.` after one reconnect attempt. The banner switched to "The gateway disconnected mid-session. Switched to replay…" and the pill to `OFFLINE`, without a reload. Reconnect then went back to live.
  - SIGTERM drains instead: the answer completed, and the next status poll switched to replay.
  - SSE burst past the chat limit (via curl) gave `rate_limited` with a countdown and auto-retry. The retry succeeded with a quote card.
  - Queue depth 1 with one running chat: the UI turn showed `queued · position 1 · ~28 s` and `queued #1`. With the queue also full, it got `overloaded` with the single-GPU message, a countdown and `queue 1/1` in the status line.
  - Esc and switching to the Observatory both cancelled the stream; the gateway logged `outcome: cancelled` over WS.
- Prompt autocomplete: `compare $micro` listed MSFT, MU, SMCI, AMD, …; Tab inserted `$AMD `. Watchlist keys moved focus with ↓/End, and Enter prefilled `/analyze GOOGL`.
- Layouts at 1440×900, 768×1024 and 375×812: `scrollWidth == clientWidth` at tablet and mobile. Charts resize with the container, and the context bottom sheet opens on mobile.
- Production build under the real headers (`make web-preview`, `WEB_MODE=auto`): Lightweight Charts and ECharts render, and the ECharts tooltip works. Zero `securitypolicyviolation` events. The default policy admits `innerHTML = ''` and rejects markup.
- One production deploy (`WEB_MODE=auto make web-deploy`, netlify-cli 27.14.2, `--no-build`), deploy `6ade90d15936628e2e98d5fc`. The live `config.json` has `mode: auto` with empty discovery. The CSP keeps `connect-src 'self'` and `/` is `no-cache`. On the live site, `/analyze NVDA` replays with charts and no violations.
- Screenshots in `docs/media/`, all PNG under 310 kB: `p2-web-desktop-analyze.png`, `p2-web-gateway-lost.png`, `p2-web-rate-limited.png`, `p2-web-overloaded.png`, `p2-web-tablet.png`, `p2-web-mobile-chart.png`, `p2-web-mobile-context.png`.
- Cleanup: the gateway, `llama-server`, `ng serve`, the preview server and the curl load are all stopped. Ports 4200, 4210, 8710, 8712 and 8719 are free, and no foreign process was touched.

Decisions:
- ADR 0101 (Lightweight Charts and ECharts, Trusted Types, lazy cards):
  - The TradingView logo is replaced by a visible text link, because the logo is injected via `innerHTML`.
  - Mouse-wheel zoom on charts is off so the wheel scrolls the log.
  - ECharts runs without ngx-echarts, from a tree-shaken setup module, with a richText tooltip.
  - The `default` Trusted Types policy admits only the empty string for HTML sinks.
  - Cards open by default behind `@defer`.
  - In production, `auto` mode with no discovery URL and no API base goes straight to replay.
  - The model preference is mapped to `auto` or the pro model id from `/status`.
- Deviations:
  - ngx-echarts 22.0.0 is not used.
  - The palette's "model preference" is `auto` or Candela Pro only (single tier).
  - The dev `llama-server` stands in for the worker, so the pill reads `PRO · Qwen3 1.7B base (dev fallback) base · CPU` in local tests.

Open issues / risks:
- The base dev model rarely calls all six tools in one turn and often hits `finishReason: length` while thinking. All card types were verified across several live turns, not within one `/analyze`. Re-run with the fine-tuned worker once p2-worker lands.
- Rate limits at WebSocket upgrade (HTTP 429) are invisible to browsers: the socket just fails, so the client shows `upstream_unavailable` instead of a `rate_limited` countdown. SSE shows the countdown correctly.
- `BUSY` derives from `workers[].state` and `route`. The status carries no explicit "declined for memory" reason.
- 60 fps scrolling on a mid-range phone was not measured on hardware. Layout containment and lazy charts are in place, and desktop and emulated-mobile scrolling is smooth.
- Service worker: returning visitors get the new version through the update toast; first-time visitors load it directly.

Notes for the next phases:
- Proposals for the Director (`contracts/api.md`, gateway):
  - Accept the WS upgrade and send `{type:"event", event:"error", data:{code:"rate_limited", retryAfterMs}}` before closing 1000, so browsers can show the countdown.
  - Optionally add `workers[].reason: 'memory' | 'training'` to `/status` for a precise `BUSY` tooltip.
  - Drop `'lite'` from `ModelInfo.tier`, as already proposed in p1-web.
- p3-deploy: deploy with `WEB_MODE=auto WEB_DISCOVERY_URL=<gist raw URL>`. `render-dist` then adds the discovery origin and `*.trycloudflare.com` (https and wss) to `connect-src`. Add `https://candela-terminal.netlify.app` to the gateway's `CANDELA_ALLOWED_ORIGINS`; it is already in the example. Everything else in the web app is ready for live use.
- Observatory phase: `PreferencesStore.telemetry` exists and is sent as `options.telemetry`. The turn reducer still ignores `telemetry` frames, so hook the Observatory stream there.
