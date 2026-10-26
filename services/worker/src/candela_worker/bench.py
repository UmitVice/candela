import asyncio
import dataclasses
import json
import statistics
import time
from typing import Any

from candela_worker import sysinfo
from candela_worker.config import ModelSpec, Settings
from candela_worker.engine import Engine, Job

PROMPT = (
    "Explain step by step how an analyst reads a company's cash flow statement: operating, investing and "
    "financing activities, free cash flow, and the warning signs to look for. Be thorough."
)
FILLER = (
    "Revenue grew 12.4% year over year to $4.21 billion while gross margin expanded 180 basis points to 61.3%, "
    "driven by mix shift toward subscription services. Operating expenses rose 8.1%, mainly research and "
    "development headcount. Free cash flow was $812 million after capital expenditure of $305 million. "
)


@dataclasses.dataclass
class Run:
    label: str
    ttft_ms: float
    prefill_tps: float
    decode_tps: float
    tokens: int
    peak_mb: float
    text: str
    frames: int


async def _one(
    engine: Engine, model_id: str, prompt: str, max_tokens: int, telemetry: bool, label: str
) -> Run:
    text: list[str] = []
    frames = 0
    usage: dict[str, Any] = {}

    async def emit(event: str, data: dict[str, Any]) -> None:
        nonlocal frames, usage
        if event in ("token", "reasoning"):
            text.append(data["delta"])
        elif event == "telemetry":
            frames += 1
        elif event == "usage":
            usage = data
        elif event == "error":
            raise RuntimeError(data["message"])

    engine.clear_prompt_cache()
    job = Job(
        job_id=f"bench-{label}",
        model_id=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
        telemetry=telemetry,
        deadline_ms=600_000,
    )
    await engine.run(job, emit)
    st = engine.last_stats
    prefill = st.get("prefill_sec") or 0.0
    return Run(
        label=label,
        ttft_ms=float(usage.get("timeToFirstTokenMs", 0)),
        prefill_tps=round(st.get("prompt_tokens", 0) / prefill, 1) if prefill else 0.0,
        decode_tps=float(usage.get("tokensPerSecond", 0.0)),
        tokens=int(usage.get("completionTokens", 0)),
        peak_mb=float(st.get("peak_mb", 0)),
        text="".join(text),
        frames=frames,
    )


def _agreement(a: str, b: str) -> float:
    wa, wb = a.split(), b.split()
    n = max(len(wa), len(wb)) or 1
    same = 0
    for x, y in zip(wa, wb, strict=False):
        if x != y:
            break
        same += 1
    return round(same / n, 3)


async def bench(
    settings: Settings,
    registry: dict[str, ModelSpec],
    model_id: str,
    runs: int,
    max_tokens: int,
    telemetry: bool,
    kv_tokens: int,
) -> dict[str, Any]:
    engine = Engine(settings, registry)
    before = sysinfo.memory()
    results: list[Run] = []
    try:
        cold = await _one(engine, model_id, PROMPT, max_tokens, False, "cold")
        results.append(cold)
        load_sec = engine.loaded.load_sec if engine.loaded else 0.0
        for i in range(runs):
            results.append(await _one(engine, model_id, PROMPT, max_tokens, False, f"warm-{i + 1}"))
        if telemetry:
            for i in range(runs):
                results.append(await _one(engine, model_id, PROMPT, max_tokens, True, f"telemetry-{i + 1}"))
        loaded_mem = sysinfo.memory()
        kv: dict[str, Any] = {}
        if kv_tokens:
            reps = max(1, kv_tokens // 60)
            long_prompt = FILLER * reps + "\n\nSummarize the figures above in three sentences."
            plain = await _one(engine, model_id, long_prompt, 96, False, "long-fp16-kv")
            quant_engine = dataclasses.replace(settings, kv_bits=8, kv_start=1024)
            engine.settings = quant_engine
            quant = await _one(engine, model_id, long_prompt, 96, False, "long-8bit-kv")
            engine.settings = settings
            results += [plain, quant]
            kv = {
                "promptTokens": engine.last_stats.get("prompt_tokens"),
                "peakMbFp16": plain.peak_mb,
                "peakMb8bit": quant.peak_mb,
                "savedMb": round(plain.peak_mb - quant.peak_mb),
                "decodeTpsFp16": plain.decode_tps,
                "decodeTps8bit": quant.decode_tps,
                "greedyWordAgreement": _agreement(plain.text, quant.text),
            }
    finally:
        await engine.close()
    after = sysinfo.memory()
    warm = [r for r in results if r.label.startswith("warm")]
    tele = [r for r in results if r.label.startswith("telemetry")]
    summary: dict[str, Any] = {
        "model": model_id,
        "loadSec": round(load_sec, 2),
        "coldTtftMs": cold.ttft_ms,
        "warmTtftMs": round(statistics.median(r.ttft_ms for r in warm)) if warm else None,
        "prefillTps": statistics.median(r.prefill_tps for r in warm) if warm else None,
        "decodeTps": statistics.median(r.decode_tps for r in warm) if warm else None,
        "peakMb": max(r.peak_mb for r in results),
        "availableGbBefore": round(before.available_gb, 2),
        "availableGbLoaded": round(loaded_mem.available_gb, 2),
        "availableGbAfterUnload": round(after.available_gb, 2),
    }
    if tele and warm:
        t = statistics.median(r.decode_tps for r in tele)
        summary["telemetryDecodeTps"] = t
        summary["telemetryOverheadPct"] = round((1 - t / summary["decodeTps"]) * 100, 1)
        summary["telemetryFramesPerSec"] = round(
            statistics.median(r.frames / max(r.tokens / max(r.decode_tps, 1e-9), 1e-9) for r in tele), 1
        )
        summary["telemetrySameText"] = all(r.text == warm[0].text for r in tele)
    if kv:
        summary["kvCache"] = kv
    summary["runs"] = [{k: v for k, v in dataclasses.asdict(r).items() if k != "text"} for r in results]
    return summary


def run_bench(
    settings: Settings,
    registry: dict[str, ModelSpec],
    model_id: str,
    runs: int,
    max_tokens: int,
    telemetry: bool,
    kv_tokens: int,
) -> None:
    started = time.perf_counter()
    summary = asyncio.run(bench(settings, registry, model_id, runs, max_tokens, telemetry, kv_tokens))
    summary["benchSec"] = round(time.perf_counter() - started, 1)
    print(json.dumps(summary, indent=2))
