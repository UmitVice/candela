import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from candela_spark import paths
from candela_spark.ops import status as trainer_status

LABEL = "com.candela.spark-trainer"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
# Deny all networking to the trainer: data is local and training must never depend on the network.
NO_NETWORK_PROFILE = "(version 1)(allow default)(deny network*)"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def plist(config: Path) -> dict[str, Any]:
    spark_bin = str(Path(sys.executable).parent / "spark")
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LABEL,
        # caffeinate -s keeps the Mac awake only on AC power; on battery the trainer pauses anyway.
        "ProgramArguments": [
            "/usr/bin/caffeinate",
            "-s",
            "/usr/bin/sandbox-exec",
            "-p",
            NO_NETWORK_PROFILE,
            spark_bin,
            "train",
            str(config.resolve()),
        ],
        "WorkingDirectory": str(paths.ROOT),
        "EnvironmentVariables": {
            "HF_HUB_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
            "TOKENIZERS_PARALLELISM": "false",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 60,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "StandardOutPath": str(paths.LOGS / "spark-trainer.out.log"),
        "StandardErrorPath": str(paths.LOGS / "spark-trainer.err.log"),
    }


def install(config: Path) -> dict[str, Any]:
    if not config.exists():
        raise FileNotFoundError(config)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    if PLIST.exists():
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    with PLIST.open("wb") as f:
        plistlib.dump(plist(config), f)
    res = _launchctl("bootstrap", _domain(), str(PLIST))
    return {"installed": res.returncode == 0, "plist": PLIST.name, "stderr": res.stderr.strip()}


def uninstall() -> dict[str, Any]:
    res = _launchctl("bootout", f"{_domain()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    return {"removed": True, "bootout": res.returncode == 0}


def status() -> dict[str, Any]:
    res = _launchctl("print", f"{_domain()}/{LABEL}")
    info: dict[str, Any] = {"loaded": res.returncode == 0}
    for raw in res.stdout.splitlines():
        line = raw.strip()
        for key in ("state = ", "pid = ", "runs = ", "last exit code = "):
            if line.startswith(key):
                info[key.split(" =")[0].replace(" ", "_")] = line.split("= ", 1)[1]
    info["trainer"] = trainer_status.read()
    return info
