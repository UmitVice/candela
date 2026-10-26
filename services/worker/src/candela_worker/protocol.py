import asyncio
import contextlib
import json
import random
import signal
import time
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from candela_worker import log, sysinfo
from candela_worker.config import PROTOCOL, VERSION, Settings
from candela_worker.engine import Engine, Job

MAX_FRAME = 1 << 20
BACKOFF_MIN = 1.0
BACKOFF_MAX = 60.0
HEALTHY_RESET_SEC = 60.0
DRAIN_TIMEOUT_SEC = 150.0

_log = log.get("protocol")


class WorkerClient:
    """`candela.worker.v1` client: dials out to the gateway, registers, answers heartbeats and runs jobs."""

    def __init__(self, settings: Settings, engine: Engine, models: list[dict[str, Any]]) -> None:
        self.settings = settings
        self.engine = engine
        self.models = models
        self.device = settings.device or sysinfo.device_label()
        self._ws: ClientConnection | None = None
        self._send_lock = asyncio.Lock()
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()
        self.engine.on_status = self._send_status

    async def _send(self, msg: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise ConnectionError("not connected")
        data = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
        if len(data.encode()) > MAX_FRAME:
            raise ValueError("frame exceeds 1 MiB")
        async with self._send_lock:
            await ws.send(data)

    async def _send_status(self) -> None:
        if self._ws is None:
            return
        loaded = self.engine.loaded
        await self._send(
            {
                "type": "status",
                "state": self.engine.state(),
                "loadedModelId": loaded.spec.id if loaded else "",
                "memoryMb": self.engine.memory_mb(),
            }
        )

    def _install_signals(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._on_signal, sig)

    def _on_signal(self, sig: int) -> None:
        if self._stopping.is_set():
            _log.warning("second signal; cancelling jobs", signal=sig)
            for job in self._jobs.values():
                job.cancelled.set()
            return
        _log.info("shutdown requested; draining", signal=sig)
        self._stopping.set()
        self.engine.draining = True
        asyncio.get_running_loop().create_task(self._safe_status())

    async def _safe_status(self) -> None:
        with contextlib.suppress(Exception):
            await self._send_status()

    async def run(self) -> None:
        self._install_signals()
        self.engine.start()
        backoff = BACKOFF_MIN
        try:
            while not self._stopping.is_set():
                started = time.monotonic()
                try:
                    await self._session()
                except InvalidStatus as exc:
                    _log.warning("gateway refused the connection", status=exc.response.status_code)
                except (OSError, WebSocketException, TimeoutError) as exc:
                    _log.warning("gateway connection failed", err=type(exc).__name__)
                if self._stopping.is_set():
                    break
                if time.monotonic() - started >= HEALTHY_RESET_SEC:
                    backoff = BACKOFF_MIN
                delay = random.uniform(0, backoff)
                _log.info("reconnecting", delay_sec=round(delay, 2))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            await self._wait_jobs()
            await self.engine.close()
            _log.info("worker stopped")

    async def _wait_jobs(self) -> None:
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=DRAIN_TIMEOUT_SEC)
        for job in self._jobs.values():
            job.cancelled.set()
        if pending:
            await asyncio.wait(pending, timeout=5)

    async def _session(self) -> None:
        headers = {"Authorization": f"Bearer {self.settings.token}"}
        async with connect(
            self.settings.gateway_url,
            subprotocols=[PROTOCOL],  # pyright: ignore[reportArgumentType]
            additional_headers=headers,
            max_size=MAX_FRAME,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            user_agent_header=f"candela-worker/{VERSION}",
        ) as ws:
            self._ws = ws
            try:
                await self._send(
                    {
                        "type": "hello",
                        "protocol": PROTOCOL,
                        "workerId": self.settings.worker_id,
                        "version": VERSION,
                        "device": self.device,
                        "maxConcurrency": 1,
                        "models": self.models,
                    }
                )
                welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if welcome.get("type") != "welcome":
                    raise WebSocketException("expected welcome")
                self.engine.draining = self._stopping.is_set()
                _log.info(
                    "registered with gateway",
                    session=welcome.get("sessionId"),
                    models=[m["id"] for m in self.models],
                )
                await self._send_status()
                await self._read_loop(ws)
            except ConnectionClosed as exc:
                _log.warning("gateway closed the connection", code=exc.rcvd.code if exc.rcvd else None)
            finally:
                self._ws = None
                for job in self._jobs.values():
                    job.cancelled.set()

    async def _read_loop(self, ws: ClientConnection) -> None:
        stop_wait = asyncio.create_task(self._stopping.wait())
        try:
            while True:
                recv = asyncio.create_task(ws.recv())
                done, _ = await asyncio.wait({recv, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
                if recv not in done:
                    recv.cancel()
                    await self._wait_jobs()
                    await ws.close(1001, "worker shutting down")
                    return
                raw = recv.result()
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    _log.warning("invalid gateway frame")
                    continue
                await self._handle(msg)
        finally:
            stop_wait.cancel()

    async def _handle(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "ping":
            await self._send({"type": "pong", "ts": msg.get("ts")})
        elif kind == "job":
            self._start_job(msg)
        elif kind == "cancel":
            job = self._jobs.get(str(msg.get("jobId")))
            if job:
                job.cancelled.set()
        elif kind == "drain":
            _log.info("gateway requested drain")
            self.engine.draining = True
            await self._send_status()
        elif kind == "welcome":
            pass
        else:
            _log.debug("ignored gateway frame", type=kind)

    def _start_job(self, msg: dict[str, Any]) -> None:
        try:
            job = Job.from_wire(msg)
        except KeyError, TypeError, ValueError:
            _log.warning("invalid job frame")
            return
        self._jobs[job.job_id] = job
        task = asyncio.create_task(self._run_job(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_job(self, job: Job) -> None:
        seq = 0

        async def emit(event: str, data: dict[str, Any]) -> None:
            nonlocal seq
            seq += 1
            await self._send({"type": "event", "jobId": job.job_id, "seq": seq, "event": event, "data": data})

        _log.info(
            "job received",
            job=job.job_id,
            model=job.model_id,
            messages=len(job.messages),
            telemetry=job.telemetry,
        )
        try:
            await self.engine.run(job, emit)
        except ConnectionError, ConnectionClosed:
            job.cancelled.set()
        finally:
            self._jobs.pop(job.job_id, None)
