# 0002 — Zero-cost deployment topology

- Status: accepted
- Date: 2026-10-23

## Context

The fine-tuned model needs an Apple Silicon GPU (MLX) and runs on the owner's MacBook, which is online only part of the day. The project must cost nothing and must not require new accounts. Facts checked on 2026-10-23:

- Hugging Face requires PRO to create Docker Spaces (HTTP 402 for free accounts since July 2026). The owner's one pre-existing Docker Space belongs to another project and is not ours to repurpose.
- Netlify's free plan is credit-based (300 credits/month, 15 per production deploy, 20 per GB of bandwidth); proxied rewrites cut streams at about 26 s.
- Cloudflare quick tunnels need no account but buffer streamed HTTP responses (measured: SSE and NDJSON arrived in one burst after 5 s), while WebSocket frames stream in real time (measured: 1 s cadence preserved). Their hostname changes on every start.
- Render, Koyeb, ngrok, Tailscale Funnel and Microsoft Dev Tunnels all need a new account or an interactive login.

## Decision

- **Web**: the Angular PWA is static on Netlify (`candela-terminal`), deployed from locally built files at milestones only. Large binaries (model weights) are never served from Netlify.
- **Gateway and GPU worker**: both run on the Mac. The worker still dials the gateway through the worker protocol, so either can move to another machine later without code changes.
- **Public edge**: `cloudflared` quick tunnel to the gateway's public listener. Browser chat uses WebSocket (`/api/v1/chat/ws`); REST endpoints are plain HTTP. Internal routes (tool execution for training, metrics, worker connect) live on a separate loopback listener that is never tunnelled.
- **Discovery**: a supervisor script starts the tunnel, reads its hostname and publishes an endpoint document to a public GitHub Gist with the already-authenticated `gh`; the PWA reads it at startup.
- **Offline behaviour**: when the gateway is unreachable the PWA switches to replay mode with real recorded sessions of the fine-tuned model (labelled with model version and date). A later phase adds an in-browser "lite" model (WebGPU) that executes tools against precomputed static data.
- **Model distribution**: adapters, merged weights, GGUF and browser builds are published to the owner's Hugging Face namespace, which serves them through a CORS-enabled CDN.

## Consequences

- Live chat with the 8B-class model works whenever the Mac is on; visitors otherwise get an honest, instant replay experience.
- Each tunnel restart changes the hostname; the Gist update propagates within minutes.
- No uptime guarantee from quick tunnels; acceptable for a portfolio demo and replaceable by configuration.

## Upgrade paths

- Stable hostname: a named Cloudflare tunnel on an owner domain, or Dev Tunnels after a one-time login.
- Always-on gateway: run the existing container image on any small host; the worker connects to it over `wss://`.
- Hugging Face PRO would allow a Docker Space for the gateway and a CPU fallback model.

## Alternatives considered

- Reusing the owner's existing private Docker Space: it serves another project.
- Netlify proxy in front of the tunnel: streams are cut at ~26 s.
- Serving SSE through the quick tunnel: buffered, measured.
