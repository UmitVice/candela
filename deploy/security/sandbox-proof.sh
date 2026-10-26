#!/usr/bin/env bash
# Proves the Seatbelt profiles in deploy/sandbox deny what ADR 0008 says they deny. Each probe
# runs a small program under the real profile (the binary parameter points at the probe tool,
# the file and network rules are unchanged) and expects "Operation not permitted". File contents
# are never printed. Exit status 1 when any probe disagrees with its expectation.
set -uo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd -P)
home=$(cd ~ && pwd -P)
sb="$repo/deploy/sandbox"
venv_python="$repo/services/worker/.venv/bin/python"
python=$(realpath "$venv_python")
python_app="$(dirname "$(dirname "$python")")/Resources/Python.app/Contents/MacOS/Python"
[ -x "$python_app" ] || python_app=$python
python_home=$(dirname "$(dirname "$python")")
case "$python_home" in */Frameworks/*) python_home=${python_home%%/Frameworks/*} ;; esac
user_cache="$(realpath "$(getconf DARWIN_USER_CACHE_DIR)")/"
fails=0

secrets=()
for f in "$home/.ssh/known_hosts" "$home/.ssh/config" "$home/.config/gh/hosts.yml" \
  "$home/.cache/huggingface/token" "$home/Library/Keychains/login.keychain-db" \
  "$repo/services/gateway/.env" "$repo/services/worker/.env" "$repo/deploy/.env"; do
  [ -e "$f" ] && secrets+=("$f")
done
secret_dirs=("$home/.ssh" "$home/.config/gh" "$home/Library/Keychains")

report() { # profile probe expected actual
  local mark=ok
  [ "$3" = "$4" ] || { mark=FAIL; fails=$((fails + 1)); }
  printf '%-12s %-58s expect %-7s got %-7s %s\n' "$1" "${2/#$home/~}" "$3" "$4" "$mark"
}

classify() { # stderr text and exit status -> allowed|denied|error
  if grep -qiE 'operation not permitted|permission denied|PermissionError' <<<"$1"; then echo denied
  elif [ "$2" -eq 0 ]; then echo allowed
  else echo error; fi
}

gateway() { # bin args...
  local bin=$1; shift
  sandbox-exec -f "$sb/gateway.sb" -D BIN="$bin" -D HOME="$home" \
    -D SNAPSHOT="$repo/services/gateway/data/market.sqlite" -D STATE_DIR="$repo/services/gateway/data/live" \
    -D SPARK_STATUS="$home/.candela/spark/status.json" "$bin" "$@"
}

cloudflared() {
  local bin=$1; shift
  sandbox-exec -f "$sb/cloudflared.sb" -D BIN="$bin" -D HOME="$home" "$bin" "$@"
}

worker_py() { # python code
  sandbox-exec -f "$sb/worker.sb" -D PYTHON="$python" -D PYTHON_APP="$python_app" -D PYTHON_HOME="$python_home" \
    -D VENV="$repo/services/worker/.venv" -D WORKER_DIR="$repo/services/worker" -D MODELS_CONFIG="$repo/ml/configs/models.yaml" \
    -D LEASE_DIR="$home/.candela/leases" -D TMP_DIR="$home/.candela/edge/tmp/worker" -D USER_CACHE="$user_cache" -D HOME="$home" \
    -D READ_0="$home/models/gemma-4-12b-it-qat-mlx-q4" -D READ_1=/nonexistent -D READ_2=/nonexistent -D READ_3=/nonexistent \
    -D READ_4=/nonexistent -D READ_5=/nonexistent "$venv_python" -I -c "$1"
}

probe_cat() { # profile-fn profile-name file expected
  local err rc
  err=$("$1" /bin/cat "$3" 2>&1 >/dev/null); rc=$?
  report "$2" "read $3" "$4" "$(classify "$err" $rc)"
}

probe_ls() {
  local err rc
  err=$("$1" /bin/ls "$3" 2>&1 >/dev/null); rc=$?
  report "$2" "list $3" "$4" "$(classify "$err" $rc)"
}

probe_tcp() { # profile-fn profile-name host port expected
  local err rc
  err=$("$1" /usr/bin/nc -zv -G 3 "$3" "$4" 2>&1); rc=$?
  report "$2" "connect $3:$4" "$5" "$(classify "$err" $rc)"
}

probe_exec() {
  local err rc
  err=$("$1" /bin/sh -c '/bin/ls / >/dev/null' 2>&1); rc=$?
  report "$2" "spawn /bin/ls from /bin/sh" denied "$(classify "$err" $rc)"
}

echo "== gateway.sb"
probe_cat gateway gateway "$repo/services/gateway/data/market.sqlite" allowed
for f in "${secrets[@]}"; do probe_cat gateway gateway "$f" denied; done
for d in "${secret_dirs[@]}"; do [ -e "$d" ] && probe_ls gateway gateway "$d" denied; done
probe_ls gateway gateway "$home" denied
probe_exec gateway gateway
probe_tcp gateway gateway www.nasdaqtrader.com 443 allowed
for target in "127.0.0.1 5432" "127.0.0.1 8080" "127.0.0.1 8719" "127.0.0.1 8712" "192.168.1.1 80" "1.1.1.1 80"; do
  read -r host port <<<"$target"
  probe_tcp gateway gateway "$host" "$port" denied
done

echo "== cloudflared.sb"
for f in "${secrets[@]}"; do probe_cat cloudflared cloudflared "$f" denied; done
probe_ls cloudflared cloudflared "$home" denied
probe_exec cloudflared cloudflared
probe_tcp cloudflared cloudflared 127.0.0.1 8710 allowed
for target in "127.0.0.1 8719" "127.0.0.1 5432" "127.0.0.1 8080" "192.168.1.1 80"; do
  read -r host port <<<"$target"
  probe_tcp cloudflared cloudflared "$host" "$port" denied
done

echo "== worker.sb"
py_probe() { # description expected python
  local err rc
  err=$(worker_py "$3" 2>&1 >/dev/null); rc=$?
  report worker "$1" "$2" "$(classify "$err" $rc)"
}
py_probe "read ml/configs/models.yaml" allowed "open('$repo/ml/configs/models.yaml').read(1)"
py_probe "read the Gemma model config" allowed "open('$home/models/gemma-4-12b-it-qat-mlx-q4/config.json').read(1)"
for f in "${secrets[@]}"; do py_probe "read $f" denied "open('$f','rb').read(1)"; done
py_probe "list $home" denied "import os; os.listdir('$home')"
py_probe "spawn /bin/ls" denied "import subprocess; subprocess.run(['/bin/ls'])"
py_probe "fork" denied "import os; os.fork()"
for port in 5432 8080 8710; do
  py_probe "connect 127.0.0.1:$port" denied "import socket; socket.create_connection(('127.0.0.1',$port),2)"
done
py_probe "connect 1.1.1.1:443" denied "import socket; socket.create_connection(('1.1.1.1',443),2)"
py_probe "bind 0.0.0.0:9999" denied "import socket; s=socket.socket(); s.bind(('0.0.0.0',9999)); s.listen()"
py_probe "write $repo/services/worker/src" denied "open('$repo/services/worker/src/x.tmp','w')"

echo
if [ "$fails" -eq 0 ]; then echo "sandbox proof: all probes as expected"; else echo "sandbox proof: $fails probe(s) FAILED"; exit 1; fi
