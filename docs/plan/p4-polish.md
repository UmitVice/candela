# Phase 4 · Release — Portfolio polish and v0.1.0 (`p4-polish`)

- Area you own: `apps/web/**`, `docs/**` (except `docs/plan/`), Hugging Face model and dataset cards, GitHub repository metadata and releases, `docs/status/p4-polish.md`. Propose `README.md` content to the Director by writing `docs/readme-draft.md`; the Director merges it.
- Runs alone or alongside non-web work.
- Inputs: all status reports, `deploy/recordings/`, published evaluation reports.

## Goal

Make Candela read like the work of a senior AI engineer in the first 30 seconds: a polished live demo, a crisp README, honest evaluation, and a clear story of the engineering decisions.

## Deliverables

1. Bundle the real recordings from `deploy/recordings/` as the replay gallery (selectable from the command palette and the offline banner); retire the hand-written fixtures.
2. UI polish pass from a fresh-eyes review on desktop and mobile: spacing, typography rhythm, empty states, loading skeletons, error copy, keyboard shortcuts sheet (`?`), about dialog (model card summary, data sources, disclaimer, links to GitHub and Hugging Face).
3. `docs/readme-draft.md`: hero screenshot/GIF (terminal and Observatory), one-paragraph pitch, live demo link with how live vs replay works, architecture diagram (Mermaid), model section (base model, method, data mix, hardware, training time, evaluation table base vs tuned), feature tour, local quickstart (`make` targets), repository map, engineering decisions (link ADRs), data sources and licenses, limitations and responsible-use note, "not financial advice".
4. `docs/case-study.md`: problem, constraints (zero cost, shared 24 GB laptop, no hosted CI), architecture, model work (data curation, synthetic tool traces through the production tool layer, resource-guarded training, evaluation), results with numbers, what I would do next.
5. Media: GIFs/screenshots captured from the local build (Playwright via `pnpm dlx`, headless), optimised (PNG/WebP ≤ 500 kB, GIF ≤ 4 MB) under `docs/media/`.
6. Hugging Face cards: final model cards (intended use, limitations, evaluation, training details, license inheritance from the base model, citation), dataset card for the published synthetic data.
7. GitHub: description, homepage, topics; release `v0.1.0` with notes generated from Conventional Commits (`gh release create`).
8. One production deploy at the end.

## Acceptance

- `make web-check` passes; Lighthouse (local, mobile) Performance ≥ 85, Accessibility ≥ 95, Best Practices ≥ 95, PWA installable.
- README draft, case study, cards and release published; links verified.
- Report written to `docs/status/p4-polish.md`.
