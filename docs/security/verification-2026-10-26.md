# Security verification — 2026-10-26 (p3-deploy)

Scope: ADR 0008 adversarial checks run through a live Cloudflare quick tunnel and locally, against the stack started by `make live-up` (`cmd/edge`: gateway, MLX worker and `cloudflared`, each under its Seatbelt profile in `deploy/sandbox/`). The endpoint Gist was not published during these runs (`CANDELA_EDGE_PUBLISH=false`; see the status report), so the tunnel hostnames were random and unannounced. The worker served `candela-pro-v0.1` plus the dev model `qwen3-0.6b-dev` for the chat-based checks, because Candela Pro training held the GPU memory.

Reproduce: `make live-up`, then `make live-sandbox-proof` and `make live-adversarial` (or `deploy/security/adversarial.sh <url> <model>`).

## 1. Seatbelt denials (`make live-sandbox-proof`)

`sandbox-exec` works on macOS 27.0.1 (build 26A434). Each probe runs under the real profile; only the binary parameter points at the probe tool (`cat`, `ls`, `sh`, `nc`) or, for the worker, the worker's own Python. Every probe matched its expectation.

```
== gateway.sb
gateway      read <repo>/services/gateway/data/market.sqlite expect allowed got allowed ok
gateway      read ~/.ssh/known_hosts                          expect denied  got denied  ok
gateway      read ~/.ssh/config                               expect denied  got denied  ok
gateway      read ~/.config/gh/hosts.yml                      expect denied  got denied  ok
gateway      read ~/.cache/huggingface/token                  expect denied  got denied  ok
gateway      read ~/Library/Keychains/login.keychain-db       expect denied  got denied  ok
gateway      read <repo>/services/gateway/.env expect denied  got denied  ok
gateway      read <repo>/services/worker/.env expect denied  got denied  ok
gateway      read <repo>/deploy/.env    expect denied  got denied  ok
gateway      list ~/.ssh                                      expect denied  got denied  ok
gateway      list ~/.config/gh                                expect denied  got denied  ok
gateway      list ~/Library/Keychains                         expect denied  got denied  ok
gateway      list ~                                           expect denied  got denied  ok
gateway      spawn /bin/ls from /bin/sh                                 expect denied  got denied  ok
gateway      connect www.nasdaqtrader.com:443                           expect allowed got allowed ok
gateway      connect 127.0.0.1:5432                                     expect denied  got denied  ok
gateway      connect 127.0.0.1:8080                                     expect denied  got denied  ok
gateway      connect 127.0.0.1:8719                                     expect denied  got denied  ok
gateway      connect 127.0.0.1:8712                                     expect denied  got denied  ok
gateway      connect 192.168.1.1:80                                     expect denied  got denied  ok
gateway      connect 1.1.1.1:80                                         expect denied  got denied  ok
== cloudflared.sb
cloudflared  read ~/.ssh/known_hosts                          expect denied  got denied  ok
cloudflared  read ~/.ssh/config                               expect denied  got denied  ok
cloudflared  read ~/.config/gh/hosts.yml                      expect denied  got denied  ok
cloudflared  read ~/.cache/huggingface/token                  expect denied  got denied  ok
cloudflared  read ~/Library/Keychains/login.keychain-db       expect denied  got denied  ok
cloudflared  read <repo>/services/gateway/.env expect denied  got denied  ok
cloudflared  read <repo>/services/worker/.env expect denied  got denied  ok
cloudflared  read <repo>/deploy/.env    expect denied  got denied  ok
cloudflared  list ~                                           expect denied  got denied  ok
cloudflared  spawn /bin/ls from /bin/sh                                 expect denied  got denied  ok
cloudflared  connect 127.0.0.1:8710                                     expect allowed got allowed ok
cloudflared  connect 127.0.0.1:8719                                     expect denied  got denied  ok
cloudflared  connect 127.0.0.1:5432                                     expect denied  got denied  ok
cloudflared  connect 127.0.0.1:8080                                     expect denied  got denied  ok
cloudflared  connect 192.168.1.1:80                                     expect denied  got denied  ok
== worker.sb
worker       read ml/configs/models.yaml                                expect allowed got allowed ok
worker       read the Gemma model config                                expect allowed got allowed ok
worker       read ~/.ssh/known_hosts                          expect denied  got denied  ok
worker       read ~/.ssh/config                               expect denied  got denied  ok
worker       read ~/.config/gh/hosts.yml                      expect denied  got denied  ok
worker       read ~/.cache/huggingface/token                  expect denied  got denied  ok
worker       read ~/Library/Keychains/login.keychain-db       expect denied  got denied  ok
worker       read <repo>/services/gateway/.env expect denied  got denied  ok
worker       read <repo>/services/worker/.env expect denied  got denied  ok
worker       read <repo>/deploy/.env    expect denied  got denied  ok
worker       list ~                                           expect denied  got denied  ok
worker       spawn /bin/ls                                              expect denied  got denied  ok
worker       fork                                                       expect denied  got denied  ok
worker       connect 127.0.0.1:5432                                     expect denied  got denied  ok
worker       connect 127.0.0.1:8080                                     expect denied  got denied  ok
worker       connect 127.0.0.1:8710                                     expect denied  got denied  ok
worker       connect 1.1.1.1:443                                        expect denied  got denied  ok
worker       bind 0.0.0.0:9999                                          expect denied  got denied  ok
worker       write <repo>/services/worker/src expect denied  got denied  ok

sandbox proof: all probes as expected
```

The gateway may connect to any address on port 443 (Seatbelt filters ports, not CIDRs); the Go egress client is the layer that refuses private, loopback and link-local addresses after DNS resolution (ADR 0008 layer 3).

## 2. Adversarial checks through the tunnel (`deploy/security/adversarial.sh`)

| # | Check | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | GET /internal/v1/tools | 404 | 404 | pass |
| 1 | GET /internal/v1/system-prompt | 404 | 404 | pass |
| 1 | GET /metrics | 404 | 404 | pass |
| 1 | GET /api/v1/worker/connect | 404 | 404 | pass |
| 1 | POST /internal/v1/tools/execute | 404 | 404 | pass |
| 1 | worker connect upgrade | 404 | 404 | pass |
| 2 | GET /api/v1/market/..%2F..%2Fetc%2Fpasswd/quote | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL%2F..%2F..%2Finternal/quote | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/http%3A%2F%2F127.0.0.1%3A8719/quote | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL%00/quote | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/aapl;ls/quote | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL/history?range=../../etc/passwd | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL/history?range=http://169.254.169.254/ | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL/indicators?range=1Y%0d%0aX-Injected:1 | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/AAPL/fundamentals?period=annual&limit=999999 | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /api/v1/market/search?q=..%2F..%2F..%2Fetc%2Fpasswd | 400/404 (search may 200 with no matches), no leaks | 200 | pass |
| 2 | GET /api/v1/market/search?q=%27%20OR%201%3D1-- | 400/404 (search may 200 with no matches), no leaks | 200 | pass |
| 2 | GET /api/v1/market/search?q=AAPL&limit=100000 | 400/404 (search may 200 with no matches), no leaks | 400 | pass |
| 2 | GET /../../../../etc/passwd | 400/404 (search may 200 with no matches), no leaks | 404 | pass |
| 2 | GET /api/v1/../../internal/v1/tools | 400/404 (search may 200 with no matches), no leaks | 404 | pass |
| 3 | POST /chat/stream 100 kB | 413 | 413 | pass |
| 3 | POST /feedback 100 kB | 413 | 413 | pass |
| 3 | 40 kB request header (gateway, loopback) | 431 | 431 | pass |
| 3 | 40 kB request header (through the edge) | dropped by the edge or 431 | 200 | pass |
| 3 | truncated JSON body | 400 | 400 | pass |
| 3 | WS 200 kB frame | close 1009 | close 1009 | pass |
| 3 | WS first frame not start | close 1008 | close 1008 | pass |
| 3 | WS binary first frame | close 1008 | close 1008 | pass |
| 4 | CORS preflight Origin: https://evil.example | 403, no ACAO | 403 | pass |
| 4 | WS upgrade Origin: https://evil.example | http 403 | http 403 | pass |
| 4 | CORS preflight Origin: https://candela-terminal.netlify.app.evil.example | 403, no ACAO | 403 | pass |
| 4 | WS upgrade Origin: https://candela-terminal.netlify.app.evil.example | http 403 | http 403 | pass |
| 4 | CORS preflight Origin: http://candela-terminal.netlify.app | 403, no ACAO | 403 | pass |
| 4 | WS upgrade Origin: http://candela-terminal.netlify.app | http 403 | http 403 | pass |
| 4 | CORS preflight Origin: HTTPS://CANDELA-TERMINAL.NETLIFY.APP | 403, no ACAO | 403 | pass |
| 4 | WS upgrade Origin: HTTPS://CANDELA-TERMINAL.NETLIFY.APP | http 403 | http 403 | pass |
| 4 | CORS preflight Origin: null | 403, no ACAO | 403 | pass |
| 4 | WS upgrade Origin: null | http 403 | http 403 | pass |
| 4 | WS upgrade without Origin | http 403 | http 403 | pass |
| 4 | WS upgrade without subprotocol | http 400 | http 400 | pass |
| 4 | GET /status from evil origin | no ACAO header | 200, ACAO 0 | pass |
| 4 | GET /status from the site origin | ACAO = site | 200 | pass |
| 5 | /status has no paths, hostnames or LAN addresses | clean | 200 | pass |
| 5 | PUT /api/v1/status | 405 (or edge 405/501) | 405 | pass |
| 5 | DELETE /api/v1/status | 405 (or edge 405/501) | 405 | pass |
| 5 | TRACE /api/v1/status | 405 (or edge 405/501) | 405 | pass |
| 5 | PATCH /api/v1/status | 405 (or edge 405/501) | 405 | pass |
| 5 | X-Request-Id CRLF injection | header not reflected | 200 | pass |
| 5 | oversized X-Request-Id | replaced by a fresh id | 200 | pass |
| 6 | forged CF-Connecting-IP | rejected by Cloudflare (403, error 1000) | 403 error code: 1000 | pass |
| 6 | 30 quotes with forged X-Forwarded-For/X-Real-IP/True-Client-IP | 429 after the burst of 20 | 8 × 429 | pass |
| 6 | 429 carries Retry-After and RateLimit-* | yes | 429 | pass |
| 7 | client message with "role":"system" | 400 | 400 | pass |
| 7 | client message with "role":"tool" | 400 | 400 | pass |
| 8 | prompt injection: unknown tools, URL as symbol | no unknown tool executes, no file or metrics content | 1×done 1×meta 38×token 1×usage ; results: none | pass |

Notes:
- Chat requests (POST and WebSocket upgrades) share one bucket per client (6/min, burst 3); the script paces them 10 s apart so each check reaches the handler. A first run without pacing showed every WebSocket check answered `429`, which is the limiter working but masked the origin checks.
- Cloudflare's edge rejects any request carrying a client-supplied `CF-Connecting-IP` with `403 error code: 1000`, so the header the gateway trusts (`CANDELA_TRUSTED_PROXY=cloudflare`, peer must be loopback) cannot be forged through the tunnel. Forged `X-Forwarded-For`, `X-Real-IP` and `True-Client-IP` are ignored: the burst still hit `429`.
- A 40 kB header reaches the gateway only through loopback, where it is refused with `431`; through the tunnel the edge drops the oversized header and the request arrives without it (the gateway logged a normal `/healthz`).
- The dev model ignored the injection prompt and called no tool. The gateway side was checked directly on the internal tool API, the same code path the chat loop uses: `read_file` → `invalid_arguments: unknown tool "read_file"`; `get_quote` with `http://169.254.169.254/latest` or `../../etc` → `symbol … does not match ^[A-Z][A-Z0-9.\-]{0,9}$`; `get_price_history` with `range=file:///etc/passwd` → `range must be one of 1M, 3M, 6M, 1Y, 2Y, 5Y`.
- Sandboxed inference works end to end (dev model, SSE): `meta → tool_call (get_quote) → tool_result → 120 token + 12 telemetry → usage → done`, 97 tokens/s, TTFT 0.99 s.

## 3. Kill switch

Run with test thresholds (`CANDELA_EDGE_KILL_ORIGIN=10`, window 1 m, cooldown 1 m, max trips 2):

| Step | Observed |
|---|---|
| 20 CORS preflights from `https://evil.example` | all `403`; `candela_abuse_total{kind="origin"} 20` |
| next scrape (≤ 15 s) | state `cooldown`, reason `origin: 20 in 1m0s`, cloudflared stopped; old hostname answers Cloudflare `530` |
| after 1 min | new tunnel, new hostname, state `online` |
| second burst | state `halted`: "kill switch tripped 2 times in 6h … restart with make live-down && make live-up"; tunnel stays closed, gateway and worker keep running locally |

With publishing enabled, every transition to `cooldown`, `halted` or `offline` publishes the `offline` document before the tunnel closes (`edge.ended`). The first run exposed a bug, now fixed: the baseline sample was taken only at the first scrape, after the burst. The baseline is now scraped the moment the tunnel goes online.

## 4. Listeners (`lsof`)

```
gateway   TCP 127.0.0.1:8710 (LISTEN)
gateway   TCP 127.0.0.1:8719 (LISTEN)
cloudflar TCP 127.0.0.1:8717 (LISTEN)
```

No other listening TCP sockets and no UDP sockets for the supervisor, gateway, worker or `cloudflared`. `cloudflared` runs with `--protocol http2`: the QUIC transport binds UDP on all interfaces, which the profile denies. Established connections: worker → 127.0.0.1:8719, cloudflared → 127.0.0.1:8710 and Cloudflare :7844, supervisor → 127.0.0.1:8719 (metrics) and :443 (tunnel probes).

## 5. Security review

The `security-review` skill was run over `git diff a2bcff5..HEAD`: `services/gateway` (including `cmd/edge` and `/api/v1/lab/spark`), `deploy/` and `make/deploy.mk`. The phase made no worker code changes, so the worker was reviewed through its sandbox profile and launch environment. Result: no HIGH or MEDIUM findings. It reported one LOW item, fixed in `ed6a37e`: a Spark pause reason could pass a process name in parentheses through to visitors. Pause reasons are now always cut before `(` and `:`.

Reviewed and judged sound:
- Children start with a minimal, explicit environment, so `GH_TOKEN`, `HF_TOKEN` and the shell's variables are not inherited.
- `gh` runs as a fixed binary with an argument vector, a minimal environment and no shell.
- The tunnel hostname is validated against `^[a-z0-9-]+\.trycloudflare\.com$` before it is used or published.
- The metrics bearer token is sent only to 127.0.0.1:8719.
- `deploy/.env` must be 0600, its keys are validated, and it never overrides the environment.
- The edge refuses to open a tunnel when the sandboxes are disabled.
