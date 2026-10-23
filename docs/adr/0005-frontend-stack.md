# 0005 — Frontend stack

- Status: accepted
- Date: 2026-10-23

## Context

The web app must be a mobile-first, installable PWA with a dense terminal-style chat, financial charts and an optional 3D view of the model, deployed as static files.

## Decision

- Angular 22 (standalone, zoneless, signals, OnPush by default) with `@ngrx/signals` for state and Angular CDK for accessible primitives (overlay, dialog, menu, virtual scroll).
- Tailwind CSS 4 mapped onto CSS custom-property design tokens; self-hosted variable fonts (Inter, JetBrains Mono).
- `@angular/service-worker` for the PWA; IndexedDB (`idb`) for conversations.
- TradingView Lightweight Charts for price series, Apache ECharts for analytical charts (forecast fans, training curves, eval comparisons).
- Plain three.js (plus `postprocessing`) for the Observatory, lazy-loaded. `angular-three` was evaluated but does not support Angular 22.
- Markdown from the model rendered with `marked` and sanitized with `DOMPurify`.

## Consequences

- Heavy dependencies (charts, three.js) stay out of the initial bundle through lazy routes and `@defer`.
- Owning the three.js integration costs some glue code but avoids a wrapper that lags Angular releases.

## Alternatives considered

- Angular Material components: solid, but its visual language fights the terminal aesthetic; CDK gives the behaviour without the look.
- React/Next.js: the owner requested Angular.
