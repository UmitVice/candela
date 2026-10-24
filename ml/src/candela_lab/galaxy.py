"""Observatory embedding galaxy: mean last-layer hidden state of Candela Pro over a one-sentence description of each
S&P 500 constituent, reduced to 3D with PCA, coloured by GICS sector, sized by snapshot market cap."""

import csv
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlx.core as mx
import numpy as np

from candela_lab import log
from candela_lab.data.sources import url_file
from candela_lab.paths import ML_OBSERVATORY_DIR, REPO_ROOT

_log = log.get("galaxy")

# datasets/s-and-p-500-companies (Open Data Commons PDDL), pinned to a commit; sha256 lives in the data lock.
CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "b02693261eae31391189b5cae0764532387aecbf/data/constituents.csv"
)
SNAPSHOT = REPO_ROOT / "services" / "gateway" / "data" / "market.sqlite"
SECTOR_COLORS = {
    "Communication Services": "#e8a33d",
    "Consumer Discretionary": "#d9644a",
    "Consumer Staples": "#9bbf4d",
    "Energy": "#c9853a",
    "Financials": "#4a90d9",
    "Health Care": "#5cc4a8",
    "Industrials": "#8e8ccf",
    "Information Technology": "#47b5e6",
    "Materials": "#b58f6d",
    "Real Estate": "#cf6fa6",
    "Utilities": "#7fae8e",
}


def constituents(pin: bool = False) -> list[dict[str, str]]:
    with url_file(CONSTITUENTS_URL, pin=pin).open(newline="") as f:
        return list(csv.DictReader(f))


def describe(row: dict[str, str]) -> str:
    hq = row.get("Headquarters Location", "").strip()
    founded = row.get("Founded", "").strip()
    sub = row["GICS Sub-Industry"]
    article = "an" if sub[:1].lower() in "aeiou" else "a"
    text = (
        f"{row['Security']} ({row['Symbol']}) is {article} {sub} company in the {row['GICS Sector']} sector"
    )
    if hq:
        text += f", headquartered in {hq}"
    if founded:
        text += f", founded in {founded.split('(')[0].strip()}"
    return text + "."


def market_caps(symbols: list[str]) -> dict[str, float]:
    if not SNAPSHOT.exists():
        return {}
    out: dict[str, float] = {}
    con = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)
    try:
        for sym in symbols:
            for candidate in (sym, sym.replace(".", "-"), sym.replace(".", "")):
                close = con.execute(
                    "SELECT c FROM bars WHERE symbol = ? ORDER BY t DESC LIMIT 1", (candidate,)
                ).fetchone()
                shares = con.execute(
                    "SELECT shares_outstanding FROM fundamentals WHERE symbol = ? AND shares_outstanding IS NOT NULL "
                    "ORDER BY period_end DESC LIMIT 1",
                    (candidate,),
                ).fetchone()
                if close and shares and shares[0]:
                    out[sym] = round(float(close[0]) * float(shares[0]) / 1e9, 1)
                    break
    finally:
        con.close()
    return out


def pca3(x: np.ndarray) -> np.ndarray:
    centred = x - x.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    y = centred @ vt[:3].T
    return y / (np.abs(y).max(axis=0, keepdims=True) + 1e-9)


def export(model_id: str, adapter: Path | None, out: Path | None = None) -> Path:
    from candela_lab.eval import runner
    from candela_lab.observatory import _dump
    from candela_lab.train.loss import text_model

    rows = constituents()
    texts = [describe(r) for r in rows]
    vectors: list[np.ndarray] = []
    with runner.engine_session("gemma-4-12b-qat", adapter, f"galaxy {model_id}") as engine:
        inner = text_model(engine.model).model
        for i, text in enumerate(texts):
            if i % 50 == 0:
                engine.lease.yield_if_needed()
            ids = engine.tokenizer.encode(text)
            h = inner(mx.array([ids]))
            vec = mx.mean(h[0, 1:].astype(mx.float32), axis=0)
            mx.eval(vec)
            vectors.append(np.array(vec))
    coords = pca3(np.stack(vectors))
    caps = market_caps([r["Symbol"] for r in rows])
    sectors = sorted({r["GICS Sector"] for r in rows})
    sector_id = {s: s.lower().replace(" ", "-") for s in sectors}
    points: list[dict[str, Any]] = []
    for r, (x, y, z) in zip(rows, coords.tolist(), strict=True):
        point: dict[str, Any] = {
            "symbol": r["Symbol"],
            "name": r["Security"],
            "sector": sector_id[r["GICS Sector"]],
            "x": round(x, 4),
            "y": round(y, 4),
            "z": round(z, 4),
        }
        if r["Symbol"] in caps:
            point["marketCapB"] = caps[r["Symbol"]]
        points.append(point)
    payload = {
        "modelId": model_id,
        "method": "pca",
        "source": "hidden_state_mean",
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sectors": [
            {"id": sector_id[s], "name": s, "color": SECTOR_COLORS.get(s, "#9aa4b2")} for s in sectors
        ],
        "points": points,
    }
    target = out or ML_OBSERVATORY_DIR / "galaxy.json"
    _dump(target, payload)
    _log.info("galaxy written", points=len(points), with_market_cap=len(caps), path=str(target))
    return target
