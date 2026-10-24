import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from candela_lab import config, log
from candela_lab.data.card import environment
from candela_lab.data.common import read_jsonl
from candela_lab.eval import report
from candela_lab.paths import DATA_DIR, MANIFESTS_DIR, ML_DIR, ML_OBSERVATORY_DIR, RUNS_DIR, TRACES_DIR

_log = log.get("publish")
NAMESPACE = "UmitVice"
DATASET_REPO = f"{NAMESPACE}/candela-finance-traces"
HARDWARE = "Apple M5 Pro, 24 GB unified memory (shared with other work)"


def repo_ids(version: str) -> dict[str, str]:
    return {
        "adapter": f"{NAMESPACE}/candela-pro-12b-{version}-mlx-lora",
        "gguf": f"{NAMESPACE}/candela-pro-12b-{version}-gguf-lora",
        "dataset": DATASET_REPO,
    }


def _eval_rows(model_id: str) -> list[dict[str, Any]]:
    path = ML_OBSERVATORY_DIR / "models" / model_id / "eval.json"
    return json.loads(path.read_text())["suites"] if path.exists() else []


def _training_facts(run: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    started = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else None
    finished = datetime.fromisoformat(state["finished_at"]) if state.get("finished_at") else None
    wall_h = (finished - started).total_seconds() / 3600 if started and finished else None
    cfg = run["config"]
    opt = cfg.get("optimizer", {})
    return {
        "steps": state["step"],
        "epochs": round(
            state["step"] * int(cfg.get("gradAccumulation", 1)) / max(int(run["trainExamples"]), 1), 2
        ),
        "tokens": state["trained_tokens"],
        "compute_h": round(state["elapsed_sec"] / 3600, 1),
        "wall_h": round(wall_h, 1) if wall_h is not None else None,
        "tokens_per_sec": round(state["trained_tokens"] / max(state["elapsed_sec"], 1e-6)),
        "peak_mem_gb": round(state["peak_mem_gb"], 2),
        "pauses": len(state.get("pauses") or []),
        "lr": float(opt.get("learningRate", 1e-4)),
        "warmup": int(opt.get("warmup", 0)),
        "min_lr_ratio": float(opt.get("minLrRatio", 0.1)),
        "accum": int(cfg.get("gradAccumulation", 1)),
        "batch": int(cfg.get("batchSize", 1)),
        "max_seq": int(cfg.get("maxSeqLength", 2048)),
        "train_examples": int(run["trainExamples"]),
        "trainable": int(run["trainableParameters"]),
        "modules": run["modules"],
    }


def _gate(base_report: Path | None, tuned_report: Path | None) -> tuple[list[dict[str, Any]], bool | None]:
    if not base_report or not tuned_report:
        return [], None
    rows = report.gate(json.loads(base_report.read_text()), json.loads(tuned_report.read_text()))
    return rows, all(r["pass"] is not False for r in rows)


def plan(
    run_id: str,
    out: Path,
    base_report: Path | None = None,
    tuned_report: Path | None = None,
    experimental: bool = False,
) -> list[dict[str, Any]]:
    rd = RUNS_DIR / run_id
    run = json.loads((rd / "run.json").read_text())
    state = json.loads((rd / "state.json").read_text())
    cfg = run["config"]
    spec = config.model(cfg["model"])
    obs = cfg.get("observatory", {})
    model_id = obs.get("modelId", run_id)
    version = obs.get("version", "dev")
    ids = repo_ids(version)
    data_version = cfg.get("data", {}).get("version", "d0.2")
    manifest_path = MANIFESTS_DIR / f"{data_version}.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    gate_rows, gate_passed = _gate(base_report, tuned_report)
    env = environment()
    env.filters["num"] = lambda v, f="%.3f": "n/a" if v is None else f % v
    common = {
        "display_name": obs.get("displayName", "Candela Pro"),
        "version": version,
        "base_model": spec.upstream,
        "base_gguf": spec.raw.get("upstream", {}).get("qatGguf", ""),
        "run_id": run_id,
        "dataset_version": data_version,
        "buckets": manifest.get("buckets", {}),
        "licenses": manifest.get("licenses", {}),
        "lora": run["lora"],
        "layers": f"{run['layerIndices'][0]}–{run['layerIndices'][-1]}" if run["layerIndices"] else "none",
        "experimental": experimental or gate_passed is False,
        "dataset_repo": ids["dataset"],
        "repos": ids,
        "eval_rows": _eval_rows(model_id),
        "gate_rows": gate_rows,
        "gate_passed": gate_passed,
        "hardware": HARDWARE,
        "train": _training_facts(run, state),
    }
    repos: list[dict[str, Any]] = []

    adapter_dir = out / "adapter"
    shutil.copytree(rd / "adapter", adapter_dir, dirs_exist_ok=True)
    (adapter_dir / "README.md").write_text(
        env.get_template("model_card.md.j2").render(
            **common, library="mlx", artifact="MLX LoRA adapter", files=[]
        )
    )
    repos.append({"repo": ids["adapter"], "type": "model", "dir": adapter_dir})

    gguf = rd / "export" / "candela-pro-lora-f16.gguf"
    if gguf.exists():
        gguf_dir = out / "gguf-lora"
        gguf_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gguf, gguf_dir / gguf.name)
        (gguf_dir / "README.md").write_text(
            env.get_template("model_card.md.j2").render(
                **common, library="gguf", artifact="GGUF LoRA adapter", files=[gguf.name]
            )
        )
        repos.append({"repo": ids["gguf"], "type": "model", "dir": gguf_dir})

    traces = sorted((TRACES_DIR / data_version).glob("*.jsonl"))
    heldout = DATA_DIR / "eval" / f"tool_use-{data_version}.jsonl"
    if traces:
        ds_dir = out / "dataset"
        (ds_dir / "data").mkdir(parents=True, exist_ok=True)
        rows = [r for t in traces for r in read_jsonl(t)]
        with (ds_dir / "data" / "train.jsonl").open("w") as f:
            for t in traces:
                f.write(t.read_text())
        held = list(read_jsonl(heldout)) if heldout.exists() else []
        if held:
            shutil.copy2(heldout, ds_dir / "data" / "heldout.jsonl")
        turns = sum(1 for r in rows for m in r["messages"] if m["role"] == "assistant")
        multi = sum(1 for r in rows if sum(m["role"] == "user" for m in r["messages"]) > 1)
        failure_intents = {
            "tool_failure",
            "unknown_company",
            "fundamentals_missing",
            "personal_advice",
            "off_topic",
        }
        failures = sum(1 for r in rows if r["meta"].get("intent") in failure_intents)
        executors = Counter(r["meta"].get("executor", "?") for r in rows)
        (ds_dir / "README.md").write_text(
            env.get_template("dataset_card.md.j2").render(
                version=data_version,
                conversations=len(rows),
                heldout=len(held),
                turns=turns,
                multi_pct=round(100 * multi / max(len(rows), 1), 1),
                failure_pct=round(100 * failures / max(len(rows), 1), 1),
                executor=executors.most_common(1)[0][0],
                intents=dict(Counter(r["meta"].get("intent", "?") for r in rows).most_common()),
                model_repo=ids["adapter"],
            )
        )
        repos.append({"repo": ids["dataset"], "type": "dataset", "dir": ds_dir})
    return repos


def publish(
    run_id: str,
    dry_run: bool = True,
    out: Path | None = None,
    base_report: Path | None = None,
    tuned_report: Path | None = None,
    experimental: bool = False,
) -> list[dict[str, Any]]:
    staging = out or ML_DIR / "staging" / run_id
    if staging.exists():
        shutil.rmtree(staging)
    repos = plan(run_id, staging, base_report, tuned_report, experimental)
    table = Table(title=f"Hugging Face publish plan ({'dry run' if dry_run else 'LIVE'})")
    for col in ("repo", "type", "files", "size MB"):
        table.add_column(col)
    for r in repos:
        files = [p for p in r["dir"].rglob("*") if p.is_file()]
        table.add_row(
            r["repo"], r["type"], str(len(files)), f"{sum(p.stat().st_size for p in files) / 1e6:.1f}"
        )
    Console().print(table)
    if dry_run:
        _log.info("dry run: nothing uploaded", staging=str(staging), repos=len(repos))
        return repos
    from huggingface_hub import HfApi

    api = HfApi()
    for r in repos:
        api.create_repo(r["repo"], repo_type=r["type"], exist_ok=True)
        api.upload_folder(
            repo_id=r["repo"],
            repo_type=r["type"],
            folder_path=str(r["dir"]),
            commit_message=f"Candela {run_id}",
        )
        _log.info("uploaded", repo=r["repo"])
    published = {
        "publishedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "huggingFace": {
            "adapter": next((r["repo"] for r in repos if r["repo"].endswith("-mlx-lora")), None),
            "gguf": next((r["repo"] for r in repos if r["repo"].endswith("-gguf-lora")), None),
        },
        "dataset": next((r["repo"] for r in repos if r["type"] == "dataset"), None),
        "experimental": experimental,
    }
    (RUNS_DIR / run_id / "published.json").write_text(json.dumps(published, indent=2) + "\n")
    return repos
