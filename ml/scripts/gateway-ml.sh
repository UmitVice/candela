#!/usr/bin/env bash
# Candela Lab's own gateway instance (ml port pair 8730/8739, own SQLite file, shared read-only snapshot) for
# generating tool-use traces through the real executor. Usage: gateway-ml.sh start | stop | status.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
state="$root/ml/runs/_gateway"
pidfile="$state/pid"
mkdir -p "$state"

case "${1:-status}" in
  start)
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      echo "gateway already running (pid $(cat "$pidfile"))"; exit 0
    fi
    (cd "$root/services/gateway" && GOMAXPROCS=4 CGO_ENABLED=0 go build -trimpath -o "$state/gateway" ./cmd/gateway)
    cd "$root"
    # Ephemeral tokens: the internal tool API needs none, but the gateway refuses to start without them.
    CANDELA_ADDR=127.0.0.1:8730 CANDELA_INTERNAL_ADDR=127.0.0.1:8739 \
      CANDELA_DB_PATH=services/gateway/data/ml.sqlite CANDELA_SNAPSHOT_PATH=services/gateway/data/market.sqlite \
      CANDELA_ENV=development CANDELA_FALLBACK_ENABLED=false CANDELA_DISABLE_SYMBOL_FETCH=true \
      CANDELA_WORKER_TOKEN="$(openssl rand -base64 32)" CANDELA_METRICS_TOKEN="$(openssl rand -base64 32)" \
      nohup "$state/gateway" >"$state/gateway.log" 2>&1 &
    echo $! >"$pidfile"
    for _ in $(seq 1 30); do
      curl -fsS -o /dev/null http://127.0.0.1:8730/healthz 2>/dev/null && { echo "gateway up (pid $(cat "$pidfile"))"; exit 0; }
      sleep 0.5
    done
    echo "gateway did not become healthy; see $state/gateway.log" >&2; exit 1
    ;;
  stop)
    if [[ -f "$pidfile" ]]; then kill "$(cat "$pidfile")" 2>/dev/null || true; rm -f "$pidfile"; echo "gateway stopped"; fi
    ;;
  status)
    [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null && echo "running (pid $(cat "$pidfile"))" || echo "stopped"
    ;;
esac
