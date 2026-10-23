import importlib.metadata
import json
import os
import sys
from pathlib import Path

import typer

from candela_spark import log, paths

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Candela Spark")
data_app = typer.Typer(no_args_is_help=True, help="Fetch, process and inspect pretraining data")
tok_app = typer.Typer(no_args_is_help=True, help="Train and inspect the frozen tokenizer")
daemon_app = typer.Typer(no_args_is_help=True, help="Continuous-training LaunchAgent")
obs_app = typer.Typer(no_args_is_help=True, help="Observatory artifacts")
app.add_typer(data_app, name="data")
app.add_typer(tok_app, name="tokenizer")
app.add_typer(daemon_app, name="daemon")
app.add_typer(obs_app, name="observatory")

_log = log.get("cli")


def _echo(obj: object) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


@app.command()
def doctor() -> None:
    """Versions, Metal device, memory headroom, power, leases and data state."""
    import mlx.core as mx
    import tokenizers

    from candela_spark.ops import lease, resources

    snap = resources.snapshot()
    guard = resources.ResourceGuard(4.0)
    tok_meta = paths.TOKENIZER_META
    _echo(
        {
            "python": sys.version.split()[0],
            "mlx": importlib.metadata.version("mlx"),
            "tokenizers": tokenizers.__version__,
            "device": mx.device_info(),
            "memory": snap.as_dict(),
            "guardStart": guard.start().reason,
            "onBattery": resources.on_battery(),
            "thermalSerious": resources.thermal_serious(),
            "leases": [vars(x) for x in lease.live_leases()],
            "tokenizer": json.loads(tok_meta.read_text()) if tok_meta.exists() else None,
            "dataRaw": (paths.RAW / "manifest-v0.json").exists(),
            "dataTokenized": (paths.TOKENIZED / "v0" / "stats.json").exists(),
        }
    )


@data_app.command("fetch")
def data_fetch(version: str = "v0", only: list[str] | None = None, verify: bool = False) -> None:
    """Download pinned sources, verify SHA-256 and write the manifest."""
    from candela_spark.data import config, fetch

    cfg = config.load(version)
    if verify:
        bad = fetch.verify(cfg)
        _echo({"corrupt": bad})
        raise typer.Exit(1 if bad else 0)
    fetch.fetch(cfg, only)


@data_app.command("process")
def data_process(version: str = "v0", stage: str = "all", workers: int = 3) -> None:
    """Stages: sample (tokenizer), build (filter, tokenize, sign), index (dedup, shuffle, split), all."""
    from candela_spark.data import config, process

    cfg = config.load(version)
    if stage == "sample":
        process.tokenizer_sample(cfg)
        return
    if stage in ("build", "all"):
        process.build(cfg, workers)
    if stage in ("index", "all"):
        _echo(process.dedup_and_index(cfg))


@data_app.command("stats")
def data_stats(version: str = "v0") -> None:
    """Token counts per source after dedup."""
    path = paths.TOKENIZED / version / "stats.json"
    if not path.exists():
        raise typer.BadParameter("run `spark data process` first")
    _echo(json.loads(path.read_text()))


@tok_app.command("train")
def tokenizer_train() -> None:
    """Train the byte-level BPE on the balanced sample (run `spark data process --stage sample` first)."""
    os.environ.setdefault("RAYON_NUM_THREADS", "4")
    from candela_spark.data.process import iter_sample_texts
    from candela_spark.tokenizer import train

    if paths.TOKENIZER_FILE.exists():
        raise typer.BadParameter("the tokenizer is frozen for the whole family; refusing to retrain")
    _echo(train.train(iter_sample_texts(paths.PROCESSED / "tokenizer-sample")))


@tok_app.command("inspect")
def tokenizer_inspect(text: str) -> None:
    """Show how a text tokenizes."""
    from candela_spark.tokenizer.train import load

    enc = load().encode(text, add_special_tokens=False)
    _echo({"count": len(enc.ids), "tokens": enc.tokens, "ids": enc.ids})


@app.command()
def train(
    config: Path, max_steps: int | None = None, priority: int | None = None, allow_network: bool = False
) -> None:
    """Run or resume a training run from a YAML config."""
    from candela_spark.train import config as run_config
    from candela_spark.train.trainer import Trainer

    overrides: dict[str, object] = {}
    if max_steps is not None:
        overrides["max_steps"] = max_steps
    if priority is not None:
        overrides["lease_priority"] = priority
    cfg = run_config.load(config, overrides)
    raise typer.Exit(Trainer(cfg, force_offline=not allow_network).run())


@app.command()
def sample(
    run: str,
    prompt: list[str] | None = None,
    max_new_tokens: int = 80,
    temperature: float = 0.8,
    seed: int = 0,
    bf16: bool = False,
) -> None:
    """Fixed-seed samples from the latest valid checkpoint of a run."""
    from candela_spark.eval.prompts import SAMPLE_PROMPTS
    from candela_spark.model.generate import generate, load_from_checkpoint
    from candela_spark.train import checkpoint

    ckpt = checkpoint.latest_valid(paths.RUNS / run / "checkpoints")
    if ckpt is None:
        raise typer.BadParameter(f"no valid checkpoint for {run}")
    model = load_from_checkpoint(ckpt)
    prompts = prompt or SAMPLE_PROMPTS
    _echo(
        [
            {
                "prompt": p,
                "completion": generate(model, p, max_new_tokens, temperature, seed=seed, qat=not bf16),
            }
            for p in prompts
        ]
    )


@app.command("eval")
def evaluate(run: str, label: str | None = None, n: int = 500, export_dir: Path | None = None) -> None:
    """Per-source perplexity (bf16, int4), zero-shot suite, finance cloze, samples; writes reports/."""
    from candela_spark.eval import suite

    _echo(suite.run(run, label, n, export_dir))


@app.command("export")
def export(run: str, name: str, gguf: bool = True) -> None:
    """Export the latest checkpoint of a run as MLX int4 (+ bf16 reference, + GGUF Q4_1)."""
    from candela_spark.export import mlx_export

    _echo(mlx_export.export(run, name, gguf=gguf))


@app.command()
def status() -> None:
    """Print the sanitised trainer status."""
    from candela_spark.ops import status as st

    _echo(st.read() or {"state": "unknown"})


@daemon_app.command("install")
def daemon_install(config: Path = paths.CONFIGS / "train" / "spark-35m-main.yaml") -> None:
    """Install and load the user LaunchAgent com.candela.spark-trainer."""
    from candela_spark.ops import daemon

    _echo(daemon.install(config))


@daemon_app.command("uninstall")
def daemon_uninstall() -> None:
    """Unload and remove the LaunchAgent (the trainer checkpoints on SIGTERM)."""
    from candela_spark.ops import daemon

    _echo(daemon.uninstall())


@daemon_app.command("status")
def daemon_status() -> None:
    """launchd state of the LaunchAgent plus the trainer status."""
    from candela_spark.ops import daemon

    _echo(daemon.status())


@obs_app.command("export")
def observatory_export(run: str = "spark-35m-main", milestone: str = "spark-35m-m1") -> None:
    """Write architecture, training, milestone and attention artifacts for the Observatory."""
    from candela_spark.export import observatory

    _echo(observatory.export(run, milestone))


@app.command()
def publish(
    name: str = "spark-35m-m1", repo: str = "UmitVice/candela-spark-35m", dry_run: bool = False
) -> None:
    """Publish an exported milestone (int4 MLX, GGUF, tokenizer, config, card) to Hugging Face."""
    from candela_spark.export import publish as pub

    _echo(pub.publish(name, repo, dry_run))
