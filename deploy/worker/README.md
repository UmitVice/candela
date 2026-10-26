# Candela worker on the Mac

The worker turns the Mac into Candela's GPU node. It dials **out** to the gateway (`candela.worker.v1`, see `contracts/worker-protocol.md`), so in `connect` mode it opens no listening socket. The model loads on the first job and unloads after `CANDELA_WORKER_IDLE_UNLOAD_SEC` (default 900 s) without jobs.

## Run it by hand

```bash
make worker-sync
cp services/worker/.env.example services/worker/.env
```

Set `CANDELA_WORKER_TOKEN` in `services/worker/.env` to the gateway's `CANDELA_WORKER_TOKEN` (`services/gateway/bin/workerctl token -env services/gateway/.env` creates one). Then start the gateway (`make gateway-run`) and the worker:

```bash
make worker-connect
```

`GET /api/v1/status` now lists the worker, and `route` is `worker`. Stop it with Ctrl-C or SIGTERM: the worker reports `draining`, finishes the running job (up to 150 s), releases its GPU lease and unloads the model. A second signal cancels the job.

Useful checks:

- `make worker-doctor`: versions, Metal device, memory headroom, live GPU leases, model and adapter paths, and whether a job would be admitted right now.
- `make worker-bench WORKER_BENCH_ARGS="--model candela-pro-v0.1 --kv-tokens 4000"`: TTFT, prefill and decode tokens/s, peak memory, telemetry overhead and the 8-bit KV comparison.
- `make worker-serve`: OpenAI-compatible API on `127.0.0.1:8711` for local work. Development only; it refuses to start with `CANDELA_ENV=production`.

## Resource behaviour

- **Admission**: before a job runs, the worker writes `~/.candela/leases/worker.json` (priority 100) as `waiting`. Lower-priority trainers then checkpoint and release the GPU. The job starts once available memory (free + inactive + purgeable + speculative pages) covers the model's inference budget plus `CANDELA_WORKER_RESERVE_GB` and memory pressure is not critical. If that does not happen within `CANDELA_WORKER_ADMISSION_WAIT_SEC` (default 30 s), the job is declined with `overloaded`. The gateway then answers from its fallback, if there is one, or reports `overloaded` and the web app offers replay.
- **Lease**: the lease file exists only while a job waits or runs and is deleted right after, so trainers get the GPU back immediately.
- **Memory limits**: MLX's memory limit is set to the model's inference budget (8 GB for Candela Pro), its buffer cache to `CANDELA_WORKER_MLX_CACHE_MB` (512 MB). Prompt KV caches for tool rounds are kept in a bounded LRU (4 entries, 1 GB).

## Login agent (optional)

`com.candela.worker.plist.template` runs `candela-worker connect` at login, restarts it after a crash (not after a clean stop), and logs to `~/Library/Logs/candela-worker.log`. It is not installed by any make target. To install it yourself:

```bash
sed -e "s#__REPO__#$PWD#g" -e "s#__HOME__#$HOME#g" deploy/worker/com.candela.worker.plist.template > ~/Library/LaunchAgents/com.candela.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.candela.worker.plist
```

Remove it with `launchctl bootout gui/$(id -u)/com.candela.worker` and delete the plist. The production sandbox (Seatbelt profile, ADR 0008) is added in `p3-deploy`. The worker needs read access only to its Python environment (`services/worker/.venv` and the Python installation it links to), the repository's `services/worker/served-models.yaml` and `ml/configs/models.yaml`, the model directory and the adapter directory; write access to `~/.candela/leases/`; and outbound connections to the gateway's internal port. It spawns no processes. It reads memory statistics and the chip name through `host_statistics64` and `sysctlbyname`, not by running `vm_stat` or `sysctl`.
