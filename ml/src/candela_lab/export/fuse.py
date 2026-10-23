from pathlib import Path


def fuse(run_id: str, out: Path | None = None) -> Path:
    del out
    raise SystemExit(
        f"Refusing to fuse {run_id}: Candela Pro keeps Google's QAT int4 base frozen and loads the adapter unmerged "
        "(ADR 0003); a merged release would need a QAT/distillation pass. Export a GGUF LoRA with "
        "`lab export gguf <run-id> --lora` instead."
    )
