# Candela — handbook for every agent session

Candela is a public portfolio project for a Senior AI Engineer profile: an open financial-analysis LLM fine-tuned locally on Apple Silicon, served by a Go gateway, used through a terminal-style Angular PWA with a 3D "Observatory" design view of the model. Owner: Ümit Vice (GitHub and Hugging Face: `UmitVice`).

Read before working: `docs/plan/00-master-plan.md` (vision, architecture, phases), your phase brief in `docs/plan/`, and `contracts/` (shared interfaces).

## Chain of command

You are a phase engineer started by the **Director** session. The owner is away and must never be asked anything.

- Decide autonomously inside your brief. Record non-obvious decisions as ADRs in `docs/adr/NNNN-title.md` (template `0000-template.md`).
- Never ask the owner questions, never wait for owner input, never use AskUserQuestion.
- Truly blocked only (missing credential, irreversible action outside your brief, a contract change another area depends on): reach a clean committed state, then end your turn with the report below whose first line is `STATUS: BLOCKED — <question>`. The Director replies by message.
- Never message the Director mid-turn; put questions in the end-of-turn report.

## Golden rules

1. English only: code, identifiers, commits, docs, UI copy.
2. No code comments unless they explain a non-obvious *why* (workaround, origin of a constant, security-sensitive choice). No commented-out code, no TODO banners, no docstring boilerplate.
3. **No tests** (unit, integration, e2e, snapshot) until the owner asks. Verify by building, linting, running and exercising behaviour (curl, CLI, browser preview).
4. Small, frequent Conventional Commits in English: `feat(web): …`, `fix(gateway): …`, `perf(worker): …`, `chore(ml): …`, `build: …`, `ci: …`, `docs: …`. Imperative, subject ≤ 72 chars. Push at every meaningful milestone (at least hourly).
5. Security first: never commit secrets, `.env` files, keys, tokens, model weights, datasets or databases; never print secret values in logs, docs or reports; never bypass hooks (`--no-verify`) or weaken `.gitignore` / `.gitleaks.toml`. Generate secrets with `openssl rand -base64 32` and keep them in git-ignored `.env` files or provider secret stores. Every service ships a `.env.example`.
6. Pinned, LTS or long-supported versions only (table below). Changing a major version needs an ADR.
7. Be a good neighbour on a shared 24 GB laptop (see Resource budget).
8. Production quality: typed, structured logging, graceful shutdown, timeouts, input validation, accessible UI, responsive layouts.
9. **No GitHub Actions or any hosted CI** (owner's quota). Quality gates run locally: `make <area>-check` (format, lint, type-check, build) must pass before every push.
10. **Deploy sparingly** (owner's Netlify credits): production deploys only at the milestones your brief names (at most one per phase), always uploading a locally built `dist` with the Netlify CLI; never trigger Netlify-side builds; verify locally first (`make web-preview`). Treat Hugging Face Space rebuilds the same way.

## Git in a shared checkout

Several phase sessions may work in this checkout at the same time, each in its own directories.

- Stage and commit only your own paths: `git add -- <paths> && git commit -m "<msg>" -- <paths>`.
- Forbidden: `git add -A`, `git add .`, `git commit -a`, `git stash`, `git reset --hard`, `git clean`, checking out or restoring other areas' paths, rebases of shared history, amending pushed commits, force pushes, new branches.
- `apps/web/public/observatory/` is written by ml sessions: web sessions always exclude it (`git add -- apps/web ':(exclude)apps/web/public/observatory'` and the same pathspec on `git commit`); ml sessions stage only that subfolder under `apps/web`.
- `index.lock` errors: wait 2–5 s and retry. Push with `git push origin main`; if rejected, `git pull --rebase origin main`, then push.
- Director-owned files: `README.md`, `CLAUDE.md`, root `Makefile`, root `.gitignore`, `.gitleaks.toml`, `.githooks/`, `docs/plan/`, `contracts/`. Propose changes to them in your report instead of editing. Area-specific make targets go in `make/<area>.mk` (always provide `<area>-check`), ignores in `<area>/.gitignore`. Do not add `.github/workflows`.

## Repository map

| Path | Purpose | Area |
|---|---|---|
| `apps/web` | Angular PWA: Terminal (default) and Observatory (3D design view) | web |
| `services/gateway` | Go API gateway: chat streaming, tool loop, market data, worker hub | gateway |
| `services/worker` | Python MLX inference worker (dials out to the gateway) | worker |
| `ml` | Candela Lab: data, training, evaluation, export, publishing; `ml/nano` holds Candela-Nano (from-scratch model) | ml |
| `deploy` | Hugging Face Space and Netlify deployment assets | deploy |
| `contracts` | Shared API, protocol, tool and artifact contracts | Director |
| `docs` | Plans, ADRs, status reports | all (own files) |

## Toolchain (pinned)

Verified on 2026-10-23. Pin exact versions in manifests and commit every lockfile (`pnpm-lock.yaml`, `go.sum`, `uv.lock`).

| Area | Pins | Notes |
|---|---|---|
| Node.js | 24 LTS (`engines.node: "^24.15.0 \|\| ^26.0.0"`) | Node 26 becomes Active LTS on 2026-10-28; the move is a later ADR |
| pnpm | 11.28.6 via `packageManager` | pnpm auto-manages the pinned version |
| Angular | core/forms/service-worker 22.2.3; cli/build/pwa/material/cdk 22.2.4 | zoneless and OnPush are defaults; Signal Forms stable |
| TypeScript | `~6.0.3` | never 7.x (unsupported by Angular 22 and typescript-eslint) |
| Lint/format | angular-eslint 22.6.0, eslint 10.13.0, typescript-eslint 8.72.0, Prettier 3 | |
| Styling | tailwindcss + @tailwindcss/postcss 4.3.3, postcss 8.5.31 | no Sass; `@apply` in component styles needs `@reference`; touch `styles.css` if `ng serve` misses classes in new files |
| 3D | three 0.186.1 (+ @types/three 0.186.0), postprocessing 6.39.5 | plain three.js; angular-three does not support Angular 22 |
| Charts | lightweight-charts 5.2.1 (keep TradingView attribution), echarts 6.1.0 + ngx-echarts 22.0.0 | |
| Go | 1.27.3 (`go 1.27`, `toolchain go1.27.3`) | golangci-lint v2.15.0 |
| Go libs | chi v5.5.0, coder/websocket v1.8.15, x/time v0.16.0, prometheus/client_golang v1.25.0, sqlc v1.31.1 and goose v3.29.0 as `go tool` deps, modernc.org/sqlite (latest) | |
| Python | 3.14 (3.14.9 via uv), `requires-python = ">=3.14,<3.15"` | uv-managed projects, ruff, pyright; set `MACOSX_DEPLOYMENT_TARGET=14.0` when resolving; fall back to 3.13 only via ADR |
| ML | mlx 0.32.4, mlx-lm 0.32.2, transformers 5.20.2, datasets 5.1.0, huggingface_hub 2.2.0, tokenizers 0.23.3, sentencepiece 0.2.2, gguf 0.19.0, numpy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1 | torch 2.14.1 only if a step truly needs it |
| Serving | fastapi 0.161.1, uvicorn 0.54.0, pydantic 2.14.1 | |
| llama.cpp | local `llama-server` (Homebrew build 9960) for the dev lite model; containers pin a `ghcr.io/ggml-org/llama.cpp` server tag | |
| Containers | `golang:1.27.3-trixie`, `python:3.14.9-slim-trixie` | Docker is not installed locally; images build on Hugging Face |
| Tooling | gitleaks 8.30.1, netlify-cli 27.14.2 (via `pnpm --package=netlify-cli@27.14.2 dlx netlify`) | |

## Local ports

Defaults: web `4200`, gateway public `8710` and internal `8719`, worker HTTP `8711`, dev lite model `llama-server` `8712`.

When phases run in parallel, each session that needs its own gateway uses its own port pair and SQLite file (`CANDELA_ADDR`, `CANDELA_INTERNAL_ADDR`, `CANDELA_DB_PATH`); the market snapshot file is shared read-only.

| Session | Gateway public / internal | Other |
|---|---|---|
| web phases | 8710 / 8719 | web 4200; owns the dev `llama-server` on 8712 |
| worker phases | 8720 / 8729 | worker HTTP 8711 |
| ml phases | 8730 / 8739 (internal tool API only) | |
| deploy phases | 8710 / 8719 after web sessions stop, otherwise 8740 / 8749 | |

Do not use, stop or reconfigure anything you did not start, especially the owner's `llama-server` on `8080`, PostgreSQL on `5432`, and services on `3150`, `4173`, `8786`.

## Resource budget

- The owner keeps working on other projects on this machine (often a 9 GB `llama-server`). Never kill, restart or reconfigure processes you did not start.
- Candela ML memory budget: training peak ≤ 9 GB; inference ≤ 8 GB for the pro model and ≤ 2 GB for lite, loaded only on demand. Use the resource guard in `ml/` (waits for headroom, checkpoints and pauses under memory pressure).
- Long jobs (training, evaluation, bulk downloads): `caffeinate -i nice -n 10 <cmd>`, run in the background, log under `ml/runs/<run-id>/`. You are notified when a background command exits: never busy-poll or sleep-loop in the foreground.
- Keep builds modest (`GOMAXPROCS=4`, no parallel heavy builds). Stop every server or watcher you started before ending your turn unless your brief says to keep it running.
- Models and datasets download to the shared Hugging Face cache (`~/.cache/huggingface`) or `ml/data/` (git-ignored), never into tracked paths.

## Accounts already authenticated on this machine

- GitHub CLI `gh` as `UmitVice` — repo `UmitVice/candela` (public).
- Hugging Face CLI `hf` as `UmitVice` — models, datasets and the Space live under this namespace.
- Netlify CLI (run as `pnpm --package=netlify-cli@27.14.2 dlx netlify …`) — site `candela-terminal`, id `29663355-ecbd-43e8-8b32-9fade3ae572b`, https://candela-terminal.netlify.app.

Never create accounts, change account settings, or copy tokens anywhere (including GitHub secrets). Deploys run from this machine with the existing CLI sessions.

## End-of-turn report

Write it as your final message and to `docs/status/<phase-id>.md` (commit it):

```
STATUS: done | partial | BLOCKED — <question>
Summary:
Commits: <short sha> <subject>, …
Verified: what you ran and what you observed
Decisions: ADRs added, deviations from the brief
Open issues / risks:
Notes for the next phases:
```
