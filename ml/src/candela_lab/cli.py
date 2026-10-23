from pathlib import Path
from typing import Annotated

import typer

from candela_lab import log

app = typer.Typer(
    help="Candela Lab: data, training, evaluation, export and publishing.", no_args_is_help=True
)
data_app = typer.Typer(help="Dataset fetch, build, statistics and data card.", no_args_is_help=True)
traces_app = typer.Typer(help="Synthetic tool-use traces.", no_args_is_help=True)
train_app = typer.Typer(help="Resource-guarded LoRA training.", no_args_is_help=True)
eval_app = typer.Typer(help="Deterministic evaluation suites.", no_args_is_help=True)
export_app = typer.Typer(help="Fuse adapters and convert to GGUF.", no_args_is_help=True)
models_app = typer.Typer(help="Base model preparation.", no_args_is_help=True)
observatory_app = typer.Typer(help="Observatory artifacts.", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(traces_app, name="traces")
app.add_typer(train_app, name="train")
app.add_typer(eval_app, name="eval")
app.add_typer(export_app, name="export")
app.add_typer(models_app, name="models")
app.add_typer(observatory_app, name="observatory")

DEFAULT_DATA_VERSION = "d0.1"


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    import logging

    log.setup(logging.DEBUG if verbose else logging.INFO)


@app.command()
def doctor(
    model: Annotated[str | None, typer.Option(help="Model id for the guard decision.")] = None,
    budget_gb: Annotated[float | None, typer.Option(help="Override the memory budget.")] = None,
) -> None:
    """Print versions, Metal device, memory headroom and the resource-guard decision."""
    from candela_lab import doctor as doctor_mod

    doctor_mod.run(budget_gb=budget_gb, model_id=model)


@models_app.command("check")
def models_check(
    model: Annotated[str | None, typer.Argument(help="Model id; defaults to Candela Pro.")] = None,
) -> None:
    """Verify that the read-only base, reference and GGUF files of a model are present."""
    from candela_lab import models

    raise typer.Exit(0 if models.check(model) else 1)


@data_app.command("fetch")
def data_fetch(
    version: str = DEFAULT_DATA_VERSION,
    only: Annotated[list[str] | None, typer.Option(help="Restrict to these source ids.")] = None,
    pin: Annotated[bool, typer.Option(help="Record sha256 of files that have no pinned hash yet.")] = False,
) -> None:
    """Fetch every source (pinned revision, verified sha256) into the shared caches."""
    from candela_lab.data import build

    build.fetch(version, only=only, pin=pin)


@data_app.command("build")
def data_build(
    version: str = DEFAULT_DATA_VERSION,
    tokenizer_model: Annotated[
        str, typer.Option(help="Model whose tokenizer enforces length caps.")
    ] = "lite",
) -> None:
    """Normalise, filter, deduplicate, decontaminate, mix and split; write manifest and data card."""
    from candela_lab.data import build

    build.build(version, tokenizer_model=tokenizer_model)


@data_app.command("stats")
def data_stats(version: str = DEFAULT_DATA_VERSION) -> None:
    """Print counts and token statistics from the committed manifest."""
    from candela_lab.data import build

    build.print_stats(version)


@data_app.command("card")
def data_card(version: str = DEFAULT_DATA_VERSION) -> None:
    """Re-render the data card from the manifest and processed splits."""
    from candela_lab.data import card

    card.write(version)


@traces_app.command("generate")
def traces_generate(
    n: Annotated[int, typer.Option(help="Number of conversations.")] = 200,
    executor: Annotated[str, typer.Option(help="fake | gateway")] = "fake",
    gateway_url: str = "http://127.0.0.1:8739",
    seed: int = 7,
    out: Annotated[Path | None, typer.Option(help="Output JSONL path.")] = None,
    today: Annotated[str | None, typer.Option(help="Date rendered into the system prompt.")] = None,
    split: Annotated[str, typer.Option(help="train | heldout (tool_use evaluation symbols)")] = "train",
) -> None:
    """Generate synthetic tool-use conversations through an executor."""
    from candela_lab.traces import generate

    generate.run(
        n=n, executor=executor, gateway_url=gateway_url, seed=seed, out=out, today=today, split=split
    )


@traces_app.command("validate")
def traces_validate(path: Path) -> None:
    """Validate a traces JSONL file: schemas, grounding and structure."""
    from candela_lab.traces import validate

    ok = validate.validate_file(path)
    raise typer.Exit(0 if ok else 1)


@train_app.command("run")
def train_run(
    config_path: Annotated[Path, typer.Argument(help="Training YAML in ml/configs/train/.")],
    run_id: Annotated[str | None, typer.Option(help="Run id; defaults to <config>-<utc>.")] = None,
    iters: Annotated[int | None, typer.Option(help="Override iterations.")] = None,
    simulate_pause_at: Annotated[
        list[int] | None, typer.Option(help="Steps that trigger a simulated pause.")
    ] = None,
    simulate_recover_sec: Annotated[float, typer.Option(help="Recovery hold for simulated pauses.")] = 30.0,
    probe: Annotated[
        bool, typer.Option(help="Probe mode: no checkpoints or artifacts, report only.")
    ] = False,
) -> None:
    """Start a resource-guarded LoRA run."""
    from candela_lab.train import loop

    loop.run(
        config_path,
        run_id=run_id,
        iters=iters,
        simulate_pause_at=simulate_pause_at or [],
        simulate_recover_sec=simulate_recover_sec,
        probe=probe,
    )


@train_app.command("resume")
def train_resume(run_id: str) -> None:
    """Resume a run from its latest checkpoint."""
    from candela_lab.train import loop

    loop.resume(run_id)


@train_app.command("status")
def train_status(run_id: Annotated[str | None, typer.Argument()] = None) -> None:
    """Show the state of one run or list all runs."""
    from candela_lab.train import loop

    loop.status(run_id)


@eval_app.command("run")
def eval_run(
    model: Annotated[str, typer.Argument(help="Model id (gemma-4-12b-qat).")],
    adapter: Annotated[Path | None, typer.Option(help="LoRA adapter directory.")] = None,
    suites: Annotated[list[str] | None, typer.Option("--suite", help="Restrict to these suites.")] = None,
    mode: Annotated[str, typer.Option(help="fast | full")] = "fast",
    label: Annotated[str | None, typer.Option(help="Report id; defaults to the model id.")] = None,
    limit: Annotated[int | None, typer.Option(help="Cap samples per suite (smoke runs).")] = None,
) -> None:
    """Run the evaluation suites for a base model or an adapter."""
    from candela_lab.eval import runner

    runner.run(model, adapter=adapter, suites=suites, mode=mode, label=label, limit=limit)


@eval_app.command("compare")
def eval_compare(
    base_report: Path,
    tuned_report: Path,
    model_id: Annotated[str, typer.Option(help="Observatory model id.")],
) -> None:
    """Compare two reports and write the Observatory eval.json."""
    from candela_lab.eval import report

    report.compare(base_report, tuned_report, model_id)


@export_app.command("fuse")
def export_fuse(run_id: str, out: Path | None = None) -> None:
    """Fuse a run's adapter into a de-quantized model."""
    from candela_lab.export import fuse

    fuse.fuse(run_id, out=out)


@export_app.command("gguf")
def export_gguf(
    run_id: str,
    quant: str = "Q4_K_M",
    lora: Annotated[
        bool, typer.Option(help="Export the adapter as a GGUF LoRA (PEFT → convert_lora_to_gguf).")
    ] = True,
    check: Annotated[
        bool, typer.Option(help="Load it with llama-server --lora on 127.0.0.1:8713 and compare.")
    ] = False,
) -> None:
    """Convert a run's adapter to a GGUF LoRA with the pinned llama.cpp converter (fused exports are refused)."""
    from candela_lab.export import gguf

    if not lora:
        gguf.export_fused(run_id, quant=quant)
        return
    gguf.export_lora(run_id)
    if check:
        gguf.serve_check(run_id)


@observatory_app.command("export")
def observatory_export(
    run_id: Annotated[
        str | None, typer.Argument(help="Run to export; defaults to all exported runs.")
    ] = None,
    sync: Annotated[
        bool, typer.Option(help="Copy ml/artifacts/observatory into apps/web/public/observatory.")
    ] = False,
) -> None:
    """Write Observatory artifacts for a run and optionally sync them into the web app."""
    from candela_lab import observatory

    if run_id:
        observatory.export_run(run_id)
    observatory.write_manifest()
    if sync:
        observatory.sync()


@app.command()
def publish(
    run_id: str,
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    out: Annotated[Path | None, typer.Option(help="Staging directory for rendered repos.")] = None,
) -> None:
    """Render model and dataset cards and stage Hugging Face uploads (dry run by default)."""
    from candela_lab.publish import hub

    hub.publish(run_id, dry_run=dry_run, out=out)


if __name__ == "__main__":
    app()
