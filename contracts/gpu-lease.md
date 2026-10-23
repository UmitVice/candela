# GPU lease protocol — `candela.gpu-lease.v1`

Several Candela processes share one Apple Silicon GPU and 24 GB of unified memory with the owner's own work: live inference (`services/worker`), Lab training and evaluation (`ml/`), and Candela Spark's continuous pretraining (`spark/`). They coordinate cooperatively through lease files; the memory resource guard still applies on top.

## Files

- Directory `~/.candela/leases/` (created with mode 0700). One JSON file per holder: `<holder>.json`, written atomically (temp file + rename).

```json
{ "protocol": "candela.gpu-lease.v1", "holder": "spark-trainer", "pid": 12345, "priority": 20,
  "purpose": "spark pretraining step loop", "startedAt": "2026-10-23T12:00:00Z", "heartbeatAt": "2026-10-23T12:00:10Z" }
```

## Priorities

| Priority | Holder | Typical duration |
|---|---|---|
| 100 | `worker` (live inference job) | seconds to a minute per chat job |
| 80 | `lab-train` (Candela Pro fine-tuning) | hours, pausable at step boundaries |
| 60 | `lab-eval`, `lab-export` | minutes to an hour |
| 20 | `spark-trainer` (continuous pretraining) | indefinite, pausable at step boundaries |

## Rules

1. A lease is **live** if `heartbeatAt` is less than 30 s old and `pid` exists. Holders refresh the heartbeat every 10 s and delete their file on exit (including SIGTERM/SIGINT).
2. Before each unit of GPU work (an optimizer step, a generation job, an eval batch), a process checks for live leases with **higher** priority. If one exists, it waits at the boundary (sleep 2–5 s and re-check) and records a pause reason; if the wait exceeds 10 minutes, long-running trainers checkpoint and release cached GPU memory (`mx.clear_cache()`), then keep waiting.
3. Equal priorities do not preempt each other; at most one holder per priority level should exist.
4. The worker writes its lease only while a job runs, so idle periods give lower priorities the GPU back immediately.
5. Stale lease files (dead pid or heartbeat older than 30 s) are ignored and may be deleted by anyone.
6. Leases never override the memory resource guard or the owner's processes: anything outside Candela always wins. In particular, no Candela training or GPU-heavy evaluation runs while a foreign training process is alive (command lines such as `train_mlx`, `mlx_lm.lora`, `mlx_lm_lora`); trainers check this at start and at every pause check.
