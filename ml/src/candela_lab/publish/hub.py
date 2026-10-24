import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from candela_lab import config, log
from candela_lab.data.card import environment
from candela_lab.data.common import read_jsonl
from candela_lab.paths import ML_DIR, ML_OBSERVATORY_DIR, RUNS_DIR, TRACES_DIR

_log = log.get("publish")
NAMESPACE = "UmitVice"


def _eval_rows(model_id: str) -> list[dict[str, Any]]:
    path = ML_OBSERVATORY_DIR / "models" / model_id / "eval.json"
    return json.loads(path.read_text())["suites"] if path.exists() else []


def plan(run_id: str, out: Path) -> list[dict[str, Any]]:
    rd = RUNS_DIR / run_id
    run = json.loads((rd / "run.json").read_text())
    state = json.loads((rd / "state.json").read_text())
    cfg = run["config"]
    spec = config.model(cfg["model"])
    obs = cfg.get("observatory", {})
    model_id = obs.get("modelId", run_id)
    version = obs.get("version", "dev")
    pilot = bool(cfg.get("pilot", False))
    suffix = "-pilot" if pilot and "pilot" not in version else ""
    dataset_repo = f"{NAMESPACE}/candela-tool-traces"
    env = environment()
    common = {
        "display_name": obs.get("displayName", "Candela Pro"),
        "base_model": spec.upstream,
        "run_id": run_id,
        "steps": state["step"],
        "dataset_version": cfg.get("data", {}).get("version", "d0.1"),
        "lora": run["lora"],
        "layers": f"{run['layerIndices'][0]}–{run['layerIndices'][-1]}" if run["layerIndices"] else "none",
        "pilot": pilot,
        "dataset_repo": dataset_repo,
        "eval_rows": _eval_rows(model_id),
    }
    repos: list[dict[str, Any]] = []

    adapter_dir = out / "adapter"
    shutil.copytree(rd / "adapter", adapter_dir, dirs_exist_ok=True)
    (adapter_dir / "README.md").write_text(
        env.get_template("model_card.md.j2").render(
            **common, library="mlx", artifact="MLX LoRA adapter", files=[]
        )
    )
    repos.append(
        {
            "repo": f"{NAMESPACE}/candela-pro-{version}{suffix}-mlx-adapter",
            "type": "model",
            "dir": adapter_dir,
        }
    )

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
        repos.append(
            {"repo": f"{NAMESPACE}/candela-pro-{version}{suffix}-gguf-lora", "type": "model", "dir": gguf_dir}
        )

    traces = sorted((TRACES_DIR / common["dataset_version"]).glob("*.jsonl"))
    if traces:
        ds_dir = out / "dataset"
        (ds_dir / "data").mkdir(parents=True, exist_ok=True)
        rows = [r for t in traces for r in read_jsonl(t)]
        for t in traces:
            shutil.copy2(t, ds_dir / "data" / t.name)
        turns = sum(1 for r in rows for m in r["messages"] if m["role"] == "assistant")
        multi = sum(1 for r in rows if sum(m["role"] == "user" for m in r["messages"]) > 1)
        executors = Counter(r["meta"].get("executor", "?") for r in rows)
        (ds_dir / "README.md").write_text(
            env.get_template("dataset_card.md.j2").render(
                version=common["dataset_version"],
                conversations=len(rows),
                turns=turns,
                multi_pct=round(100 * multi / max(len(rows), 1), 1),
                executor=executors.most_common(1)[0][0],
                intents=dict(Counter(r["meta"].get("intent", "?") for r in rows).most_common()),
            )
        )
        repos.append({"repo": dataset_repo, "type": "dataset", "dir": ds_dir})
    return repos


def publish(run_id: str, dry_run: bool = True, out: Path | None = None) -> list[dict[str, Any]]:
    staging = out or ML_DIR / "staging" / run_id
    if staging.exists():
        shutil.rmtree(staging)
    repos = plan(run_id, staging)
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
        api.upload_folder(repo_id=r["repo"], repo_type=r["type"], folder_path=str(r["dir"]))
        _log.info("uploaded", repo=r["repo"])
    return repos
