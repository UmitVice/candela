# 0101 — Terminal live mode: chart libraries, Trusted Types and lazy cards

- Status: accepted
- Date: 2026-10-26

## Context

Phase `p2-web` turns tool results into charts (Lightweight Charts for prices and indicators, ECharts for the forecast fan) and talks to the live gateway. The production CSP enforces Trusted Types (`require-trusted-types-for 'script'`, ADR 0100) and the initial Terminal route must stay under 250 kB gzip. Both chart libraries write to `innerHTML`: Lightweight Charts injects its TradingView logo as an SVG string, and zrender (ECharts) clears its container with `innerHTML = ''` on init and dispose. Both calls throw under Trusted Types without a policy.

## Decision

- **Lightweight Charts 5.2.1**: `layout.attributionLogo` is off; every chart carries a visible "chart by TradingView Lightweight Charts™" link to tradingview.com, which the library licence accepts as attribution. Mouse-wheel scroll and scale are off so the wheel scrolls the terminal log; drag, pinch and axis scaling still work, and vertical touch drags scroll the page.
- **ECharts 6.1.0 without ngx-echarts**: a small `echarts-setup.ts` imports only `LineChart`, grid, tooltip, mark line and the canvas renderer (149 kB gzip lazy chunk instead of ~320 kB with namespace imports). One component owns `init`, a `ResizeObserver` and `dispose`; a wrapper library adds nothing here. The tooltip uses `renderMode: 'richText'` so it draws on the canvas and never builds HTML.
- **Trusted Types**: the existing `default` policy gains `createHTML` that admits exactly the empty string and throws for anything else. Clearing a node cannot inject markup, so the trust boundary stays DOMPurify (Markdown) and Angular's own policies.
- **Cards**: tool lines with UI data open by default and render their card inside `@defer (on viewport)` with a placeholder sized per card kind, so cards and chart libraries never enter the initial bundle and lazily loaded cards do not shift the log. A `ResizeObserver` keeps the log pinned to the bottom while pinned.
- **Live behaviour**: `/status` is polled every 30 s while visible and on focus; a failed poll or a stream that ends with `upstream_unavailable` re-probes and switches to replay without a reload. A WebSocket that drops before the first reasoning, token or tool event is reopened once. In production, `auto` mode without a discovery URL or API base goes straight to replay ("not published yet") instead of probing the static host.
- **Model preference**: the palette stores a tier (`auto` | `pro`); requests send `auto` or the concrete pro model id from `/status`, because the gateway accepts only `auto` or a model id.

## Consequences

- No CSP or Trusted Types violations in the rendered production build (`make web-preview`), including chart tooltips.
- The TradingView logo overlay is replaced by a text link under each chart.
- The `default` policy is slightly wider than in ADR 0100, but only for the empty string.

## Alternatives considered

- A DOMPurify-backed `createHTML` in the default policy: works for both libraries but would let any third-party sink pass sanitised markup; rejected as wider than needed.
- ngx-echarts 22.0.0 (pinned in the toolchain table): adds a module and zone-era wrapper for a single chart; not needed.
- SVG renderer for ECharts: uses more `innerHTML` paths and is heavier for the fan.
