import asyncio
import contextlib
import gc
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import mlx.core as mx
from mlx_lm.models.cache import KVCache, can_trim_prompt_cache, make_prompt_cache, trim_prompt_cache
from mlx_lm.sample_utils import make_sampler

from candela_worker import log, sysinfo
from candela_worker.chat import FAMILIES, Family, Splitter, ToolCallError, parse_tool_calls, template_messages
from candela_worker.config import ModelSpec, Settings
from candela_worker.lease import GpuLease
from candela_worker.telemetry import Telemetry

GB = 1024**3
MB = 1024**2
TELEMETRY_INTERVAL_SEC = 0.055
KV_GROUP_SIZE = 64

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
_log = log.get("engine")


class JobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Job:
    job_id: str
    model_id: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float = 0.6
    top_p: float = 0.95
    max_tokens: int = 1024
    reasoning: bool = False
    telemetry: bool = False
    seed: int | None = None
    deadline_ms: int = 120_000
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    received_at: float = field(default_factory=time.perf_counter)

    @classmethod
    def from_wire(cls, msg: dict[str, Any]) -> Job:
        p = msg.get("params") or {}
        seed = p.get("seed")
        return cls(
            job_id=str(msg["jobId"]),
            model_id=str(msg.get("modelId", "")),
            messages=list(msg.get("messages") or []),
            tools=msg.get("tools") or None,
            temperature=float(p.get("temperature", 0.6)),
            top_p=float(p.get("topP", 0.95)),
            max_tokens=int(p.get("maxTokens", 1024)),
            reasoning=bool(p.get("reasoning", False)),
            telemetry=bool(p.get("telemetry", False)),
            seed=int(seed) if seed is not None else None,
            deadline_ms=int(msg.get("deadlineMs", 120_000)),
        )


@dataclass
class Loaded:
    spec: ModelSpec
    model: Any
    tokenizer: Any
    family: Family
    telemetry: Telemetry
    stop_ids: set[int]
    weights_mb: float
    load_sec: float


class PromptCacheLRU:
    """Bounded LRU of KV caches keyed by the exact token sequence they hold. An entry is moved out while a job
    uses it (no copies), trimmed to the longest common prefix when the cache type allows, and put back after."""

    def __init__(self, max_entries: int, max_bytes: int) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[int, tuple[str, list[int], list[Any], int]] = OrderedDict()
        self._next = 0

    def take(self, model_id: str, tokens: list[int]) -> tuple[list[Any] | None, int]:
        best, best_len = None, 0
        for key, (mid, toks, *_) in self._entries.items():
            if mid != model_id:
                continue
            n = _common_prefix(toks, tokens)
            if n > best_len:
                best, best_len = key, n
        if best is None:
            return None, 0
        _, toks, cache, _ = self._entries.pop(best)
        keep = min(best_len, len(tokens) - 1)
        extra = len(toks) - keep
        if extra > 0 and (
            keep <= 0 or not can_trim_prompt_cache(cache) or trim_prompt_cache(cache, extra) != extra
        ):
            return None, 0
        return cache, keep

    def put(self, model_id: str, tokens: list[int], cache: list[Any]) -> None:
        nbytes = sum(c.nbytes for c in cache)
        if nbytes > self.max_bytes or self.max_entries <= 0:
            return
        self._next += 1
        self._entries[self._next] = (model_id, list(tokens), cache, nbytes)
        while (
            len(self._entries) > self.max_entries
            or sum(e[3] for e in self._entries.values()) > self.max_bytes
        ):
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def nbytes(self) -> int:
        return sum(e[3] for e in self._entries.values())


def _common_prefix(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def quantize_kv(cache: list[Any], start: int, bits: int) -> None:
    """8-bit KV for full-attention layers past `start` tokens. Sliding-window caches stay as they are: they are
    bounded by the window and mlx-lm cannot quantize them."""
    if not bits:
        return
    for i, c in enumerate(cache):
        if type(c) is KVCache and c.offset >= start:
            cache[i] = c.to_quantized(group_size=KV_GROUP_SIZE, bits=bits)


def _weights_mb(path: Path) -> float:
    return sum(p.stat().st_size for p in path.glob("*.safetensors")) / MB


def resolve_model_path(spec: ModelSpec, allow_download: bool) -> Path:
    if spec.path is not None:
        return spec.path
    from huggingface_hub import snapshot_download

    assert spec.hf_repo is not None
    try:
        return Path(snapshot_download(spec.hf_repo, revision=spec.hf_revision, local_files_only=True))
    except Exception:
        if not allow_download:
            raise
        return Path(snapshot_download(spec.hf_repo, revision=spec.hf_revision))


class Engine:
    """Owns the MLX model on one dedicated thread: lazy load, admission control, GPU lease, generation and idle unload."""

    def __init__(self, settings: Settings, registry: dict[str, ModelSpec]) -> None:
        self.settings = settings
        self.registry = registry
        self.loaded: Loaded | None = None
        self.busy = False
        self.draining = False
        self.last_used = time.monotonic()
        self.on_status: Callable[[], Awaitable[None]] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        self._cache = PromptCacheLRU(settings.prompt_cache_entries, settings.prompt_cache_mb * MB)
        self._idle_task: asyncio.Task[None] | None = None
        self.last_stats: dict[str, Any] = {}
        mx.set_cache_limit(settings.cache_limit_mb * MB)

    def start(self) -> None:
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())

    async def close(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
        await self._in_thread(self._unload)
        self._executor.shutdown(wait=True)

    def state(self) -> str:
        return "draining" if self.draining else "busy" if self.busy else "idle"

    def memory_mb(self) -> int:
        return int(mx.get_active_memory() / MB)

    async def _in_thread[T](self, fn: Callable[..., T], *args: Any) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    async def _notify(self) -> None:
        if self.on_status:
            with contextlib.suppress(Exception):
                await self.on_status()

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            idle = time.monotonic() - self.last_used
            if self.loaded and not self.busy and idle >= self.settings.idle_unload_sec:
                before = sysinfo.memory()
                active = self.memory_mb()
                await self._in_thread(self._unload)
                after = sysinfo.memory()
                _log.info(
                    "model unloaded after idle timeout",
                    idle_sec=round(idle),
                    mlx_active_mb_before=active,
                    mlx_active_mb_after=self.memory_mb(),
                    rss_mb_before=round(before.process_rss_mb),
                    rss_mb_after=round(after.process_rss_mb),
                    available_gb_before=round(before.available_gb, 2),
                    available_gb_after=round(after.available_gb, 2),
                )
                await self._notify()

    def clear_prompt_cache(self) -> None:
        self._cache.clear()

    def _unload(self) -> None:
        if self.loaded is None:
            return
        self._cache.clear()
        self.loaded = None
        gc.collect()
        mx.clear_cache()

    def _load(self, spec: ModelSpec) -> Loaded:
        if self.loaded and self.loaded.spec.id == spec.id:
            return self.loaded
        self._unload()
        from mlx_lm import load

        path = resolve_model_path(spec, allow_download=not self.settings.production)
        started = time.perf_counter()
        mx.set_memory_limit(int(spec.budget_gb * GB))
        pair = load(str(path), adapter_path=str(spec.adapter) if spec.adapter else None)
        model, tokenizer = pair[0], pair[1]
        model.eval()
        family = FAMILIES[spec.family]
        stop_ids = set(tokenizer.eos_token_ids)
        for s in (*family.stop, *spec.stop):
            ids = tokenizer.encode(s, add_special_tokens=False)
            if len(ids) == 1:
                stop_ids.add(ids[0])
        loaded = Loaded(
            spec=spec,
            model=model,
            tokenizer=tokenizer,
            family=family,
            telemetry=Telemetry(model),
            stop_ids=stop_ids,
            weights_mb=_weights_mb(path) + (_weights_mb(spec.adapter) if spec.adapter else 0.0),
            load_sec=time.perf_counter() - started,
        )
        self.loaded = loaded
        _log.info(
            "model loaded",
            model=spec.id,
            adapter=spec.adapter is not None,
            load_sec=round(loaded.load_sec, 2),
            mlx_active_mb=self.memory_mb(),
        )
        return loaded

    async def _admit(self, spec: ModelSpec, job: Job) -> str | None:
        """Returns None when there is memory headroom for the job, else the reason for declining it."""
        resident = self.loaded is not None and self.loaded.spec.id == spec.id
        need = (1.0 if resident else spec.budget_gb) + self.settings.reserve_gb
        deadline = time.monotonic() + self.settings.admission_wait_sec
        while True:
            mem = sysinfo.memory()
            if mem.pressure != "critical" and mem.available_gb >= need:
                return None
            if job.cancelled.is_set():
                return "cancelled"
            if time.monotonic() >= deadline:
                return (
                    f"memory headroom {mem.available_gb:.1f} GB below {need:.1f} GB (pressure {mem.pressure})"
                )
            await asyncio.sleep(1.0)

    async def run(self, job: Job, emit: Emit) -> None:
        if self.draining:
            await emit("error", {"code": "upstream_unavailable", "message": "worker is draining"})
            return
        if self.busy:
            await emit("error", {"code": "overloaded", "message": "worker is busy"})
            return
        spec = self.registry.get(job.model_id)
        if spec is None or (self.settings.model_ids and job.model_id not in self.settings.model_ids):
            await emit("error", {"code": "invalid_request", "message": "unknown model"})
            return
        self.busy = True
        await self._notify()
        lease = GpuLease(f"inference {spec.id}").acquire()
        try:
            reason = await self._admit(spec, job)
            if reason == "cancelled":
                await emit("done", {"finishReason": "cancelled"})
                return
            if reason:
                _log.warning("job declined", job=job.job_id, reason=reason)
                await emit(
                    "error", {"code": "overloaded", "message": "GPU node has no memory headroom right now"}
                )
                return
            lease.activate()
            await self._stream(job, spec, emit)
        finally:
            lease.release()
            self.busy = False
            self.last_used = time.monotonic()
            await self._notify()

    async def _stream(self, job: Job, spec: ModelSpec, emit: Emit) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        stop = threading.Event()

        def push(event: str, data: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (event, data))

        def work() -> None:
            try:
                self._generate(job, spec, push, stop)
            except JobError as exc:
                push("error", {"code": exc.code, "message": exc.message})
            except Exception:
                _log.error("generation failed", exc=True, job=job.job_id)
                push("error", {"code": "internal", "message": "generation failed"})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        future = loop.run_in_executor(self._executor, work)
        cancel_wait = asyncio.create_task(job.cancelled.wait())
        terminal = False
        cancelled_at: float | None = None
        try:
            while True:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({get, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
                if get not in done:
                    get.cancel()
                    stop.set()
                    cancelled_at = time.perf_counter()
                    if not terminal:
                        terminal = True
                        await emit("done", {"finishReason": "cancelled"})
                    break
                item = get.result()
                if item is None:
                    break
                event, data = item
                if terminal:
                    continue
                try:
                    await emit(event, data)
                except Exception:
                    stop.set()
                    terminal = True
                    break
                if event in ("done", "error"):
                    terminal = True
        finally:
            cancel_wait.cancel()
            await future
            if cancelled_at is not None:
                _log.info(
                    "job cancelled",
                    job=job.job_id,
                    gpu_stopped_ms=round((time.perf_counter() - cancelled_at) * 1000),
                )

    def _generate(
        self, job: Job, spec: ModelSpec, push: Callable[[str, dict[str, Any]], None], stop: threading.Event
    ) -> None:
        mx.reset_peak_memory()
        lm = self._load(spec)
        tok = lm.tokenizer
        try:
            msgs = template_messages(job.messages)
        except (ValueError, TypeError) as exc:
            raise JobError("invalid_request", "messages could not be rendered") from exc
        prompt = tok.apply_chat_template(
            msgs, tools=job.tools, add_generation_prompt=True, tokenize=False, enable_thinking=job.reasoning
        )
        tokens: list[int] = tok.encode(prompt, add_special_tokens=False)
        if len(tokens) > self.settings.max_prompt_tokens:
            raise JobError("invalid_request", "prompt exceeds the worker context limit")
        if not tokens:
            raise JobError("invalid_request", "empty prompt")

        deadline = job.received_at + job.deadline_ms / 1000
        cache, reused = self._cache.take(spec.id, tokens)
        if cache is None:
            cache = make_prompt_cache(lm.model)
        fed = list(tokens[:reused])
        rest = tokens[reused:]
        kv_bits = self.settings.kv_bits
        model = lm.model
        started = time.perf_counter()

        def interrupted() -> str | None:
            if stop.is_set():
                return "cancelled"
            if time.perf_counter() > deadline:
                return "deadline"
            return None

        while len(rest) > 1:
            if why := interrupted():
                return self._finish_interrupted(why, push)
            n = min(self.settings.prefill_chunk, len(rest) - 1)
            model(mx.array(rest[:n])[None], cache=cache)
            quantize_kv(cache, self.settings.kv_start, kv_bits)
            mx.eval([c.state for c in cache])
            fed.extend(rest[:n])
            rest = rest[n:]
        prefill_sec = time.perf_counter() - started

        if job.seed is not None:
            mx.random.seed(job.seed)
        sampler = make_sampler(temp=job.temperature, top_p=job.top_p)
        tele = lm.telemetry if job.telemetry else None
        last_frame = [0.0]

        def due() -> bool:
            if tele is None:
                return False
            now = time.perf_counter()
            if now - last_frame[0] >= TELEMETRY_INTERVAL_SEC:
                last_frame[0] = now
                return True
            return False

        def step(y: mx.array, probe: bool) -> tuple[mx.array, dict[str, mx.array] | None]:
            if probe and tele:
                tele.arm()
            logits = model(y[None], cache=cache)[:, -1, :]
            states = tele.disarm() if probe and tele else None
            quantize_kv(cache, self.settings.kv_start, kv_bits)
            logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
            nxt = sampler(logprobs).reshape(-1)
            graph = tele.graph(states, logprobs) if tele and states else None
            mx.async_eval(nxt, *(graph.values() if graph else ()))
            return nxt, graph

        splitter = Splitter(lm.family)
        tail = prompt.rstrip()
        if tail.endswith(lm.family.think_start):
            splitter.start_in_reasoning()
        detok = tok.detokenizer
        detok.reset()
        decode_one = tok.decode

        y_in = mx.array(rest)
        fed.extend(rest)
        y, graph = step(y_in, due())
        n = 0
        reasoning_tokens = 0
        first_at: float | None = None
        finish = "length"
        try:
            while n < job.max_tokens:
                nxt: tuple[mx.array, dict[str, mx.array] | None] | None = None
                if n + 1 < job.max_tokens:
                    nxt = step(y, due())
                token = int(cast(list[int], y.tolist())[0])
                if first_at is None:
                    first_at = time.perf_counter()
                if nxt is not None:
                    fed.append(token)
                n += 1
                if token in lm.stop_ids:
                    finish = "stop"
                    break
                phase = splitter.phase
                if phase == "reasoning":
                    reasoning_tokens += 1
                detok.add_token(token)
                for part_phase, text in splitter.feed(detok.last_segment):
                    push("reasoning" if part_phase == "reasoning" else "token", {"delta": text})
                if graph is not None and tele is not None:
                    frame = tele.frame(
                        graph,
                        n - 1,
                        decode_one([token]),
                        "reasoning" if phase == "reasoning" else "answer",
                        lambda t: decode_one([t]),
                    )
                    push("telemetry", frame)
                if why := interrupted():
                    return self._finish_interrupted(why, push)
                if nxt is None:
                    break
                y, graph = nxt
        finally:
            peak_mb = mx.get_peak_memory() / MB
        detok.finalize()
        for part_phase, text in splitter.feed(detok.last_segment, final=True):
            push("reasoning" if part_phase == "reasoning" else "token", {"delta": text})

        if (body := splitter.unterminated_tool()) is not None and body.strip():
            splitter.tool_bodies.append(body)
        calls: list[dict[str, Any]] = []
        try:
            for body in splitter.tool_bodies:
                calls.extend(parse_tool_calls(lm.family, body))
        except ToolCallError as exc:
            _log.warning("malformed tool call", job=job.job_id, err=str(exc)[:200])
            raise JobError("internal", "the model produced a malformed tool call") from exc
        for call in calls:
            push("tool_call", call)
        if calls:
            finish = "tool_calls"

        ended = time.perf_counter()
        decode_sec = ended - (first_at or ended)
        usage = {
            "promptTokens": len(tokens),
            "completionTokens": n,
            "reasoningTokens": reasoning_tokens,
            "timeToFirstTokenMs": round(((first_at or ended) - job.received_at) * 1000),
            "tokensPerSecond": round((n - 1) / decode_sec, 2) if n > 1 and decode_sec > 0 else 0.0,
            "totalMs": round((ended - job.received_at) * 1000),
        }
        push("usage", usage)
        push("done", {"finishReason": finish})
        self._cache.put(spec.id, fed, cache)
        self.last_stats = {
            "finish": finish,
            "prompt_tokens": len(tokens),
            "reused_tokens": reused,
            "prefill_sec": round(prefill_sec, 3),
            "completion_tokens": n,
            "tool_calls": len(calls),
            "tps": usage["tokensPerSecond"],
            "ttft_ms": usage["timeToFirstTokenMs"],
            "peak_mb": round(peak_mb),
            "prompt_cache_mb": round(self._cache.nbytes / MB),
        }
        _log.info("job finished", job=job.job_id, model=spec.id, **self.last_stats)

    def _finish_interrupted(self, why: str, push: Callable[[str, dict[str, Any]], None]) -> None:
        if why == "deadline":
            push("error", {"code": "upstream_timeout", "message": "job deadline exceeded"})
        else:
            push("done", {"finishReason": "cancelled"})
