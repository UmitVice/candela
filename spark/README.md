# Candela Spark

A decoder-only language-model family built from scratch in pure MLX. It is trained quantization-aware, so int4 is its native format, and it trains continuously in the background on a shared Apple Silicon laptop.

- Architecture and training spec: [ADR 0600](../docs/adr/0600-spark-architecture-and-training-spec.md)
- QAT recipe and int4 export: [ADR 0601](../docs/adr/0601-spark-qat-and-int4-export.md)
- GPU coordination: [`contracts/gpu-lease.md`](../contracts/gpu-lease.md)

## Layout

| Path | Purpose |
|---|---|
| `configs/data/v0.yaml` | pinned pretraining sources (commit revisions, licenses, files, mixture) |
| `configs/data/eval.yaml` | pinned zero-shot evaluation sets |
| `configs/train/` | run configs: continuous main run, milestone decay branches, LR probes |
| `tokenizer/spark-bpe-32k.json` | frozen byte-level BPE shared by every size (hash in `spark-bpe-32k.meta.json`) |
| `src/candela_spark/model` | presets, QAT linear layers, transformer, int4 inference model, generation |
| `src/candela_spark/train` | Muon/AdamW, WSD schedule, atomic checkpoints, the trainer loop |
| `src/candela_spark/data` | fetch (SHA-256 verified), cleaning, MinHash dedup, tokenization, mixture loader |
| `src/candela_spark/ops` | memory guard, foreign-training check, GPU lease, status file, LaunchAgent |
| `src/candela_spark/export` | MLX int4/bf16, GGUF Q4_1, Observatory artifacts, Hugging Face publishing |
| `reports/` | evaluation reports (JSON and Markdown) |

`data/`, `runs/` and `artifacts/` are git-ignored: downloads, tokenized shards, checkpoints, metrics and exported weights live there.

## Usage

```bash
make spark-sync
```

```bash
make spark-data
```

```bash
make spark-train
```

```bash
make spark-status
```

The trainer never touches the network: it runs under a Seatbelt profile that denies all network access. Before every optimizer step it checks, in order:

- override pause and battery power
- thermal pressure
- foreign training processes
- higher-priority GPU leases
- the memory guard

If any check fails, it waits at the step boundary. Checkpoints are written every 10 minutes, on SIGTERM/SIGINT and on long pauses.

Continuous operation goes through the LaunchAgent `com.candela.spark-trainer`. Logs go to `~/Library/Logs/Candela/`, and the sanitised status is written to `~/.candela/spark/status.json`.

```bash
make spark-daemon-install
```

To pause the daemon by hand, or to simulate battery power, write `~/.candela/spark/override.json` with `{"pause": true}` or `{"simulateBattery": true}`.
