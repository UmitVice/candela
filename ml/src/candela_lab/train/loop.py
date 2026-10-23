import gc
import json
import random
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import mlx.core as mx
import mlx.optimizers as optim
from mlx import nn
from mlx.nn.utils import value_and_grad as nn_value_and_grad
from mlx.utils import tree_flatten, tree_map, tree_unflatten
from rich.console import Console
from rich.table import Table

from candela_lab import config, gpu_lease, log, resources
from candela_lab.data.common import read_jsonl
from candela_lab.paths import ML_DIR, PROCESSED_DIR, RUNS_DIR
from candela_lab.train import data as tdata
from candela_lab.train import deltas
from candela_lab.train.loss import checkpoint_layers, make_loss, to_float

_log = log.get("train")


@dataclass
class TrainConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def model_id(self) -> str:
        return self.raw["model"]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass
class RunState:
    step: int = 0
    cursor: int = 0
    epoch: int = 0
    trained_tokens: int = 0
    elapsed_sec: float = 0.0
    pauses: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[int] = field(default_factory=list)
    status: str = "running"
    started_at: str = ""
    finished_at: str | None = None
    peak_mem_gb: float = 0.0


class Paused(Exception):
    def __init__(self, step: int, reason: str) -> None:
        super().__init__(reason)
        self.step = step
        self.reason = reason


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_config(path: Path) -> TrainConfig:
    p = path if path.is_absolute() else (ML_DIR / path if (ML_DIR / path).exists() else path)
    return TrainConfig(config.load_yaml(p), p)


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _append_metric(rd: Path, row: dict[str, Any]) -> None:
    with (rd / "metrics.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def lora_settings(cfg: TrainConfig, spec: config.ModelSpec) -> dict[str, Any]:
    return {**spec.lora, **(cfg.get("lora") or {})}


def schedule(cfg: TrainConfig, iters: int) -> Any:
    opt = cfg.get("optimizer", {})
    lr = float(opt.get("learningRate", 1e-4))
    warmup = int(opt.get("warmup", max(1, iters // 20)))
    floor = lr * float(opt.get("minLrRatio", 0.1))
    decay = optim.cosine_decay(lr, max(iters - warmup, 1), floor)
    if warmup <= 0:
        return decay
    return optim.join_schedules([optim.linear_schedule(lr * 0.05, lr, warmup), decay], [warmup])


def load_samples(cfg: TrainConfig, split: str) -> list[dict[str, Any]]:
    data_cfg = cfg.get("data", {})
    version = data_cfg.get("version", "d0.1")
    rows = list(read_jsonl(PROCESSED_DIR / version / f"{split}.jsonl"))
    buckets = data_cfg.get("sources")
    if buckets:
        rows = [r for r in rows if r["meta"]["source"] in buckets]
    limit = data_cfg.get("trainSubset" if split == "train" else "validSubset")
    if limit:
        rng = random.Random(f"{cfg.get('seed', 7)}:{split}")
        rng.shuffle(rows)
        rows = rows[: int(limit)]
    return rows


def build_model(spec: config.ModelSpec, lora: dict[str, Any], grad_ckpt: bool) -> tuple[nn.Module, Any]:
    from mlx_lm import load
    from mlx_lm.tuner.utils import linear_to_lora_layers

    loaded = load(spec.base_path())
    model, tokenizer = loaded[0], loaded[1]
    model.freeze()
    linear_to_lora_layers(
        model,
        int(lora["numLayers"]),
        {
            "rank": int(lora["rank"]),
            "scale": float(lora["scale"]),
            "dropout": float(lora["dropout"]),
            "keys": lora["keys"],
        },
    )
    if grad_ckpt:
        checkpoint_layers(model)
    return model, tokenizer


def _total_parameters(model: nn.Module) -> int:
    from mlx_lm.utils import get_total_parameters

    return int(get_total_parameters(model))


def save_adapter(model: nn.Module, target: Path, lora: dict[str, Any], spec: config.ModelSpec) -> None:
    target.mkdir(parents=True, exist_ok=True)
    weights = dict(tree_flatten(model.trainable_parameters()))
    mx.save_safetensors(str(target / "adapters.safetensors"), weights)
    _write_json(
        target / "adapter_config.json",
        {
            "fine_tune_type": "lora",
            "num_layers": int(lora["numLayers"]),
            "lora_parameters": {
                "rank": int(lora["rank"]),
                "scale": float(lora["scale"]),
                "dropout": float(lora["dropout"]),
                "keys": list(lora["keys"]),
            },
            "base_model": spec.id,
            "base_upstream": spec.upstream,
        },
    )


def save_checkpoint(
    rd: Path,
    model: nn.Module,
    optimizer: optim.Optimizer,
    state: RunState,
    lora: dict[str, Any],
    spec: config.ModelSpec,
) -> Path:
    ck = rd / "checkpoints" / f"step-{state.step:06d}"
    save_adapter(model, ck, lora, spec)
    opt_state = dict(tree_flatten(optimizer.state))
    mx.save_safetensors(
        str(ck / "optimizer.safetensors"), {k: v for k, v in opt_state.items() if isinstance(v, mx.array)}
    )
    _write_json(ck / "state.json", state.__dict__)
    latest = rd / "adapter"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(ck, latest, ignore=shutil.ignore_patterns("optimizer.safetensors", "state.json"))
    _write_json(rd / "state.json", state.__dict__)
    return ck


def latest_checkpoint(rd: Path) -> Path | None:
    cks = sorted((rd / "checkpoints").glob("step-*")) if (rd / "checkpoints").exists() else []
    return cks[-1] if cks else None


def evaluate(model: nn.Module, loss_fn: Any, samples: list[tdata.Encoded]) -> float:
    total, toks = 0.0, 0.0
    for enc in samples:
        tokens = mx.array(enc.tokens[None, :])
        positions = mx.arange(enc.prompt_len - 1, len(enc.tokens) - 1)
        loss, n = loss_fn(model, tokens, positions)
        mx.eval(loss, n)
        total += to_float(loss) * to_float(n)
        toks += to_float(n)
        mx.clear_cache()
    return total / max(toks, 1.0)


def session(
    cfg: TrainConfig,
    run_id: str,
    state: RunState,
    guard: resources.ResourceGuard,
    lease: gpu_lease.Lease,
    probe: bool,
    resume_from: Path | None,
) -> RunState:
    spec = config.model(cfg.model_id)
    lora = lora_settings(cfg, spec)
    rd = run_dir(run_id)
    iters = int(cfg.get("iters", 100))
    accum = int(cfg.get("gradAccumulation", 8))
    max_len = int(cfg.get("maxSeqLength", 2048))
    save_every = int(cfg.get("saveEvery", 50))
    eval_every = int(cfg.get("evalEvery", 50))
    report_every = int(cfg.get("reportEvery", 1))
    clip = float(cfg.get("optimizer", {}).get("gradClip", 1.0))
    mem = cfg.get("memory", {})
    budget = float(mem.get("budgetGb", spec.train_budget_gb))

    guard.wait_for_headroom(what=f"train {run_id}")
    resources.apply_process_limits(budget, cache_gb=float(mem.get("cacheGb", 1.0)))
    mx.random.seed(int(cfg.get("seed", 7)))
    mx.reset_peak_memory()
    load_t = time.time()
    model, tokenizer = build_model(spec, lora, bool(cfg.get("gradCheckpoint", True)))
    _log.info(
        "model loaded",
        base=spec.base_path(),
        seconds=round(time.time() - load_t, 1),
        trainable=deltas.trainable_parameters(model),
        layers=deltas.adapted_layers(model)[:1] + deltas.adapted_layers(model)[-1:],
        active_gb=round(mx.get_active_memory() / 1e9, 2),
    )
    if resume_from is not None:
        model.load_weights(str(resume_from / "adapters.safetensors"), strict=False)
    load_peak = mx.get_peak_memory() / 1e9
    mx.reset_peak_memory()

    train_rows = load_samples(cfg, "train")
    train, dropped = tdata.encode_all(tokenizer, train_rows, max_len)
    if probe:
        train.sort(key=lambda e: len(e.tokens), reverse=True)
    else:
        random.Random(f"{cfg.get('seed', 7)}:order").shuffle(train)
    valid, _ = tdata.encode_all(tokenizer, load_samples(cfg, "valid"), max_len)
    valid = valid[: int(cfg.get("validBatches", 32))]
    _log.info("data encoded", train=len(train), valid=len(valid), dropped=dropped)
    if not state.started_at:
        _write_json(
            rd / "run.json",
            {
                "runId": run_id,
                "config": cfg.raw,
                "configPath": str(cfg.path),
                "trainExamples": len(train),
                "validExamples": len(valid),
                "trainableParameters": deltas.trainable_parameters(model),
                "layerIndices": deltas.adapted_layers(model),
                "modules": deltas.adapted_modules(model),
                "lora": lora,
                "device": mx.device_info().get("device_name"),
                "memoryLimitGb": budget,
                "loadPeakGb": round(load_peak, 3),
                "weightsGb": round(mx.get_active_memory() / 1e9, 3),
                "totalParameters": _total_parameters(model),
            },
        )

    sched = schedule(cfg, iters)
    opt_cfg = cfg.get("optimizer", {})
    optimizer = optim.AdamW(learning_rate=sched, weight_decay=float(opt_cfg.get("weightDecay", 0.0)))
    if resume_from is not None and (resume_from / "optimizer.safetensors").exists():
        optimizer.init(model.trainable_parameters())
        restored = cast(dict[str, mx.array], mx.load(str(resume_from / "optimizer.safetensors")))
        optimizer.state = tree_unflatten(list(restored.items()))
    loss_fn = make_loss(model, chunk=int(cfg.get("headChunk", 256)))
    value_and_grad = nn_value_and_grad(model, loss_fn)

    def release() -> None:
        save_checkpoint(rd, model, optimizer, state, lora, spec)

    if not state.started_at:
        state.started_at = now()
        if not probe:
            norms = deltas.lora_delta_norms(model, spec.architecture["layers"])
            _append_metric(rd, {"type": "deltas", "step": 0, "norms": norms})
            state.checkpoints.append(0)

    num_layers = int(spec.architecture["layers"])
    model.train()
    window_tokens, window_time, window_loss, window_n = 0, 0.0, 0.0, 0
    while state.step < iters:
        waited = lease.yield_if_needed(on_long_wait=release)
        if waited > 0:
            _append_metric(
                rd,
                {
                    "type": "pause",
                    "step": state.step,
                    "reason": "gpu lease: higher priority",
                    "at": now(),
                    "waitedSec": waited,
                },
            )
            state.pauses.append({"step": state.step, "reason": "gpu lease: higher priority", "at": now()})
        decision = guard.check_step(state.step + 1)
        if not decision.ok:
            if not probe:
                save_checkpoint(rd, model, optimizer, state, lora, spec)
            raise Paused(state.step, decision.reason)
        tic = time.perf_counter()
        grads_acc = None
        step_loss, step_tokens = 0.0, 0
        for _ in range(accum):
            if state.cursor >= len(train):
                state.cursor = 0
                state.epoch += 1
            enc = train[state.cursor]
            state.cursor += 1
            tokens = mx.array(enc.tokens[None, :])
            positions = mx.arange(enc.prompt_len - 1, len(enc.tokens) - 1)
            (loss, _ntoks), grads = value_and_grad(model, tokens, positions)
            grads_acc = grads if grads_acc is None else tree_map(lambda a, b: a + b, grads_acc, grads)
            mx.eval(loss, grads_acc)
            step_loss += to_float(loss)
            step_tokens += len(enc.tokens)
        grads_avg = tree_map(lambda g: g / accum, grads_acc)
        if clip > 0:
            grads_avg, _ = optim.clip_grad_norm(grads_avg, clip)
        optimizer.update(model, grads_avg)
        mx.eval(model.trainable_parameters(), optimizer.state)
        del grads_acc, grads_avg
        mx.clear_cache()
        dt = time.perf_counter() - tic
        state.step += 1
        state.trained_tokens += step_tokens
        state.elapsed_sec += dt
        peak = mx.get_peak_memory() / 1e9
        state.peak_mem_gb = max(state.peak_mem_gb, peak)
        window_tokens += step_tokens
        window_time += dt
        window_loss += step_loss / accum
        window_n += 1
        if state.step % report_every == 0 or state.step == iters:
            lr = to_float(optimizer.learning_rate) if isinstance(optimizer.learning_rate, mx.array) else 0.0
            row = {
                "type": "train",
                "step": state.step,
                "loss": round(window_loss / window_n, 5),
                "lr": lr,
                "tokensPerSec": round(window_tokens / max(window_time, 1e-6), 1),
                "peakMemGb": round(peak, 3),
                "elapsedSec": round(state.elapsed_sec, 1),
            }
            _append_metric(rd, row)
            _log.info("step", **{k: v for k, v in row.items() if k != "type"}, epoch=state.epoch)
            window_tokens, window_time, window_loss, window_n = 0, 0.0, 0.0, 0
        if valid and not probe and (state.step % eval_every == 0 or state.step == iters):
            model.eval()
            vloss = evaluate(model, loss_fn, valid)
            model.train()
            _append_metric(rd, {"type": "valid", "step": state.step, "loss": round(vloss, 5)})
            _log.info("validation", step=state.step, loss=round(vloss, 4))
        if not probe and (state.step % save_every == 0 or state.step == iters):
            norms = deltas.lora_delta_norms(model, num_layers)
            _append_metric(rd, {"type": "deltas", "step": state.step, "norms": norms})
            state.checkpoints.append(state.step)
            save_checkpoint(rd, model, optimizer, state, lora, spec)
    state.status = "completed"
    state.finished_at = now()
    if not probe:
        save_checkpoint(rd, model, optimizer, state, lora, spec)
    _write_json(rd / "state.json", state.__dict__)
    return state


def _new_run_id(cfg_path: Path) -> str:
    return f"{cfg_path.stem}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


def run(
    config_path: Path,
    run_id: str | None = None,
    iters: int | None = None,
    simulate_pause_at: list[int] | None = None,
    simulate_recover_sec: float = 30.0,
    probe: bool = False,
) -> RunState:
    cfg = load_config(config_path)
    if iters is not None:
        cfg.raw["iters"] = iters
    run_id = run_id or _new_run_id(cfg.path)
    rd = run_dir(run_id)
    rd.mkdir(parents=True, exist_ok=True)
    handler = log.add_json_file(rd / "log.jsonl")
    state_path = rd / "state.json"
    state = RunState(**json.loads(state_path.read_text())) if state_path.exists() else RunState()
    if state.status == "completed":
        _log.info("run already completed", run_id=run_id)
        return state
    _write_json(rd / "config.json", {**cfg.raw, "simulatePauseAt": simulate_pause_at or [], "probe": probe})
    spec = config.model(cfg.model_id)
    budget = float(cfg.get("memory", {}).get("budgetGb", spec.train_budget_gb))
    guard = resources.ResourceGuard(budget_gb=budget, pause_file=rd / "PAUSE")
    guard.install_signal_handler()
    guard.simulate_pause_at(simulate_pause_at or [])
    holder = "lab-train"
    try:
        with gpu_lease.Lease(
            holder, purpose=f"{'probe' if probe else 'train'} {run_id}", state="waiting"
        ) as lease:
            guard.wait_for_headroom(what=f"train {run_id}")
            lease.activate()
            resume = latest_checkpoint(rd) if state.step > 0 else None
            while True:
                paused: tuple[int, str] | None = None
                try:
                    state = session(cfg, run_id, state, guard, lease, probe, resume)
                    break
                except Paused as p:
                    paused = (p.step, p.reason)
                # Waiting outside the except block lets the traceback (and the session's model) be freed first.
                step, reason = paused
                event: dict[str, Any] = {"step": step, "reason": reason, "at": now()}
                _log.warning("paused", run_id=run_id, step=step, reason=reason)
                state.status = "paused"
                _append_metric(rd, {"type": "pause", **event})
                gc.collect()
                resources.release_mlx_memory()
                _log.info("memory released", active_gb=round(mx.get_active_memory() / 1e9, 2))
                hold = simulate_recover_sec if reason == "simulated pause" else None
                waited = guard.wait_for_recovery(recover_sec=hold)
                event["resumedAt"] = now()
                event["waitedSec"] = round(waited, 1)
                state.pauses.append(event)
                _append_metric(
                    rd,
                    {
                        "type": "resume",
                        "step": step,
                        "at": event["resumedAt"],
                        "waitedSec": event["waitedSec"],
                    },
                )
                state.status = "running"
                _write_json(state_path, state.__dict__)
                resume = None if probe else latest_checkpoint(rd)
    except Exception:
        state.status = "failed"
        _write_json(state_path, state.__dict__)
        _log.error("run failed", run_id=run_id, exc_info=True)
        raise
    finally:
        log.remove_handler(handler)
    _log.info(
        "run finished",
        run_id=run_id,
        steps=state.step,
        peak_mem_gb=round(state.peak_mem_gb, 2),
        tokens=state.trained_tokens,
        tokens_per_sec=round(state.trained_tokens / max(state.elapsed_sec, 1e-6), 1),
        pauses=len(state.pauses),
    )
    if not probe:
        from candela_lab import observatory

        observatory.export_run(run_id)
    return state


def resume(run_id: str) -> RunState:
    rd = run_dir(run_id)
    cfg_raw = json.loads((rd / "config.json").read_text())
    probe = bool(cfg_raw.pop("probe", False))
    cfg_raw.pop("simulatePauseAt", None)
    tmp = rd / "resume-config.yaml"
    import yaml

    tmp.write_text(yaml.safe_dump(cfg_raw))
    return run(tmp, run_id=run_id, probe=probe)


def status(run_id: str | None) -> None:
    console = Console()
    runs = (
        [run_dir(run_id)] if run_id else sorted(p for p in RUNS_DIR.glob("*") if (p / "state.json").exists())
    )
    table = Table(title="Candela Lab runs")
    for col in ("run", "status", "step", "tokens", "peak GB", "tok/s", "pauses", "last loss"):
        table.add_column(col)
    for rd in runs:
        st = json.loads((rd / "state.json").read_text())
        last = None
        if (rd / "metrics.jsonl").exists():
            for line in (rd / "metrics.jsonl").read_text().splitlines():
                row = json.loads(line)
                if row.get("type") == "train":
                    last = row["loss"]
        tps = st["trained_tokens"] / st["elapsed_sec"] if st.get("elapsed_sec") else 0
        table.add_row(
            rd.name,
            st["status"],
            str(st["step"]),
            str(st["trained_tokens"]),
            f"{st.get('peak_mem_gb', 0):.2f}",
            f"{tps:.0f}",
            str(len(st.get("pauses", []))),
            "" if last is None else f"{last:.4f}",
        )
    console.print(table)
