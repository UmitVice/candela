import importlib.metadata as md
import platform
import shutil
import sys

from rich.console import Console
from rich.table import Table

from candela_lab import config, resources

PACKAGES = [
    "mlx",
    "mlx-lm",
    "transformers",
    "datasets",
    "huggingface_hub",
    "tokenizers",
    "sentencepiece",
    "gguf",
    "numpy",
    "pandas",
    "scikit-learn",
]


def run(budget_gb: float | None = None, model_id: str | None = None) -> bool:
    import mlx.core as mx

    console = Console()
    versions = Table(title="Candela Lab doctor", show_header=True)
    versions.add_column("component")
    versions.add_column("version / value")
    versions.add_row("python", sys.version.split()[0])
    versions.add_row("platform", f"{platform.system()} {platform.release()} {platform.machine()}")
    for pkg in PACKAGES:
        try:
            versions.add_row(pkg, md.version(pkg))
        except md.PackageNotFoundError:
            versions.add_row(pkg, "[red]missing[/red]")
    info = mx.device_info()
    versions.add_row("metal device", f"{info.get('device_name')} ({info.get('architecture')})")
    versions.add_row("metal available", str(mx.metal.is_available()))
    versions.add_row(
        "recommended working set",
        f"{int(info.get('max_recommended_working_set_size', 0)) / resources.GB:.1f} GB",
    )
    for tool in ("llama-server", "llama-quantize", "hf", "caffeinate"):
        versions.add_row(tool, shutil.which(tool) or "[yellow]not found[/yellow]")
    console.print(versions)

    snap = resources.snapshot()
    mem = Table(title="Memory headroom")
    mem.add_column("metric")
    mem.add_column("value")
    for k, v in snap.as_dict().items():
        mem.add_row(k, f"{v} GB" if isinstance(v, float) else str(v))
    console.print(mem)

    from candela_lab import gpu_lease, models

    models.check(model_id)
    leases = gpu_lease.live_leases()
    console.print(
        "GPU leases: "
        + (", ".join(f"{x.holder} (priority {x.priority}, pid {x.pid})" for x in leases) or "none live")
    )
    spec = config.model(model_id)
    budget = budget_gb if budget_gb is not None else spec.train_budget_gb
    guard = resources.ResourceGuard(budget_gb=budget)
    decision = guard.start_decision()
    verdict = "[green]START[/green]" if decision.ok else "[yellow]WAIT[/yellow]"
    console.print(
        f"Guard decision for {spec.id} training (budget {budget:.1f} GB, needs "
        f"{guard.required_start_gb():.1f} GB available): {verdict} — {decision.reason}"
    )
    return True
