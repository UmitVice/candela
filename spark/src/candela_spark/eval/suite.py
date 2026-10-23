import ast
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from candela_spark import log, paths
from candela_spark.data import config as data_config
from candela_spark.data.loader import validation_windows
from candela_spark.eval import data as eval_data
from candela_spark.eval.prompts import FINANCE_CLOZE, SAMPLE_PROMPTS
from candela_spark.eval.scoring import Scorer
from candela_spark.model.generate import generate, load_from_checkpoint
from candela_spark.model.transformer import SparkLM
from candela_spark.ops.gpu import gpu_job
from candela_spark.tokenizer.train import load as load_tokenizer
from candela_spark.train import checkpoint
from candela_spark.train.trainer import evaluate

_log = log.get("eval")
CHANCE = {
    "arc-easy": 0.25,
    "hellaswag": 0.25,
    "piqa": 0.5,
    "blimp": 0.5,
    "finance-cloze": 0.25,
    "lambada": 0.0,
}


def _subset(rows: list[dict[str, Any]], n: int, seed: int = 7) -> list[dict[str, Any]]:
    if len(rows) <= n:
        return rows
    idx = np.random.default_rng(seed).choice(len(rows), size=n, replace=False)
    return [rows[i] for i in sorted(idx)]


def _parse(value: Any) -> Any:
    return ast.literal_eval(value) if isinstance(value, str) else value


def zero_shot(model: SparkLM, n: int) -> list[dict[str, Any]]:
    tok = load_tokenizer()
    sc = Scorer(model, tok)
    out: list[dict[str, Any]] = []

    rows = _subset(eval_data.rows("lambada"), n)
    hits, nll, cnt = 0, 0.0, 0
    for r in rows:
        ctx, _, last = r["text"].rpartition(" ")
        lp, greedy, k = sc.continuation(ctx, " " + last)
        hits += greedy
        nll -= lp
        cnt += k
    out.append(
        {
            "id": "lambada",
            "metric": "acc",
            "n": len(rows),
            "value": hits / len(rows),
            "extra": {"targetPerplexity": math.exp(nll / max(1, cnt))},
        }
    )

    rows = _subset(eval_data.rows("arc-easy"), n)
    ok = 0
    for r in rows:
        ch = _parse(r["choices"])
        pred = sc.choice(f"Question: {r['question']}\nAnswer:", [" " + t for t in ch["text"]], normalize=True)
        ok += ch["label"][pred] == r["answerKey"]
    out.append({"id": "arc-easy", "metric": "acc_norm", "n": len(rows), "value": ok / len(rows)})

    rows = _subset(eval_data.rows("hellaswag"), n)
    ok = 0
    for r in rows:
        ctx = f"{r['activity_label']}: {r['ctx_a']} {r['ctx_b'].capitalize()}".strip()
        endings = [" " + e for e in _parse(r["endings"])]
        ok += sc.choice(ctx, endings, normalize=True) == int(r["label"])
    out.append({"id": "hellaswag", "metric": "acc_norm", "n": len(rows), "value": ok / len(rows)})

    rows = _subset(eval_data.rows("piqa"), n)
    ok = 0
    for r in rows:
        pred = sc.choice(
            f"Question: {r['goal']}\nAnswer:", [" " + r["sol1"], " " + r["sol2"]], normalize=True
        )
        ok += pred == int(r["label"])
    out.append({"id": "piqa", "metric": "acc_norm", "n": len(rows), "value": ok / len(rows)})

    rows = _subset(eval_data.rows("blimp"), n * 2)
    ok = 0
    for r in rows:
        good, _, _ = sc.continuation("", r["sentence_good"])
        bad, _, _ = sc.continuation("", r["sentence_bad"])
        ok += good > bad
    out.append({"id": "blimp", "metric": "acc", "n": len(rows), "value": ok / len(rows)})

    ok = 0
    for ctx, right, wrong in FINANCE_CLOZE:
        ok += sc.choice(ctx, [right, *wrong], normalize=False) == 0
    out.append(
        {"id": "finance-cloze", "metric": "acc", "n": len(FINANCE_CLOZE), "value": ok / len(FINANCE_CLOZE)}
    )
    for s in out:
        s["chance"] = CHANCE[s["id"]]
        s["value"] = round(s["value"], 4)
    return out


def run(run_id: str, label: str | None, n: int, export_dir: Path | None) -> dict[str, Any]:
    ckpt = checkpoint.latest_valid(paths.RUNS / run_id / "checkpoints")
    if ckpt is None:
        raise RuntimeError(f"no valid checkpoint for {run_id}")
    label = label or run_id
    with gpu_job("spark-eval", 60, f"spark eval {label}"):
        t0 = time.time()
        model = load_from_checkpoint(ckpt)
        state = json.loads((ckpt / "state.json").read_text())
        dcfg = data_config.load(state["dataVersion"])
        windows = validation_windows(dcfg, int(state["runConfig"]["seq_len"]), 64)
        ppl = evaluate(model, windows, 2)
        exported = None
        if export_dir is not None:
            from candela_spark.model.quantized import load_int4

            qmodel = load_int4(export_dir)
            exported = evaluate(qmodel, windows, 2)["int4"]
        model.set_qat(True)
        suites = zero_shot(model, n)
        samples = [{"prompt": p, "completion": generate(model, p, 60, 0.7, seed=0)} for p in SAMPLE_PROMPTS]
    per_source = {
        s: {
            "bf16": round(ppl["bf16"][s], 4),
            "int4": round(ppl["int4"][s], 4),
            "int4Export": round(exported[s], 4) if exported else None,
            "pplBf16": round(math.exp(ppl["bf16"][s]), 2),
            "pplInt4": round(math.exp(ppl["int4"][s]), 2),
        }
        for s in ppl["bf16"]
    }
    bf = float(np.mean([v["bf16"] for v in per_source.values()]))
    q4 = float(np.mean([v["int4"] for v in per_source.values()]))
    report = {
        "label": label,
        "run": run_id,
        "checkpoint": ckpt.name,
        "step": state["step"],
        "tokens": state["tokens"],
        "evaluatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "validation": {
            "perSource": per_source,
            "meanBf16": round(bf, 4),
            "meanInt4": round(q4, 4),
            "gapRel": round((q4 - bf) / bf, 5),
            "windowsPerSource": 64,
            "seqLen": 1024,
        },
        "zeroShot": suites,
        "samples": samples,
        "sec": round(time.time() - t0, 1),
    }
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    (paths.REPORTS / f"{label}.json").write_text(json.dumps(report, indent=2) + "\n")
    (paths.REPORTS / f"{label}.md").write_text(render_md(report))
    return {k: report[k] for k in ("label", "step", "tokens", "validation", "zeroShot")}


def render_md(r: dict[str, Any]) -> str:
    v = r["validation"]
    lines = [
        f"# Evaluation — {r['label']}",
        "",
        f"Checkpoint `{r['checkpoint']}` of run `{r['run']}`: step {r['step']:,}, {r['tokens']:,} tokens. "
        f"Evaluated {r['evaluatedAt']}.",
        "",
        "## Validation loss per source (nats/token, 64 × 1024-token windows)",
        "",
        "| Source | bf16 | int4 (QAT forward) | int4 export | ppl bf16 | ppl int4 |",
        "|---|---|---|---|---|---|",
    ]
    for s, x in v["perSource"].items():
        ex = f"{x['int4Export']:.4f}" if x["int4Export"] is not None else "—"
        lines.append(f"| {s} | {x['bf16']:.4f} | {x['int4']:.4f} | {ex} | {x['pplBf16']} | {x['pplInt4']} |")
    lines += [
        "",
        f"Mean bf16 {v['meanBf16']:.4f}, mean int4 {v['meanInt4']:.4f}, relative int4 gap "
        f"{100 * v['gapRel']:+.3f} %.",
        "",
        "## Zero-shot suite",
        "",
        "| Suite | Metric | n | Score | Chance |",
        "|---|---|---|---|---|",
    ]
    for s in r["zeroShot"]:
        lines.append(f"| {s['id']} | {s['metric']} | {s['n']} | {s['value']:.3f} | {s['chance']:.2f} |")
    lines += ["", "## Fixed-seed samples (int4, temperature 0.7, seed 0)", ""]
    for s in r["samples"]:
        lines += [f"**{s['prompt']}**{s['completion']}", ""]
    return "\n".join(lines) + "\n"
