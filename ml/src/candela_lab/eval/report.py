import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candela_lab import log
from candela_lab.paths import ML_OBSERVATORY_DIR

_log = log.get("eval.report")


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def markdown(p: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation — {p['reportId']}",
        "",
        f"- Model: `{p['modelId']}` (base `{p['baseModel']}`)"
        + (f", adapter `{p['adapter']}`" if p.get("adapter") else ""),
        f"- Mode: {p['mode']}"
        + (f" (limit {p['limit']} per suite)" if p.get("limit") else "")
        + f", dataset {p['datasetVersion']}, eval seed {p['evalSeed']}, greedy decoding, thinking off",
        f"- Evaluated {p['evaluatedAt']} on {p['machine']} in {p['durationSec'] / 60:.1f} min, peak MLX memory {p['peakMemGb']} GB",
        "",
        "| Suite | Metric | Value | n | Seconds | Details |",
        "|---|---|---:|---:|---:|---|",
    ]
    for sid, s in p["suites"].items():
        details = ", ".join(
            f"{k}={_fmt(v)}" for k, v in (s.get("details") or {}).items() if not isinstance(v, (list, dict))
        )
        lines.append(
            f"| {s['name']} (`{sid}`) | {s['metric']} | {_fmt(s['value'])} | {s['n']} | {s['seconds']} | {details} |"
        )
    lines += ["", "## Samples", ""]
    for sid, s in p["suites"].items():
        for sample in (s.get("samples") or [])[:2]:
            lines.append(f"**{sid}** — `{json.dumps(sample, default=str)[:600]}`")
            lines.append("")
    return "\n".join(lines) + "\n"


def compare(base_path: Path, tuned_path: Path, model_id: str) -> Path:
    base = json.loads(base_path.read_text())
    tuned = json.loads(tuned_path.read_text())
    suites = []
    for sid, b in base["suites"].items():
        t = tuned["suites"].get(sid)
        if t is None or b.get("value") is None or t.get("value") is None:
            continue
        suites.append(
            {
                "id": sid,
                "name": b["name"],
                "metric": b["metric"],
                "higherIsBetter": b["higherIsBetter"],
                "n": min(int(b["n"]), int(t["n"])),
                "base": round(float(b["value"]), 4),
                "tuned": round(float(t["value"]), 4),
                "delta": round(float(t["value"]) - float(b["value"]), 4),
            }
        )
    for key, name, metric in (("groundingRate", "Tool-use grounding", "grounding_rate"),):
        bv = (base["suites"].get("tool_use", {}).get("details") or {}).get(key)
        tv = (tuned["suites"].get("tool_use", {}).get("details") or {}).get(key)
        if bv is not None and tv is not None:
            n = int(tuned["suites"]["tool_use"]["n"])
            suites.append(
                {
                    "id": f"tool_use_{metric}",
                    "name": name,
                    "metric": metric,
                    "higherIsBetter": True,
                    "n": n,
                    "base": round(bv, 4),
                    "tuned": round(tv, 4),
                    "delta": round(tv - bv, 4),
                }
            )
    samples = []
    for sid in ("tool_use", "finqa", "fpb"):
        bs = (base["suites"].get(sid) or {}).get("samples") or []
        ts = (tuned["suites"].get(sid) or {}).get("samples") or []
        for b, t in zip(bs, ts, strict=False):
            samples.append(
                {
                    "suite": sid,
                    "prompt": str(b.get("prompt", b.get("gold", "")))[:400],
                    "base": str(b.get("output", ""))[:600],
                    "tuned": str(t.get("output", ""))[:600],
                }
            )
            if len(samples) >= 6:
                break
    payload = {
        "modelId": model_id,
        "baseModel": base["baseModel"],
        "evaluatedAt": tuned.get("evaluatedAt") or datetime.now(UTC).isoformat(timespec="seconds"),
        "datasetVersion": tuned.get("datasetVersion", "d0.1"),
        "suites": suites,
        "samples": samples[:10],
    }
    out = ML_OBSERVATORY_DIR / "models" / model_id / "eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")))
    _log.info("observatory eval written", path=str(out), suites=len(suites))
    return out
