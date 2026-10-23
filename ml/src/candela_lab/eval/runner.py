import json
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlx.core as mx

from candela_lab import config, gpu_lease, log, resources
from candela_lab.data.common import read_jsonl
from candela_lab.eval import datasets, metrics, report
from candela_lab.paths import PROCESSED_DIR, REPORTS_DIR
from candela_lab.traces.grounding import grounding_report
from candela_lab.traces.schema import validate_arguments

_log = log.get("eval")

# Fast mode keeps each model under ~30 minutes on the M5 Pro; full mode uses the master-plan sizes.
SIZES = {
    "fast": {
        "fpb": 300,
        "fiqa_sa": 235,
        "headlines": 300,
        "finqa": 100,
        "convfinqa": 100,
        "tatqa": 100,
        "tool_use": 40,
        "heldout_loss": 100,
    },
    "full": {
        "fpb": 500,
        "fiqa_sa": 235,
        "headlines": 500,
        "finqa": 300,
        "convfinqa": 300,
        "tatqa": 300,
        "tool_use": 300,
        "heldout_loss": 400,
    },
}
SUITES = ["fpb", "fiqa_sa", "headlines", "finqa", "convfinqa", "tatqa", "tool_use", "heldout_loss"]
SUITE_INFO: dict[str, dict[str, Any]] = {
    "fpb": {"name": "Financial PhraseBank", "metric": "macro_f1", "higherIsBetter": True},
    "fiqa_sa": {"name": "FiQA sentiment", "metric": "weighted_f1", "higherIsBetter": True},
    "headlines": {"name": "Gold headlines", "metric": "weighted_f1", "higherIsBetter": True},
    "finqa": {"name": "FinQA", "metric": "numeric_em", "higherIsBetter": True},
    "convfinqa": {"name": "ConvFinQA", "metric": "numeric_em", "higherIsBetter": True},
    "tatqa": {"name": "TAT-QA (arithmetic)", "metric": "numeric_em", "higherIsBetter": True},
    "tool_use": {"name": "Candela tool use", "metric": "tool_choice_f1", "higherIsBetter": True},
    "heldout_loss": {"name": "Held-out loss (d0.1 valid)", "metric": "loss", "higherIsBetter": False},
}
BATCH = {"short": 16, "long": 4}


@dataclass
class Engine:
    model: Any
    tokenizer: Any
    family: str
    lease: gpu_lease.Lease
    guard: resources.ResourceGuard

    def prompt_ids(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> list[int]:
        kwargs: dict[str, Any] = {"add_generation_prompt": True, "enable_thinking": False, "tokenize": False}
        if tools:
            kwargs["tools"] = tools
        text = self.tokenizer.apply_chat_template(messages, **kwargs)
        return self.tokenizer.encode(text, add_special_tokens=False)

    def generate(self, prompts: list[list[int]], max_tokens: int, batch: int) -> list[str]:
        from mlx_lm.generate import batch_generate

        hf = getattr(self.tokenizer, "_tokenizer", self.tokenizer)
        out: list[str] = []
        for i in range(0, len(prompts), batch):
            self.lease.yield_if_needed()
            decision = self.guard.check_step(0)
            if not decision.ok:
                _log.warning("memory pressure during eval, waiting", reason=decision.reason)
                resources.release_mlx_memory()
                self.guard.wait_for_recovery(recover_sec=60)
            res = batch_generate(
                self.model,
                self.tokenizer,
                prompts[i : i + batch],
                max_tokens=max_tokens,
                return_token_ids=True,
                prefill_batch_size=min(batch, 8),
                completion_batch_size=batch,
            )
            out.extend(hf.decode(ids, skip_special_tokens=False) for ids in res.token_ids or [])
            mx.clear_cache()
        return out


def _neighbourly_wired_limit() -> None:
    """mlx-lm wires the recommended working set (≈18 GB here) during generation; on a shared machine we keep MLX at
    the default (no wiring) so the owner's processes can still reclaim memory."""
    import mlx_lm.generate as gen

    gen.maybe_set_recommended_wired_limit = lambda *a, **k: None  # type: ignore[assignment]


def classification(engine: Engine, suite: str, n: int, limit: int | None) -> dict[str, Any]:
    items = datasets.load(suite, limit or n)
    prompts = [engine.prompt_ids([{"role": "user", "content": it.prompt}]) for it in items]
    texts = engine.generate(prompts, max_tokens=8, batch=BATCH["short"])
    preds = [metrics.parse_label(t, it.choices) for t, it in zip(texts, items, strict=True)]
    golds = [it.answer for it in items]
    average = "macro" if suite == "fpb" else "weighted"
    scores = metrics.classification_scores(golds, preds, average)
    samples = [
        {"prompt": it.prompt[-300:], "output": t, "gold": it.answer, "pred": p}
        for it, t, p in list(zip(items, texts, preds, strict=True))[:5]
    ]
    return {"value": scores["f1"], "n": len(items), "details": scores, "samples": samples}


def numeric(engine: Engine, suite: str, n: int, limit: int | None) -> dict[str, Any]:
    items = datasets.load(suite, limit or n)
    prompts = [engine.prompt_ids([{"role": "user", "content": it.prompt}]) for it in items]
    texts = engine.generate(prompts, max_tokens=160, batch=BATCH["long"])
    hits = 0
    unparsed = 0
    samples = []
    for it, t in zip(items, texts, strict=True):
        pred = metrics.parse_numeric(t)
        gold = metrics.gold_number(it.answer)
        ok = metrics.numeric_match(pred, gold)
        hits += ok
        unparsed += pred is None
        if len(samples) < 5:
            samples.append(
                {"prompt": it.prompt[-300:], "output": t[-400:], "gold": it.answer, "pred": pred, "ok": ok}
            )
    return {
        "value": hits / max(len(items), 1),
        "n": len(items),
        "details": {"unparsed": unparsed / max(len(items), 1)},
        "samples": samples,
    }


def tool_use(engine: Engine, n: int, limit: int | None) -> dict[str, Any]:
    items = datasets.load("tool_use", limit or n)
    if not items:
        return {
            "value": None,
            "n": 0,
            "details": {"error": "no held-out traces; run lab traces generate --split heldout"},
        }
    schemas = {t["function"]["name"]: t["function"]["parameters"] for t in config.tools_schema()}
    call_prompts, call_gold, ans_prompts, ans_ctx = [], [], [], []
    for it in items:
        row = it.extra
        msgs, tools = row["messages"], row["tools"]
        for k, m in enumerate(msgs):
            if m["role"] != "assistant":
                continue
            prev = msgs[k - 1]["role"]
            if prev == "user":
                call_prompts.append(engine.prompt_ids(msgs[:k], tools))
                call_gold.append([tc["function"]["name"] for tc in m.get("tool_calls") or []])
            if not m.get("tool_calls") and prev == "tool":
                ans_prompts.append(engine.prompt_ids(msgs[:k], tools))
                ctx = [x["content"] for x in msgs[:k] if x["role"] == "tool"]
                ans_ctx.append(ctx)
    call_texts = engine.generate(call_prompts, max_tokens=160, batch=BATCH["long"])
    tp = fp = fn = 0
    valid_args = total_args = malformed = 0
    no_tool_correct = no_tool_total = 0
    samples = []
    for text, gold in zip(call_texts, call_gold, strict=True):
        calls, bad = metrics.extract_tool_calls(text, engine.family)
        malformed += bad
        pred = [c["name"] for c in calls]
        a, b, c = metrics.tool_choice(gold, pred)
        tp, fp, fn = tp + a, fp + b, fn + c
        if not gold:
            no_tool_total += 1
            no_tool_correct += not pred
        for call in calls:
            total_args += 1
            if call["name"] in schemas and not validate_arguments(schemas[call["name"]], call["arguments"]):
                valid_args += 1
        if len(samples) < 4:
            samples.append({"gold": gold, "pred": pred, "output": text[:400]})
    ans_texts = engine.generate(ans_prompts, max_tokens=384, batch=BATCH["long"])
    rates, ungrounded_examples = [], []
    for text, ctx in zip(ans_texts, ans_ctx, strict=True):
        rep = grounding_report(metrics.strip_reasoning(text), ctx)
        rates.append(rep["rate"])
        if rep["ungrounded"] and len(ungrounded_examples) < 5:
            ungrounded_examples.append(rep["ungrounded"][:5])
    choice = metrics.prf(tp, fp, fn)
    return {
        "value": choice["f1"],
        "n": len(items),
        "details": {
            "toolChoicePrecision": choice["precision"],
            "toolChoiceRecall": choice["recall"],
            "toolChoiceF1": choice["f1"],
            "argumentValidity": valid_args / total_args if total_args else 0.0,
            "malformedCalls": malformed,
            "noToolAccuracy": no_tool_correct / no_tool_total if no_tool_total else None,
            "groundingRate": sum(rates) / len(rates) if rates else None,
            "callTurns": len(call_prompts),
            "answerTurns": len(ans_prompts),
            "ungroundedExamples": ungrounded_examples,
        },
        "samples": samples,
    }


def heldout_loss(engine: Engine, n: int, limit: int | None, version: str = "d0.1") -> dict[str, Any]:
    from candela_lab.train import data as tdata
    from candela_lab.train.loss import make_loss, to_float

    path = PROCESSED_DIR / version / "valid.jsonl"
    if not path.exists():
        return {"value": None, "n": 0, "details": {"error": f"{path} missing; run lab data build"}}
    rows = list(read_jsonl(path))[: limit or n]
    encoded, _ = tdata.encode_all(engine.tokenizer, rows, 2048)
    loss_fn = make_loss(engine.model)
    total, toks = 0.0, 0.0
    for enc in encoded:
        engine.lease.yield_if_needed()
        tokens = mx.array(enc.tokens[None, :])
        positions = mx.arange(enc.prompt_len - 1, len(enc.tokens) - 1)
        loss, cnt = loss_fn(engine.model, tokens, positions)
        mx.eval(loss, cnt)
        total += to_float(loss) * to_float(cnt)
        toks += to_float(cnt)
        mx.clear_cache()
    return {"value": total / max(toks, 1.0), "n": len(encoded), "details": {"tokens": int(toks)}}


RUNNERS: dict[str, Callable[[Engine, int, int | None], dict[str, Any]]] = {
    "fpb": lambda e, n, lim: classification(e, "fpb", n, lim),
    "fiqa_sa": lambda e, n, lim: classification(e, "fiqa_sa", n, lim),
    "headlines": lambda e, n, lim: classification(e, "headlines", n, lim),
    "finqa": lambda e, n, lim: numeric(e, "finqa", n, lim),
    "convfinqa": lambda e, n, lim: numeric(e, "convfinqa", n, lim),
    "tatqa": lambda e, n, lim: numeric(e, "tatqa", n, lim),
    "tool_use": tool_use,
    "heldout_loss": heldout_loss,
}


def run(
    model_id: str,
    adapter: Path | None = None,
    suites: list[str] | None = None,
    mode: str = "fast",
    label: str | None = None,
    limit: int | None = None,
) -> Path:
    from mlx_lm import load

    spec = config.model(model_id)
    chosen = suites or SUITES
    sizes = SIZES[mode]
    guard = resources.ResourceGuard(budget_gb=spec.inference_budget_gb)
    _neighbourly_wired_limit()
    started = time.time()
    with gpu_lease.Lease("lab-eval", purpose=f"eval {label or spec.id}") as lease:
        guard.wait_for_headroom(what=f"eval {spec.id}")
        resources.apply_process_limits(spec.inference_budget_gb, cache_gb=1.0)
        mx.reset_peak_memory()
        loaded = load(spec.base_path(), adapter_path=str(adapter) if adapter else None)
        model, tokenizer = loaded[0], loaded[1]
        engine = Engine(model, tokenizer, spec.family, lease, guard)
        results: dict[str, Any] = {}
        for suite in chosen:
            t0 = time.time()
            _log.info("suite start", suite=suite, n=limit or sizes[suite])
            res = RUNNERS[suite](engine, sizes[suite], limit)
            res["seconds"] = round(time.time() - t0, 1)
            res.update({k: v for k, v in SUITE_INFO[suite].items()})
            results[suite] = res
            _log.info("suite done", suite=suite, value=res["value"], n=res["n"], seconds=res["seconds"])
        peak = mx.get_peak_memory() / 1e9
        del model, engine
        resources.release_mlx_memory()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_id = label or spec.id
    payload = {
        "reportId": report_id,
        "modelId": spec.id,
        "baseModel": spec.upstream,
        "basePath": spec.base_path(),
        "adapter": str(adapter) if adapter else None,
        "mode": mode,
        "limit": limit,
        "datasetVersion": "d0.1",
        "evalSeed": datasets.EVAL_SEED,
        "decoding": {"temperature": 0.0, "thinking": False},
        "evaluatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "durationSec": round(time.time() - started, 1),
        "peakMemGb": round(peak, 2),
        "machine": f"{mx.device_info().get('device_name')} · {platform.machine()}",
        "suites": results,
    }
    out = REPORTS_DIR / "eval" / f"{report_id}-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    out.with_suffix(".md").write_text(report.markdown(payload))
    _log.info("report written", path=str(out), seconds=payload["durationSec"], peak_gb=payload["peakMemGb"])
    return out
