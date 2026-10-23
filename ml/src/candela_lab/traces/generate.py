import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from candela_lab import config, log
from candela_lab.data.common import stable_id, write_jsonl
from candela_lab.paths import DATA_DIR, ML_DIR
from candela_lab.traces import compose, market, scenarios, validate
from candela_lab.traces.executor import (
    Executor,
    FakeExecutor,
    GatewayExecutor,
    check_contract_shapes,
    error_view,
)

_log = log.get("traces.generate")

DEFAULT_AS_OF = "2026-10-22"


def conversation(
    plan: scenarios.Plan, executor: Executor, rng: random.Random, today: str, conv_id: str
) -> dict[str, Any]:
    w = compose.Writer(rng)
    messages: list[dict[str, Any]] = [{"role": "system", "content": config.system_prompt(today)}]
    counter = 0
    calls_made: list[str] = []
    for turn in plan.turns:
        messages.append({"role": "user", "content": turn.user})
        gen = turn.script(w)
        try:
            calls = next(gen)
            while True:
                results = []
                for name, args in calls:
                    forced = plan.failures.get((name, str(args.get("symbol", ""))))
                    results.append(
                        error_view(forced, f"{name} is temporarily unavailable")
                        if forced
                        else executor.execute(name, args)
                    )
                    calls_made.append(name)
                messages.append(scenarios.tool_call_message(calls, counter))
                messages.extend(scenarios.tool_messages(calls, results, counter))
                counter += len(calls)
                calls = gen.send(results)
        except StopIteration as stop:
            messages.append({"role": "assistant", "content": str(stop.value)})
    return {
        "messages": messages,
        "tools": config.tools_schema(),
        "meta": {
            "id": conv_id,
            "task": f"tool_use:{plan.intent}",
            "intent": plan.intent,
            "executor": executor.name,
            "symbols": plan.symbols,
            "derived": sorted(set(w.derived)),
            "tools": dict(Counter(calls_made)),
            "turns": len(plan.turns),
        },
    }


def make_executor(kind: str, gateway_url: str, as_of: str) -> Executor:
    if kind == "fake":
        problems = check_contract_shapes(as_of)
        if problems:
            raise RuntimeError("fake executor drifted from contracts/tools.md: " + "; ".join(problems))
        return FakeExecutor(as_of=as_of)
    if kind == "gateway":
        gw = GatewayExecutor(base_url=gateway_url)
        if not gw.health():
            raise RuntimeError(f"gateway internal tool API not reachable at {gateway_url}")
        return gw
    raise ValueError(f"unknown executor {kind}")


def run(
    n: int,
    executor: str,
    gateway_url: str,
    seed: int,
    out: Path | None,
    today: str | None,
    split: str = "train",
) -> Path:
    as_of = DEFAULT_AS_OF
    today = today or (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
    ex = make_executor(executor, gateway_url, as_of)
    if split == "heldout":
        symbols = sorted(market.HELDOUT_SYMBOLS)
        default_out = DATA_DIR / "eval" / "tool_use-d0.1.jsonl"
    else:
        symbols = [s for s, *_ in market.UNIVERSE if s not in market.HELDOUT_SYMBOLS]
        default_out = DATA_DIR / "traces" / "d0.1" / f"{executor}-{seed}.jsonl"
    target = out if out is not None else default_out
    if not target.is_absolute():
        target = ML_DIR / target
    rng = random.Random(f"traces:{split}:{seed}")
    fund_ok = ex.fundamentals_enabled if isinstance(ex, FakeExecutor) else (lambda _s: True)
    rows, rejected = [], Counter()
    attempts = 0
    while len(rows) < n and attempts < n * 3:
        attempts += 1
        plan = scenarios.plan(rng, symbols, fund_ok)
        conv_id = stable_id("trace", split, str(seed), str(attempts))
        row = conversation(plan, ex, rng, today, conv_id)
        problems = validate.validate_conversation(row)
        if problems:
            rejected[problems[0].split(":")[0]] += 1
            continue
        rows.append(row)
    write_jsonl(target, rows)
    intents = Counter(r["meta"]["intent"] for r in rows)
    multi = sum(1 for r in rows if r["meta"]["turns"] > 1)
    _log.info(
        "traces written",
        path=str(target),
        conversations=len(rows),
        rejected=dict(rejected),
        multi_turn_pct=round(100 * multi / max(len(rows), 1), 1),
        intents=dict(intents),
    )
    return target
