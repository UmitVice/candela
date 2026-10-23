import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from huggingface_hub import HfApi

from candela_spark import paths
from candela_spark.data import config as data_config
from candela_spark.model.config import PRESETS, param_counts

_FORBIDDEN = [
    re.compile(p)
    for p in (
        r"/Users/",
        r"/home/",
        r"hf_[A-Za-z0-9]{20,}",
        r"~/",
        r"@[a-z0-9-]+\.(com|io)",
        r"BEGIN [A-Z ]*PRIVATE KEY",
    )
]


def card(name: str) -> str:
    report = json.loads((paths.REPORTS / f"{name}.json").read_text())
    export = json.loads((paths.ARTIFACTS / name / "export.json").read_text())
    dcfg = data_config.load("v0")
    stats = json.loads((paths.TOKENIZED / "v0" / "stats.json").read_text())
    evals = yaml.safe_load((paths.CONFIGS / "data" / "eval.yaml").read_text())["suites"]
    cfg = PRESETS["spark-35m"]
    counts = param_counts(cfg)
    v = report["validation"]
    licenses = sorted({"odc-by", "cc-by-sa-3.0", "apache-2.0"})
    src_rows = "\n".join(
        f"| `{s.repo}` ({s.id}) | `{s.revision[:12]}` | {s.license} | {', '.join(f'`{f}`' for f in s.files)} |"
        for s in dcfg.sources
    )
    mix_rows = "\n".join(
        f"| {k} | {x['trainTokens'] / 1e6:,.1f}M | {dcfg.mixture.get(k, 1.0)} |"
        for k, x in stats["sources"].items()
    )
    val_rows = "\n".join(
        f"| {k} | {x['bf16']:.4f} | {x['int4']:.4f} | {x['pplInt4']} |" for k, x in v["perSource"].items()
    )
    zs_rows = "\n".join(
        f"| {s['id']} | {s['metric']} | {s['n']} | {s['value']:.3f} | {s['chance']:.2f} |"
        for s in report["zeroShot"]
    )
    samples = "\n\n".join(f"> **{s['prompt']}**{s['completion']}" for s in report["samples"][:5])
    ev_rows = ", ".join(f"`{e['repo']}`@`{e['revision'][:12]}` ({e['license']})" for e in evals)
    return f"""---
license: apache-2.0
language: [en]
library_name: mlx
pipeline_tag: text-generation
tags: [mlx, from-scratch, quantization-aware-training, int4, qat, gguf, finance, candela]
datasets: [HuggingFaceFW/fineweb-edu, HuggingFaceTB/smollm-corpus, wikimedia/wikipedia, HuggingFaceTB/finemath,
  eloukas/edgar-corpus]
---

# Candela Spark 35M — milestone 1 (`{name}`)

A {counts["total"] / 1e6:.1f}M-parameter decoder trained **from scratch** in pure MLX on an Apple M5 Pro laptop,
**quantization-aware from the first step**: the int4 weights in this repo *are* the trained model, not a
post-training approximation. Part of [Candela](https://github.com/UmitVice/candela), an open financial-analysis
LLM project. This is an early base model (no instruction tuning); expect fluent-ish English with weak factual
recall.

## Files

| File | Format |
|---|---|
| `model.safetensors`, `config.json` | MLX affine int4, group 32, bf16 scales/biases — primary artifact |
| `{export["gguf"]["path"]}` | GGUF Q4_1 (llama.cpp, architecture `gemma3`) — bit-identical int4 grid |
| `bf16-reference/` | bf16 master weights, for reference only |
| `tokenizer.json` | frozen byte-level BPE, 32 768 tokens, single-digit splitting |
| `eval.json` | full evaluation report |

## Architecture

Gemma 3 block layout so llama.cpp runs it unchanged: pre- and post-norm RMSNorm around attention and FFN, QK-norm,
grouped-query attention ({cfg.num_heads} query / {cfg.num_kv_heads} KV heads, head dim {cfg.head_dim}), RoPE (base
10k local / 1M global), 5 sliding-window layers (window {cfg.sliding_window}) per global layer, GeGLU FFN, no biases,
tied embeddings scaled by √d. d = {cfg.hidden_size}, {cfg.num_layers} layers, FFN {cfg.intermediate_size},
context {cfg.max_seq_len}. Parameters: {counts["total"]:,} ({counts["embedding"]:,} in the tied embedding).

## Training recipe

- **QAT**: every matrix (all block linears and the tied embedding/head) is fake-quantized in the forward pass
  through `mx.quantize`/`mx.dequantize` (affine int4, group 32, bf16 scales), the exact grid MLX exports, with a
  straight-through estimator to fp32 master weights. Active from step 0.
- **Optimiser**: Muon (Nesterov 0.95, 5 Newton–Schulz steps, decoupled weight decay 0.01, spectral
  √(fan_out/fan_in) scaling) for hidden matrices; AdamW for the embedding and norms; μP-style output multiplier.
- **Schedule**: warmup–stable–decay; this release is a 1−√ decay branch forked from the continuous stable run at
  step {export["step"] - 800 if export["step"] > 800 else 0:,}.
- **Batch**: 32 768 tokens/step (2 × 1 024 × 16 accumulation), bf16 compute, fp32 master weights.
- Trained for {report["tokens"] / 1e6:,.0f}M tokens ({report["step"]:,} steps).

## Data (pinned, SHA-256 verified, permissive)

| Dataset | Revision | License | Files |
|---|---|---|---|
{src_rows}

Filters: length, English stop-word ratio, alphabetic ratio, word length, repeated lines; EDGAR keeps Items 1, 1A
and 7 with page furniture removed; finance/economics pages selected from FineWeb-Edu by a keyword-density rule and
upsampled ×3; exact and MinHash (112 permutations, 14 bands) dedup across all sources. Training mix after dedup:

| Source | Train tokens | Mixture multiplier |
|---|---|---|
{mix_rows}

Dataset licenses involved: {", ".join(licenses)}. Wikipedia text is CC-BY-SA-3.0; attribution to Wikipedia
contributors.

## Evaluation

Validation loss (nats/token) on held-out documents, bf16 master weights vs the int4 QAT forward pass:

| Source | bf16 | int4 | int4 perplexity |
|---|---|---|---|
{val_rows}

Mean bf16 {v["meanBf16"]:.4f}, mean int4 {v["meanInt4"]:.4f}: **relative int4 gap {100 * v["gapRel"]:+.3f} %**.
The exported int4 model reproduces the QAT forward pass (max relative loss difference
{export["check"]["maxRelLossDiff"]}).

Zero-shot (subsets, log-likelihood scoring):

| Suite | Metric | n | Score | Chance |
|---|---|---|---|---|
{zs_rows}

Evaluation sets: {ev_rows}. Web-crawl pretraining data may overlap some benchmark text.

Fixed-seed samples (int4, temperature 0.7):

{samples}

## Limitations

Tiny base model trained for well under a Chinchilla budget: it makes up facts and numbers, has no instruction
following, and must not be used for financial decisions. English only. Knowledge reflects the training snapshots
(web crawl to 2024, Wikipedia 2023-11, 10-K filings 2019–2020).

## License

Apache-2.0 for the weights and code.
"""


def _check(text: str) -> None:
    for pat in _FORBIDDEN:
        if pat.search(text):
            raise RuntimeError(f"refusing to publish: card matches {pat.pattern}")


def publish(name: str, repo: str, dry_run: bool) -> dict[str, Any]:
    root = paths.ARTIFACTS / name
    stage = root / "hf"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "bf16-reference").mkdir(parents=True)
    for f in ("model.safetensors", "config.json", "tokenizer.json"):
        shutil.copy(root / "mlx-int4" / f, stage / f)
        shutil.copy(root / "mlx-bf16" / f, stage / "bf16-reference" / f)
    for g in root.glob("*.gguf"):
        shutil.copy(g, stage / g.name)
    shutil.copy(paths.REPORTS / f"{name}.json", stage / "eval.json")
    text = card(name)
    _check(text)
    for f in (stage / "config.json", stage / "eval.json", stage / "bf16-reference" / "config.json"):
        _check(f.read_text())
    (stage / "README.md").write_text(text)
    files = sorted(str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file())
    if dry_run:
        return {"repo": repo, "files": files, "dryRun": True}
    api = HfApi()
    api.create_repo(repo, repo_type="model", exist_ok=True, private=False)
    commit = api.upload_folder(
        repo_id=repo, repo_type="model", folder_path=str(stage), commit_message=f"Release {name}"
    )
    return {"repo": repo, "files": files, "commit": commit.oid, "url": f"https://huggingface.co/{repo}"}


def stage_dir(name: str) -> Path:
    return paths.ARTIFACTS / name / "hf"
