import json
import math
import os
import signal
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, cast

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten, tree_map

from candela_spark import log, paths
from candela_spark.data import config as data_config
from candela_spark.data.loader import Cursor, MixtureLoader, validation_windows
from candela_spark.model.config import PRESETS, ModelConfig
from candela_spark.model.transformer import SparkLM
from candela_spark.ops import resources, status
from candela_spark.ops.lease import GpuLease
from candela_spark.tokenizer.train import frozen_hash
from candela_spark.train import checkpoint
from candela_spark.train.config import RunConfig
from candela_spark.train.optim import SparkOptimizer
from candela_spark.train.schedule import WSD

_log = log.get("trainer")
OVERRIDE_FILE = paths.SPARK_STATE / "override.json"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_override() -> dict[str, Any]:
    try:
        raw = json.loads(OVERRIDE_FILE.read_text())
        return raw if isinstance(raw, dict) else {}
    except OSError, ValueError:
        return {}


def token_losses(model: SparkLM, x: mx.array, y: mx.array) -> mx.array:
    return nn.losses.cross_entropy(model(x).astype(mx.float32), y, reduction="none")


def evaluate(model: SparkLM, windows: dict[str, np.ndarray], batch: int) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {"bf16": {}, "int4": {}}
    was = model.qat
    for mode, qat in (("bf16", False), ("int4", True)):
        model.set_qat(qat)
        for name, arr in windows.items():
            total, count = 0.0, 0
            for i in range(0, len(arr), batch):
                chunk = mx.array(arr[i : i + batch])
                losses = token_losses(model, chunk[:, :-1], chunk[:, 1:])
                total += float(losses.sum())
                count += losses.size
            out[mode][name] = total / max(1, count)
    model.set_qat(was)
    return out


class Trainer:
    def __init__(self, cfg: RunConfig, force_offline: bool = True) -> None:
        if force_offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["HF_DATASETS_OFFLINE"] = "1"
        self.cfg = cfg
        self.mcfg: ModelConfig = PRESETS[cfg.preset]
        self.dcfg = data_config.load(cfg.data_version)
        self.run_dir = cfg.run_dir
        self.ckpt_dir = self.run_dir / "checkpoints"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.metrics = (self.run_dir / "metrics.jsonl").open("a", buffering=1)
        self.events = (self.run_dir / "events.jsonl").open("a", buffering=1)
        self.stop_requested = False
        self.stop_signal = ""
        self.guard = resources.ResourceGuard(cfg.memory_budget_gb)
        self.lease = GpuLease(cfg.lease_holder, cfg.lease_priority, f"spark pretraining ({cfg.run_id})")
        self.schedule = WSD(cfg.warmup_steps)
        self.step = 0
        self.tokens = 0
        self.started_at = now_iso()
        self.elapsed_train_sec = 0.0
        self.last_val: dict[str, Any] | None = None
        self.last_train: dict[str, Any] = {}
        self.pause_reason: str | None = None
        self.milestones: list[dict[str, Any]] = []
        self.next_milestone_tokens = cfg.milestone_every_tokens
        self._env_checked_at = 0.0
        self._env_reason: str | None = None

    def event(self, kind: str, **fields: Any) -> None:
        self.events.write(json.dumps({"type": kind, "at": now_iso(), "step": self.step, **fields}) + "\n")

    def _signal(self, signum: int, _frame: object) -> None:
        self.stop_requested = True
        self.stop_signal = signal.Signals(signum).name

    def _state(self) -> dict[str, Any]:
        return {
            "runId": self.cfg.run_id,
            "tokens": self.tokens,
            "cursor": self.loader.cursor.to_dict(),
            "seed": self.cfg.seed,
            "rngSeed": self.cfg.seed + self.step,
            "schedule": {
                "warmupSteps": self.schedule.warmup_steps,
                "decayStart": self.schedule.decay_start,
                "decaySteps": self.schedule.decay_steps,
            },
            "elapsedTrainSec": self.elapsed_train_sec,
            "runConfig": self.cfg.to_dict(),
            "modelConfig": self.mcfg.to_dict(),
            "modelFingerprint": self.mcfg.fingerprint(),
            "tokenizerSha256": self.tokenizer_hash,
            "dataVersion": self.dcfg.version,
            "lastVal": self.last_val,
            "milestones": self.milestones,
            "forkOrigin": self.fork_origin,
            "savedAt": now_iso(),
        }

    def save(self, reason: str, milestone: bool = False) -> Path:
        t0 = time.time()
        mx.eval(self.model.parameters(), self.opt.state)
        path = checkpoint.save(
            self.ckpt_dir,
            self.step,
            self.model.parameters(),
            self.opt.state,
            self._state(),
            keep_last=self.cfg.keep_last,
            milestone=milestone,
        )
        self.last_ckpt_at = time.time()
        self.event(
            "checkpoint", reason=reason, name=path.name, milestone=milestone, sec=round(time.time() - t0, 2)
        )
        _log.info("checkpoint", reason=reason, step=self.step, tokens=self.tokens, name=path.name)
        return path

    def _restore(self) -> None:
        found = checkpoint.latest_valid(self.ckpt_dir)
        source = "own"
        if found is None and self.cfg.fork_from:
            parent = paths.RUNS / self.cfg.fork_from / "checkpoints"
            name = f"step-{self.cfg.fork_step:08d}" if self.cfg.fork_step else None
            found = parent / name if name else checkpoint.latest_valid(parent)
            if found is None or not checkpoint.verify(found):
                raise RuntimeError(f"fork source checkpoint missing or corrupt: {self.cfg.fork_from}")
            source = "fork"
        if found is None:
            self.loader = MixtureLoader(self.dcfg, self.cfg.seq_len, self.cfg.seed)
            return
        params, opt_state, state = checkpoint.load(found)
        if state["modelFingerprint"] != self.mcfg.fingerprint():
            raise RuntimeError("checkpoint model config differs from the preset")
        if state["tokenizerSha256"] != self.tokenizer_hash:
            raise RuntimeError("checkpoint tokenizer differs from the frozen tokenizer")
        self.model.load_weights(list(params.items()), strict=True)
        self.opt.inner.init(self.model.trainable_parameters())
        if opt_state is not None:
            self.opt.state = opt_state
        self.step = int(state["step"])
        self.tokens = int(state["tokens"])
        self.elapsed_train_sec = float(state.get("elapsedTrainSec", 0.0))
        self.last_val = state.get("lastVal")
        self.milestones = list(state.get("milestones", [])) if source == "own" else []
        # Nothing stochastic runs after init (no dropout; data order is the cursor), so a step seed suffices.
        mx.random.seed(self.cfg.seed + self.step)
        self.loader = MixtureLoader(
            self.dcfg, self.cfg.seq_len, self.cfg.seed, Cursor.from_dict(state["cursor"])
        )
        if source == "fork":
            self.schedule = WSD(
                self.cfg.warmup_steps, decay_start=self.step, decay_steps=self.cfg.decay_steps
            )
            self.fork_origin = {"run": self.cfg.fork_from, "step": self.step, "tokens": self.tokens}
        else:
            sch = state["schedule"]
            self.schedule = WSD(sch["warmupSteps"], sch["decayStart"], sch["decaySteps"])
            self.fork_origin = state.get("forkOrigin")
        while self.next_milestone_tokens <= self.tokens:
            self.next_milestone_tokens += self.cfg.milestone_every_tokens
        self.event("resume", source=source, checkpoint=found.name, tokens=self.tokens)
        _log.info("resumed", source=source, checkpoint=str(found.name), step=self.step, tokens=self.tokens)

    def _build(self) -> None:
        self.tokenizer_hash = frozen_hash()
        mx.random.seed(self.cfg.seed)
        self.model = SparkLM(self.mcfg)
        self.model.set_qat(self.mcfg.quant.start_step == 0)
        mx.eval(self.model.parameters())
        self.opt = SparkOptimizer(self.cfg.optim)
        self.fork_origin: dict[str, Any] | None = None
        self._restore()
        self.opt.inner.init(self.model.trainable_parameters())
        self.opt.set_lr_mult(self.schedule.mult(self.step))
        mx.eval(self.model.parameters(), self.opt.state)
        model, opt = self.model, self.opt

        def loss_fn(m: SparkLM, x: mx.array, y: mx.array) -> mx.array:
            return nn.losses.cross_entropy(m(x).astype(mx.float32), y, reduction="mean")

        grad_fn = nn.value_and_grad(model, loss_fn)

        @partial(mx.compile, inputs=[model.state], outputs=[model.state])
        def micro(x: mx.array, y: mx.array) -> tuple[mx.array, Any]:
            return grad_fn(model, x, y)

        @partial(mx.compile, inputs=[model.state, opt.state], outputs=[model.state, opt.state])
        def apply(grads: Any) -> mx.array:
            clipped, norm = optim.clip_grad_norm(grads, self.cfg.optim.grad_clip)
            opt.inner.update(model, clipped)
            return norm

        self.micro = micro
        self.apply = apply
        self.val_windows = validation_windows(self.dcfg, self.cfg.seq_len, self.cfg.eval_windows_per_source)

    def _gate(self) -> bool:
        """Wait at the step boundary while anything outranks us. Returns False if a stop was requested."""
        waited_since: float | None = None
        released = False
        healthy_since: float | None = None
        reason = None
        last_override = 0.0
        override: dict[str, Any] = {}
        while not self.stop_requested:
            now = time.time()
            if now - last_override > 5 or waited_since is not None:
                override = read_override()
                last_override = now
            # Subprocess-based checks are cached for a few seconds; the lease check below runs every step.
            if waited_since is not None or now - self._env_checked_at > 10:
                self._env_checked_at = now
                self._env_reason = None
                if resources.on_battery(override.get("simulateBattery")):
                    self._env_reason = "on battery power"
                elif resources.thermal_serious():
                    self._env_reason = "thermal pressure"
                elif foreign := resources.foreign_training():
                    self._env_reason = f"external training running ({foreign[0]})"
            reason = None
            if override.get("pause"):
                reason = "paused by override"
            elif override.get("simulateBattery") and not self._env_reason:
                reason = "on battery power"
            elif self._env_reason:
                reason = self._env_reason
            else:
                higher = self.lease.higher()
                if higher:
                    top = max(higher, key=lambda le: le.priority)
                    reason = f"yielding to {top.holder} (priority {top.priority})"
                else:
                    decision = self.guard.step() if waited_since is None else self.guard.start()
                    if not decision.ok:
                        reason = f"memory guard: {decision.reason}"
                    elif (
                        waited_since is not None
                        and self.pause_reason
                        and self.pause_reason.startswith("memory")
                    ):
                        ok, healthy_since = self.guard.recovered(healthy_since)
                        if not ok:
                            reason = "memory guard: holding for recovery"
            if reason is None:
                if waited_since is not None:
                    self.event(
                        "resume_after_pause",
                        reason=self.pause_reason,
                        waitedSec=round(time.time() - waited_since),
                    )
                    _log.info(
                        "resumed after pause",
                        reason=self.pause_reason,
                        waited=round(time.time() - waited_since),
                    )
                self.pause_reason = None
                return True
            if waited_since is None or reason != self.pause_reason:
                if waited_since is None:
                    waited_since = time.time()
                self.event("pause", reason=reason)
                _log.info("pausing", reason=reason, step=self.step)
                self.pause_reason = reason
                self.publish_status("paused")
            if not released and time.time() - waited_since > self.cfg.long_wait_sec:
                self.save("long pause")
                mx.clear_cache()
                released = True
            self.publish_status("paused")
            time.sleep(3)
        return False

    def publish_status(self, state: str) -> None:
        status.write(
            {
                "state": state,
                "runId": self.cfg.run_id,
                "model": self.mcfg.name,
                "parameters": int(
                    sum(cast(mx.array, v).size for _, v in tree_flatten(self.model.parameters()))
                ),
                "phase": self.schedule.phase(self.step),
                "step": self.step,
                "tokens": self.tokens,
                "pauseReason": self.pause_reason,
                "train": self.last_train,
                "valid": self.last_val,
                "milestones": self.milestones,
                "leasePriority": self.lease.priority,
                "startedAt": self.started_at,
            }
        )

    def run(self) -> int:
        cfg = self.cfg
        resources.renice(10)
        resources.apply_mlx_limits(cfg.memory_budget_gb, cfg.cache_limit_gb)
        signal.signal(signal.SIGTERM, self._signal)
        signal.signal(signal.SIGINT, self._signal)
        self.lease.acquire()
        try:
            self._build()
            self.publish_status("starting")
            while not self.stop_requested:
                decision = self.guard.start()
                foreign = resources.foreign_training()
                if decision.ok and not foreign:
                    break
                self.pause_reason = (
                    f"external training running ({foreign[0]})"
                    if foreign
                    else f"memory guard: {decision.reason}"
                )
                self.publish_status("waiting")
                _log.info("waiting before start", reason=self.pause_reason)
                time.sleep(15)
            self.last_ckpt_at = time.time()
            window_t0, window_tokens, window_losses = time.time(), 0, []
            if self.step == 0 and self.last_val is None:
                self._eval()
            while not self.stop_requested:
                if self.schedule.done(self.step) or (
                    cfg.max_steps is not None and self.step >= cfg.max_steps
                ):
                    break
                if not self._gate():
                    break
                t0 = time.time()
                self.opt.set_lr_mult(self.schedule.mult(self.step))
                acc = None
                loss_sum = mx.array(0.0)
                for _ in range(cfg.accum):
                    batch = mx.array(self.loader.next_batch(cfg.micro_batch))
                    loss, grads = self.micro(batch[:, :-1], batch[:, 1:])
                    acc = grads if acc is None else tree_map(lambda a, b: a + b, acc, grads)
                    loss_sum = loss_sum + loss
                    mx.eval(acc, loss_sum)
                acc = tree_map(lambda g: g / cfg.accum, acc)
                gnorm = self.apply(acc)
                mx.eval(self.model.parameters(), self.opt.state, gnorm)
                dt = time.time() - t0
                self.step += 1
                self.tokens += cfg.tokens_per_step
                self.elapsed_train_sec += dt
                window_tokens += cfg.tokens_per_step
                loss_v = float(loss_sum) / cfg.accum
                if not math.isfinite(loss_v):
                    self.event("nonfinite_loss", loss=str(loss_v))
                    raise RuntimeError(f"non-finite loss at step {self.step}")
                window_losses.append(loss_v)
                self.guard.set_own_usage(mx.get_active_memory() / resources.GB)
                if self.step % cfg.log_every == 0:
                    elapsed = time.time() - window_t0
                    self.last_train = {
                        "step": self.step,
                        "tokens": self.tokens,
                        "loss": round(sum(window_losses) / len(window_losses), 4),
                        "lr": round(float(self.opt.muon.learning_rate), 6),
                        "lrMult": round(self.schedule.mult(self.step), 4),
                        "tokensPerSec": round(window_tokens / max(elapsed, 1e-6)),
                        "peakMemGb": round(mx.get_peak_memory() / resources.GB, 3),
                        "gradNorm": round(float(gnorm), 4),
                        "elapsedSec": round(self.elapsed_train_sec, 1),
                        "at": now_iso(),
                    }
                    self.metrics.write(json.dumps({"type": "train", **self.last_train}) + "\n")
                    self.publish_status("training")
                    window_t0, window_tokens, window_losses = time.time(), 0, []
                if self.step % cfg.eval_every == 0:
                    self._eval()
                if self.tokens >= self.next_milestone_tokens:
                    self.next_milestone_tokens += cfg.milestone_every_tokens
                    self.milestones.append(
                        {"step": self.step, "tokens": self.tokens, "at": now_iso(), "kind": "tokens"}
                    )
                    self.save("token milestone", milestone=True)
                elif time.time() - self.last_ckpt_at >= cfg.checkpoint_every_sec:
                    self.save("periodic")
            if self.stop_requested:
                self.save(f"signal {self.stop_signal}")
                self.publish_status("stopped")
                return 0
            self._eval()
            kind = "release" if self.schedule.done(self.step) else "fork-point"
            self.milestones.append({"step": self.step, "tokens": self.tokens, "at": now_iso(), "kind": kind})
            self.save(f"finished ({kind})", milestone=True)
            self.publish_status("finished")
            return 0
        finally:
            self.lease.release()

    def _eval(self) -> None:
        t0 = time.time()
        res = evaluate(self.model, self.val_windows, self.cfg.micro_batch)
        bf = sum(res["bf16"].values()) / len(res["bf16"])
        q4 = sum(res["int4"].values()) / len(res["int4"])
        self.last_val = {
            "step": self.step,
            "tokens": self.tokens,
            "bf16": round(bf, 5),
            "int4": round(q4, 5),
            "gapRel": round((q4 - bf) / bf, 5),
            "perSource": {
                k: {"bf16": round(v, 4), "int4": round(res["int4"][k], 4)} for k, v in res["bf16"].items()
            },
            "at": now_iso(),
        }
        self.metrics.write(
            json.dumps({"type": "val", **self.last_val, "sec": round(time.time() - t0, 1)}) + "\n"
        )
        _log.info(
            "validation", step=self.step, bf16=round(bf, 4), int4=round(q4, 4), sec=round(time.time() - t0, 1)
        )
