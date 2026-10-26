import asyncio
import contextlib
import json
import secrets
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from candela_worker.config import ModelSpec, Settings, model_info
from candela_worker.engine import Engine, Job


class ChatMessageIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatCompletionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=200)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=32)
    stream: bool = False
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=8192)
    seed: int | None = None
    reasoning: bool | None = None
    chat_template_kwargs: dict[str, Any] | None = None
    candela_telemetry: bool = False


def _openai_tool_call(call: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "id": call["id"],
        "type": "function",
        "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
    }


def _usage(u: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_tokens": u["promptTokens"],
        "completion_tokens": u["completionTokens"],
        "total_tokens": u["promptTokens"] + u["completionTokens"],
        "completion_tokens_details": {"reasoning_tokens": u["reasoningTokens"]},
        "candela": u,
    }


def create_app(settings: Settings, engine: Engine, registry: dict[str, ModelSpec]) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        engine.start()
        try:
            yield
        finally:
            await engine.close()

    app = FastAPI(
        title="Candela worker (development)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    served = settings.model_ids or list(registry)

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": m,
                    "object": "model",
                    "owned_by": "candela",
                    "candela": model_info(registry[m], settings),
                }
                for m in served
                if m in registry
            ],
        }

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "state": engine.state(),
            "loaded": engine.loaded.spec.id if engine.loaded else None,
        }

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(body: ChatCompletionIn) -> StreamingResponse | JSONResponse:
        if body.model not in served or body.model not in registry:
            raise HTTPException(404, detail="unknown model")
        thinking = body.reasoning
        if thinking is None and body.chat_template_kwargs:
            thinking = bool(body.chat_template_kwargs.get("enable_thinking", False))
        job = Job(
            job_id="chatcmpl-" + secrets.token_hex(8),
            model_id=body.model,
            messages=[m.model_dump(exclude_none=True) for m in body.messages],
            tools=body.tools,
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_completion_tokens or body.max_tokens or 1024,
            reasoning=bool(thinking),
            telemetry=body.candela_telemetry,
            seed=body.seed,
        )
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def emit(event: str, data: dict[str, Any]) -> None:
            await queue.put((event, data))

        async def runner() -> None:
            try:
                await engine.run(job, emit)
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())
        created = int(time.time())

        def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> dict[str, Any]:
            return {
                "id": job.job_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": body.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                **extra,
            }

        if body.stream:

            async def sse() -> AsyncIterator[str]:
                calls = 0
                try:
                    yield f"data: {json.dumps(chunk({'role': 'assistant'}))}\n\n"
                    while (item := await queue.get()) is not None:
                        event, data = item
                        if event == "token":
                            out = chunk({"content": data["delta"]})
                        elif event == "reasoning":
                            out = chunk({"reasoning_content": data["delta"]})
                        elif event == "tool_call":
                            out = chunk({"tool_calls": [_openai_tool_call(data, calls)]})
                            calls += 1
                        elif event == "telemetry":
                            out = chunk({}, candela_telemetry=data)
                        elif event == "usage":
                            out = {**chunk({}), "choices": [], "usage": _usage(data)}
                        elif event == "done":
                            out = chunk({}, data["finishReason"])
                        else:
                            out = {"error": data}
                        yield f"data: {json.dumps(out, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                finally:
                    job.cancelled.set()

            async def on_close() -> None:
                # On client disconnect Starlette cancels the response while the body iterator is suspended at a
                # yield, so the iterator's finally only runs at garbage collection; this hook runs right away.
                job.cancelled.set()
                await task

            return StreamingResponse(
                sse(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
                background=BackgroundTask(on_close),
            )

        content: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        telemetry: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None
        finish = "stop"
        error: dict[str, Any] | None = None
        try:
            while (item := await queue.get()) is not None:
                event, data = item
                if event == "token":
                    content.append(data["delta"])
                elif event == "reasoning":
                    reasoning.append(data["delta"])
                elif event == "tool_call":
                    tool_calls.append(_openai_tool_call(data, len(tool_calls)))
                elif event == "telemetry":
                    telemetry.append(data)
                elif event == "usage":
                    usage = data
                elif event == "done":
                    finish = data["finishReason"]
                elif event == "error":
                    error = data
        finally:
            job.cancelled.set()
            await task
        if error:
            status = (
                503
                if error["code"] in ("overloaded", "upstream_unavailable")
                else 400
                if error["code"] == "invalid_request"
                else 500
            )
            return JSONResponse({"error": error}, status_code=status)
        message: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tool_calls:
            message["tool_calls"] = [{k: v for k, v in c.items() if k != "index"} for c in tool_calls]
        result: dict[str, Any] = {
            "id": job.job_id,
            "object": "chat.completion",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        }
        if usage:
            result["usage"] = _usage(usage)
        if telemetry:
            result["candela_telemetry"] = telemetry
        return JSONResponse(result)

    return app
