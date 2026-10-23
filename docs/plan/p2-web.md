# Phase 2 · Web — Terminal live (`p2-web`)

- Area you own: `apps/web/**` (except `apps/web/public/observatory/`, written by `ml/` tooling), `make/web.mk`, `docs/status/p2-web.md`, new ADRs.
- Runs in parallel with `p2-train` and `p2-worker`.
- Inputs: `CLAUDE.md`, `docs/status/p1-web.md`, `docs/status/p1-gateway.md`, `contracts/`.

## Goal

Turn the terminal into the real product: live chat through the gateway (WebSocket in production, SSE locally), rich financial result cards, market panels driven by the gateway, and resilient offline/replay behaviour.

## Deliverables

1. Live mode against the local gateway (`make gateway-run`, port 8710, dev lite model or the worker): status polling (every 30 s and on focus) drives the model pill (`PRO · Candela <size> <version> · GPU`, `REPLAY`, `OFFLINE`), route badge, queue position UI and the status line.
2. Tool result cards (lazy, `@defer` on viewport):
   - Quote card (price, change, range bar for day and 52-week, volume vs 30-day average).
   - Price chart with Lightweight Charts: candlesticks + volume, range switcher, crosshair legend; keep TradingView attribution.
   - Indicators view: price with SMA20/50/200 and Bollinger overlays, RSI and MACD sub-panes, signal chips coloured by tone.
   - Fundamentals table: periods as columns, margins and growth highlighted, compact number formatting (B/M), missing values as "—".
   - Forecast fan chart with ECharts: P10–P90 band and P50 line per horizon from the base price, source and method badge; `baseline` is labelled "Statistical baseline".
   - Symbol search results as selectable chips.
3. Context panel: follows the most recent symbol in the conversation (or the selected watchlist item): quote, mini chart, key indicators, forecast mini-fan, data source and `asOf`.
4. Watchlist: add/remove (persisted), batch quote refresh with backoff, sparklines (tiny canvas), keyboard navigation; clicking a symbol pre-fills `/analyze`.
5. Symbol autocomplete in the prompt (`$NVDA` or after slash commands) through `/api/v1/market/search` with debounce and caching.
6. Command palette (Cmd/Ctrl+K): commands, symbols, conversations, settings (reasoning on/off, telemetry on/off, model preference).
7. Robustness: `rate_limited` countdown and auto-retry option, `overloaded` queue messaging, reconnect on WebSocket drop before the first token (once), cancel on Esc and on navigation, graceful degradation to replay when the gateway disappears mid-session.
8. Feedback (👍/👎 with optional reason and explicit consent checkbox for storing the transcript) posting to `/api/v1/feedback`.
9. Performance and quality: initial Terminal route JS ≤ 250 kB gzip, charts and ECharts lazy; no layout shift while streaming; 60 fps scroll on mid-range phones; `aria-live` announcements for completed answers; colour-blind-safe up/down cues (arrows plus colour).
10. One production deploy at the end, still in `auto` mode (discovery → live when the owner's gateway is online, otherwise replay). The discovery Gist is created in `p3-deploy`; until then `discoveryUrl` stays empty and production behaves as replay.

## Acceptance (verify by running; no automated tests)

- `make web-check` passes.
- With the local gateway and dev model: a full "Analyze NVDA" turn streams over WebSocket with reasoning, tool lines, every card type rendering real data, and a correct usage footer; the same works over SSE.
- Mobile, tablet and desktop previews are clean; charts resize; bottom sheets work with touch.
- Killing the gateway mid-stream produces a clear error and a switch to replay mode without a reload.
- Report written to `docs/status/p2-web.md` with screenshots saved under `docs/media/` (PNG, ≤ 500 kB each).

## Out of scope

The Observatory (next phase), gateway changes (propose them in your report), tests.
