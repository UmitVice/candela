# p2-worker — status

STATUS: partial — Gemma 4 12B verification queued in the background (waiting for ≥ 9 GB available memory)

Summary:
`services/worker` (`candela-worker`, Python 3.14, mlx 0.32.4, mlx-lm 0.32.2) is implemented and verified end to end with the pinned dev model `mlx-community/Qwen3-0.6B-4bit`:
- worker protocol client, admission control with GPU lease reservation, lazy load and idle unload;
- own decode loop with reasoning split, tool-call parsing, prompt KV reuse and cancellation;
- per-token telemetry and the OpenAI-compatible development API;
- bench and doctor commands, `make/worker.mk`, `deploy/worker/`, ADR 0300.

The Gemma 4 12B QAT run (pilot adapter, then the v0.1 interim adapter) starts automatically when memory allows (`/tmp/gemma-verify.sh`, results in `services/worker/runs/gemma-verify/`). The final report replaces this file.

Commits so far: cb35087, 8703f66, 14691c3, 9634a66, 4682fc5.
