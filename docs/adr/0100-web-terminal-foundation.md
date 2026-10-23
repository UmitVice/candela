# 0100 — Web terminal foundation decisions

- Status: accepted
- Date: 2026-10-23

## Context

`p1-web` ships the Candela Terminal PWA in replay mode before any fine-tuned model exists, under a strict CSP on Netlify, with the visual tokens from the brief and a shared contract that later dropped the lite tier.

## Decision

- **Text contrast**: `--fg-2` is `#7a8592` instead of the brief's `#6b7684`, which measures 4.32:1 on `--bg-0` and 3.86:1 on `--bg-2`. The new value keeps the hue and reaches ≥ 4.75:1 on every background.
- **Replay fixtures are generated, not hand-typed bar by bar**: recorded sessions (`RecordedSession`, exactly the stream events of `contracts/api.md`) are produced deterministically from a small instrument table: seeded Brownian bridges through anchor closes give daily bars; indicators follow the contract definitions (SMA, EMA seeded by SMA, Wilder RSI/ATR, MACD, Bollinger with population σ); answers interpolate the same numbers, so every figure in a replayed answer exists in its tool results. The data is labelled "illustrative" everywhere. Real recordings from the fine-tuned model replace them later through the same `ReplayChatTransport.play()`.
- **Markdown trust boundary**: `marked` output with raw HTML escaped, then DOMPurify with an allowlist; the result is bound with `bypassSecurityTrustHtml` because DOMPurify is the sanitizer of record and a second pass per streamed token is wasted work.
- **Trusted Types**: the CSP sets `require-trusted-types-for 'script'` with policies `angular`, `angular#unsafe-bypass`, `dompurify` and a `default` policy installed before bootstrap that only admits same-origin `ngsw-worker.js` / `safety-worker.js` (Angular registers the worker with a plain string). Without it the service worker, and therefore offline mode, is blocked.
- **Runtime configuration only**: `config.json` and the CSP `connect-src` are rendered into `dist` by `scripts/render-dist.mjs` from `WEB_*` variables; `connect-src` is `'self'` in replay mode and adds the discovery origin plus `*.trycloudflare.com` (https and wss) when discovery is enabled.
- **Single tier**: the model pill shows `PRO · <displayName> <version> · GPU`, `BUSY`, `REPLAY` or `OFFLINE`; `/model` reports the model instead of switching tiers.
- **Local preview**: `make web-preview` serves the rendered `dist` with a dependency-free Node server that applies `_headers` and the SPA fallback, dropping only HSTS and `upgrade-insecure-requests`, which cannot work on plain-http loopback.

## Consequences

- Production headers are exercised locally before every deploy, including Trusted Types and the service worker.
- Initial JS is ~196 kB gzip (budget 250 kB), checked by `scripts/check-bundle.mjs` in `make web-check`.
- Replay numbers are internally consistent but not market data; the UI says so.

## Alternatives considered

- Keeping `#6b7684`: fails the brief's own 4.5:1 requirement.
- Dropping Trusted Types: simpler, but loses a cheap defence for an app that renders model output.
- Hand-writing every bar and indicator in JSON: large, error-prone fixtures whose numbers drift from the prose.
