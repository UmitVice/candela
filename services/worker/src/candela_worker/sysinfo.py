import ctypes
import ctypes.util
from dataclasses import dataclass
from typing import Literal

import psutil

GB = 1024**3
MB = 1024**2
Pressure = Literal["normal", "warn", "critical", "unknown"]

# kern.memorystatus_vm_pressure_level reports the kernel's dispatch levels: 1 normal, 2 warn, 4 critical.
_PRESSURE: dict[int, Pressure] = {1: "normal", 2: "warn", 4: "critical"}

# sysctlbyname through libc instead of spawning `sysctl`: the production sandbox denies process execution.
_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _sysctl_raw(name: str, size: int = 256) -> bytes | None:
    buf = ctypes.create_string_buffer(size)
    length = ctypes.c_size_t(size)
    if _libc.sysctlbyname(name.encode(), buf, ctypes.byref(length), None, ctypes.c_size_t(0)) != 0:
        return None
    return buf.raw[: length.value]


def sysctl_int(name: str) -> int | None:
    raw = _sysctl_raw(name, 8)
    return int.from_bytes(raw, "little") if raw else None


def sysctl_str(name: str) -> str | None:
    raw = _sysctl_raw(name)
    return raw.rstrip(b"\x00").decode(errors="replace") if raw else None


class _VmStats64(ctypes.Structure):
    _fields_ = [
        ("free_count", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("inactive_count", ctypes.c_uint32),
        ("wire_count", ctypes.c_uint32),
        ("zero_fill_count", ctypes.c_uint64),
        ("reactivations", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("pageouts", ctypes.c_uint64),
        ("faults", ctypes.c_uint64),
        ("cow_faults", ctypes.c_uint64),
        ("lookups", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("purges", ctypes.c_uint64),
        ("purgeable_count", ctypes.c_uint32),
        ("speculative_count", ctypes.c_uint32),
        ("decompressions", ctypes.c_uint64),
        ("compressions", ctypes.c_uint64),
        ("swapins", ctypes.c_uint64),
        ("swapouts", ctypes.c_uint64),
        ("compressor_page_count", ctypes.c_uint32),
        ("throttled_count", ctypes.c_uint32),
        ("external_page_count", ctypes.c_uint32),
        ("internal_page_count", ctypes.c_uint32),
        ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
    ]


_HOST_VM_INFO64 = 4


def available_bytes() -> int:
    """free + inactive + purgeable + speculative pages (host_statistics64, the numbers `vm_stat` prints): the same
    measure the Candela Lab and Spark guards use, so admission decisions agree across processes."""
    stats = _VmStats64()
    count = ctypes.c_uint32(ctypes.sizeof(stats) // 4)
    host = _libc.mach_host_self()
    if _libc.host_statistics64(host, _HOST_VM_INFO64, ctypes.byref(stats), ctypes.byref(count)) != 0:
        return int(psutil.virtual_memory().available)
    page = sysctl_int("hw.pagesize") or 16384
    pages = stats.free_count + stats.inactive_count + stats.purgeable_count + stats.speculative_count
    return pages * page


def pressure() -> Pressure:
    level = sysctl_int("kern.memorystatus_vm_pressure_level")
    return _PRESSURE.get(level, "unknown") if level is not None else "unknown"


@dataclass(frozen=True)
class Memory:
    total_gb: float
    available_gb: float
    swap_used_gb: float
    pressure: Pressure
    process_rss_mb: float

    def as_dict(self) -> dict[str, float | str]:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in self.__dict__.items()}


def memory() -> Memory:
    vm = psutil.virtual_memory()
    return Memory(
        total_gb=vm.total / GB,
        available_gb=available_bytes() / GB,
        swap_used_gb=psutil.swap_memory().used / GB,
        pressure=pressure(),
        process_rss_mb=psutil.Process().memory_info().rss / MB,
    )


def device_label() -> str:
    """Generic hardware label for `hello` (ADR 0008): chip and memory size, never hostname or user."""
    chip = sysctl_str("machdep.cpu.brand_string") or "Apple Silicon"
    total = sysctl_int("hw.memsize") or psutil.virtual_memory().total
    return f"{chip} · {round(total / GB)} GB"
