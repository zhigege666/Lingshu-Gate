"""Memory diagnostics helpers for Lingshu Gate."""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
from typing import Any

from lingshu_gate.logging import log_event


PROC_ROOT = Path("/proc")


def collect_memory_snapshot(top_processes_limit: int = 12) -> dict[str, Any]:
    """Collect process, cgroup, and host memory information without extra dependencies."""

    return {
        "pid": os.getpid(),
        "platform": platform.platform(),
        "process": _process_memory(),
        "cgroup": _cgroup_memory(),
        "host": _host_memory(),
        "top_processes": _top_processes(top_processes_limit),
    }


def log_memory_snapshot(logger: logging.Logger, event: str, message: str, *, top_processes_limit: int = 12) -> None:
    """Write a structured memory snapshot into JSON logs."""

    snapshot = collect_memory_snapshot(top_processes_limit=top_processes_limit)
    log_event(logger, logging.INFO, event, message, memory=snapshot)


def _process_memory() -> dict[str, Any]:
    status = _read_proc_status(PROC_ROOT / "self" / "status")
    return {
        "rss_bytes": _kb_to_bytes(status.get("VmRSS")),
        "vms_bytes": _kb_to_bytes(status.get("VmSize")),
        "hwm_bytes": _kb_to_bytes(status.get("VmHWM")),
        "data_bytes": _kb_to_bytes(status.get("VmData")),
        "threads": _to_int(status.get("Threads")),
        "raw": status,
    }


def _cgroup_memory() -> dict[str, Any]:
    result: dict[str, Any] = {}
    current = _read_int_file(Path("/sys/fs/cgroup/memory.current"))
    maximum = _read_limit_file(Path("/sys/fs/cgroup/memory.max"))
    peak = _read_int_file(Path("/sys/fs/cgroup/memory.peak"))

    if current is None:
        current = _read_int_file(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"))
    if maximum is None:
        maximum = _read_limit_file(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    if peak is None:
        peak = _read_int_file(Path("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"))

    result["current_bytes"] = current
    result["limit_bytes"] = maximum
    result["peak_bytes"] = peak
    if current is not None and maximum is not None and maximum != 0:
        result["usage_percent"] = round(current * 100 / maximum, 2)
    return result


def _host_memory() -> dict[str, Any]:
    meminfo = _read_meminfo(PROC_ROOT / "meminfo")
    total = _kb_to_bytes(meminfo.get("MemTotal"))
    available = _kb_to_bytes(meminfo.get("MemAvailable"))
    used = total - available if total is not None and available is not None else None
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "raw": meminfo,
    }


def _top_processes(limit: int) -> list[dict[str, Any]]:
    """Return top RSS processes by reading /proc directly.

    The runtime image is intentionally slim and may not include procps/ps.
    Reading procfs keeps memory diagnostics useful without growing the image.
    """

    if not PROC_ROOT.exists():
        return [{"error": "/proc is not available"}]

    processes: list[dict[str, Any]] = []
    try:
        pid_dirs = [path for path in PROC_ROOT.iterdir() if path.name.isdigit()]
    except OSError as exc:
        return [{"error": str(exc)}]

    for pid_dir in pid_dirs:
        status = _read_proc_status(pid_dir / "status")
        if not status:
            continue

        rss_bytes = _kb_to_bytes(status.get("VmRSS"))
        vms_bytes = _kb_to_bytes(status.get("VmSize"))
        if rss_bytes is None and vms_bytes is None:
            continue

        pid = _to_int(status.get("Pid")) or _to_int(pid_dir.name)
        command = status.get("Name", "")
        processes.append(
            {
                "pid": pid,
                "ppid": _to_int(status.get("PPid")),
                "rss_bytes": rss_bytes,
                "vsz_bytes": vms_bytes,
                "threads": _to_int(status.get("Threads")),
                "command": command,
                "args": _read_cmdline(pid_dir / "cmdline") or command,
                "source": "procfs",
            }
        )

    processes.sort(key=lambda item: int(item.get("rss_bytes") or 0), reverse=True)
    return processes[: max(0, limit)]


def _read_proc_status(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _read_meminfo(path: Path) -> dict[str, str]:
    return _read_proc_status(path)


def _read_cmdline(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if not raw:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()[:500]


def _read_int_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return _to_int(text)


def _read_limit_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text == "max":
        return None
    return _to_int(text)


def _kb_to_bytes(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value * 1024
    number = _to_int(value.split()[0] if value.split() else value)
    return number * 1024 if number is not None else None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
