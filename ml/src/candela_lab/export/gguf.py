import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from candela_lab import config, gpu_lease, log, resources
from candela_lab.paths import ML_DIR, RUNS_DIR, VENDOR_DIR

_log = log.get("export")

LLAMA_CPP_TAG = "b9960"
LLAMA_CPP_DIR = VENDOR_DIR / "llama.cpp"
CHECK_PORT = 8713
PROMPT = "In one sentence: what does an RSI(14) reading of 72 usually indicate?"


def _hf_name(mlx_name: str) -> str:
    """MLX module paths (`language_model.model.layers.N...`) → HF checkpoint paths (`model.language_model.layers.N...`)."""
    if mlx_name.startswith("language_model.model."):
        return "model.language_model." + mlx_name.removeprefix("language_model.model.")
    return mlx_name


def mlx_to_peft(adapter_dir: Path, out_dir: Path, base_ref: str) -> Path:
    import mlx.core as mx

    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    lp = cfg["lora_parameters"]
    weights = mx.load(str(adapter_dir / "adapters.safetensors"))
    tensors: dict[str, Any] = {}
    targets: set[str] = set()
    for name, w in weights.items():  # type: ignore[union-attr]
        module, leaf = name.rsplit(".", 1)
        hf = _hf_name(module)
        targets.add(hf.rsplit(".", 1)[-1])
        if leaf == "lora_a":
            tensors[f"base_model.model.{hf}.lora_A.weight"] = mx.transpose(w).astype(mx.float16)
        elif leaf == "lora_b":
            tensors[f"base_model.model.{hf}.lora_B.weight"] = mx.transpose(w).astype(mx.float16)
    out_dir.mkdir(parents=True, exist_ok=True)
    mx.save_safetensors(str(out_dir / "adapter_model.safetensors"), tensors)
    rank = int(lp["rank"])
    (out_dir / "adapter_config.json").write_text(
        json.dumps(
            {
                "peft_type": "LORA",
                "task_type": "CAUSAL_LM",
                "base_model_name_or_path": base_ref,
                "r": rank,
                "lora_alpha": float(lp["scale"]) * rank,
                "lora_dropout": float(lp["dropout"]),
                "target_modules": sorted(targets),
                "bias": "none",
                "fan_in_fan_out": False,
                "inference_mode": True,
            },
            indent=2,
        )
    )
    _log.info("peft adapter written", path=str(out_dir), tensors=len(tensors), modules=sorted(targets))
    return out_dir


def _converter() -> Path:
    script = LLAMA_CPP_DIR / "convert_lora_to_gguf.py"
    if not script.exists():
        raise FileNotFoundError(
            f"{script} missing; clone it with: git clone --depth 1 --branch {LLAMA_CPP_TAG} "
            f"https://github.com/ggml-org/llama.cpp.git {LLAMA_CPP_DIR}"
        )
    return script


def export_lora(run_id: str) -> Path:
    rd = RUNS_DIR / run_id
    run = json.loads((rd / "run.json").read_text())
    spec = config.model(run["config"]["model"])
    reference = spec.reference_path()
    if not reference or not Path(reference, "config.json").exists():
        raise FileNotFoundError("bf16 QAT reference (config.json) is required by convert_lora_to_gguf.py")
    export_dir = rd / "export"
    peft_dir = mlx_to_peft(rd / "adapter", export_dir / "peft", spec.upstream)
    out = export_dir / "candela-pro-lora-f16.gguf"
    cmd = [
        "uv",
        "run",
        "--frozen",
        "--group",
        "convert",
        "python",
        str(_converter()),
        str(peft_dir),
        "--base",
        reference,
        "--outtype",
        "f16",
        "--outfile",
        str(out),
    ]
    _log.info("converting adapter to GGUF LoRA", out=str(out))
    t0 = time.time()
    subprocess.run(
        cmd, check=True, cwd=str(ML_DIR), env={**os.environ, "PYTHONPATH": str(LLAMA_CPP_DIR / "gguf-py")}
    )
    _log.info(
        "gguf lora written",
        path=str(out),
        mb=round(out.stat().st_size / 1e6, 1),
        seconds=round(time.time() - t0, 1),
    )
    return out


def _chat(client: httpx.Client, max_tokens: int = 160) -> str:
    r = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": PROMPT}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "seed": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def serve_check(run_id: str) -> dict[str, Any]:
    """Loads the QAT GGUF with the converted LoRA in a local llama-server on loopback and compares scale 0 vs 1."""
    rd = RUNS_DIR / run_id
    run = json.loads((rd / "run.json").read_text())
    spec = config.model(run["config"]["model"])
    base = spec.gguf_path()
    lora = rd / "export" / "candela-pro-lora-f16.gguf"
    if not base or not Path(base).exists() or not lora.exists():
        raise FileNotFoundError("QAT GGUF base or converted LoRA missing")
    guard = resources.ResourceGuard(budget_gb=spec.inference_budget_gb, policy=resources.PRO_POLICY)
    result: dict[str, Any] = {}
    with gpu_lease.Lease(
        "lab-export", purpose=f"llama-server --lora check {run_id}", state="waiting"
    ) as lease:
        guard.wait_for_headroom(what="llama-server lora check")
        lease.activate()
        log_path = rd / "export" / "llama-server.log"
        cmd = [
            "llama-server",
            "-m",
            base,
            "--lora",
            str(lora),
            "--host",
            "127.0.0.1",
            "--port",
            str(CHECK_PORT),
            "-c",
            "4096",
            "-np",
            "1",
            "-t",
            "4",
            "--jinja",
        ]
        t0 = time.time()
        with log_path.open("w") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)
        try:
            client = httpx.Client(base_url=f"http://127.0.0.1:{CHECK_PORT}", timeout=120)
            for _ in range(240):
                if proc.poll() is not None:
                    raise RuntimeError(f"llama-server exited early, see {log_path}")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            result["loadSeconds"] = round(time.time() - t0, 1)
            adapters = client.get("/lora-adapters").json()
            result["adapters"] = adapters
            with_lora = _chat(client)
            client.post("/lora-adapters", json=[{"id": 0, "scale": 0.0}]).raise_for_status()
            without = _chat(client)
            result.update(
                {
                    "prompt": PROMPT,
                    "withLora": with_lora,
                    "withoutLora": without,
                    "differs": with_lora != without,
                }
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
    (rd / "export" / "llama-server-check.json").write_text(json.dumps(result, indent=2))
    _log.info(
        "llama-server lora check", adapters=len(result.get("adapters", [])), differs=result.get("differs")
    )
    return result


def export_fused(run_id: str, quant: str = "Q4_K_M") -> Path:
    raise SystemExit(
        f"Refusing to fuse {run_id} ({quant}): Candela Pro adapters are never merged into the QAT int4 base "
        "(ADR 0003). Use `lab export gguf --lora` for a portable GGUF LoRA."
    )
