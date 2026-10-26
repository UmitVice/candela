import asyncio
import dataclasses
import json
from typing import Annotated

import typer

from candela_worker import log
from candela_worker.config import Settings, default_model, load_registry, model_info

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Candela Pro inference worker")


def _settings() -> Settings:
    log.setup()
    return Settings.from_env()


def _served(settings: Settings) -> list[str]:
    return settings.model_ids or [default_model(settings)]


@app.command()
def connect() -> None:
    """Dial out to the gateway over candela.worker.v1 and serve generation jobs (opens no listening socket)."""
    from candela_worker.engine import Engine, resolve_model_path
    from candela_worker.lease import release_stale_own
    from candela_worker.protocol import WorkerClient

    settings = _settings()
    if not settings.token:
        raise typer.BadParameter("CANDELA_WORKER_TOKEN is not set")
    registry = load_registry(settings)
    ids = _served(settings)
    missing = [m for m in ids if m not in registry]
    if missing:
        raise typer.BadParameter(f"unknown model ids: {', '.join(missing)}")
    infos = []
    for m in ids:
        spec = registry[m]
        local = None
        if spec.path is None:
            try:
                local = resolve_model_path(spec, allow_download=False)
            except Exception:
                local = None
        infos.append(model_info(spec, settings, local))
    settings = dataclasses.replace(settings, model_ids=ids)
    release_stale_own()

    async def main() -> None:
        engine = Engine(settings, registry)
        await WorkerClient(settings, engine, infos).run()

    asyncio.run(main())


@app.command()
def serve() -> None:
    """OpenAI-compatible HTTP API on 127.0.0.1 for local development (refused when CANDELA_ENV=production)."""
    import uvicorn

    from candela_worker.engine import Engine
    from candela_worker.http import create_app
    from candela_worker.lease import release_stale_own

    settings = _settings()
    if settings.production:
        raise typer.BadParameter("serve is development-only; production uses `connect`")
    registry = load_registry(settings)
    engine = Engine(settings, registry)
    api = create_app(settings, engine, registry)
    release_stale_own()
    uvicorn.run(api, host=settings.http_host, port=settings.http_port, log_level="warning", access_log=False)


@app.command()
def bench(
    model: Annotated[str | None, typer.Option(help="Model id from served-models.yaml")] = None,
    runs: Annotated[int, typer.Option(min=1, max=10)] = 3,
    max_tokens: Annotated[int, typer.Option(min=16, max=2048)] = 256,
    telemetry: Annotated[bool, typer.Option(help="Also measure telemetry overhead")] = True,
    kv_tokens: Annotated[
        int, typer.Option(help="Long-prompt KV-cache comparison size in tokens (0 = skip)")
    ] = 0,
) -> None:
    """TTFT, prefill and decode tokens/s, peak memory, telemetry overhead and optional 8-bit KV comparison."""
    from candela_worker.bench import run_bench

    settings = _settings()
    registry = load_registry(settings)
    run_bench(settings, registry, model or _served(settings)[0], runs, max_tokens, telemetry, kv_tokens)


@app.command()
def doctor() -> None:
    """Versions, Metal device, memory headroom, GPU leases and model paths."""
    from candela_worker.doctor import doctor as run

    print(json.dumps(run(_settings()), indent=2))


if __name__ == "__main__":
    app()
