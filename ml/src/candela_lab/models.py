from pathlib import Path

from rich.console import Console
from rich.table import Table

from candela_lab import config


def _size_gb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1024**3
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1024**3


def check(model_id: str | None = None) -> bool:
    spec = config.model(model_id)
    table = Table(title=f"{spec.display_name} ({spec.id})")
    table.add_column("artifact")
    table.add_column("path")
    table.add_column("status")
    ok = True
    for label, path in (
        ("mlx int4 base", spec.base_path()),
        ("bf16 QAT reference", spec.reference_path()),
        ("QAT Q4 GGUF", spec.gguf_path()),
    ):
        if path is None:
            continue
        p = Path(path)
        if p.exists():
            table.add_row(label, path, f"[green]present[/green] {_size_gb(p):.1f} GB")
        else:
            ok = ok and label != "mlx int4 base"
            table.add_row(label, path, "[red]missing[/red]")
    Console().print(table)
    return ok
