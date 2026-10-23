# Contracts

Shared, versioned interfaces between the components. Code follows these files; changes land in the same commit as the code that implements them.

| File | Producer | Consumers |
|---|---|---|
| `api.md` | `services/gateway` | `apps/web`, `services/worker` |
| `worker-protocol.md` | `services/gateway` | `services/worker` |
| `tools.json` | gateway (execution) | worker (prompting), `ml/` (training data), gateway |
| `tools.md` | gateway | `ml/` (training data must match model views), `apps/web` (UI views) |
| `system-prompt.md` | gateway | `ml/` (training data) |
| `observatory.md` | `ml/` | `apps/web` |
| `gpu-lease.md` | every GPU job | `services/worker`, `ml/`, `spark/` |
