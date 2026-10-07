"""Telemetrie systeme pour le tableau de bord (CPU, RAM, disque, reseau, batterie, GPU...)."""

from __future__ import annotations

import platform
import shutil
import socket
import time
from functools import lru_cache

import psutil

from .osutils import run

_last_net = {"t": time.time(), "sent": 0, "recv": 0}
_init = False


def _net_rates() -> tuple[float, float]:
    counters = psutil.net_io_counters()
    now = time.time()
    dt = max(now - _last_net["t"], 1e-3)
    up = (counters.bytes_sent - _last_net["sent"]) / dt if _last_net["sent"] else 0.0
    down = (counters.bytes_recv - _last_net["recv"]) / dt if _last_net["recv"] else 0.0
    _last_net.update(t=now, sent=counters.bytes_sent, recv=counters.bytes_recv)
    return max(up, 0.0), max(down, 0.0)


def _main_disk() -> str:
    if platform.system() == "Windows":
        import os

        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


@lru_cache(maxsize=1)
def _has_nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None


def gpu_info() -> list[dict]:
    if not _has_nvidia():
        return []
    try:
        out = run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            timeout=4,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 5:
            try:
                gpus.append({
                    "name": parts[0], "load": float(parts[1]), "mem_used_mb": float(parts[2]),
                    "mem_total_mb": float(parts[3]), "temp_c": float(parts[4]),
                })
            except ValueError:
                continue
    return gpus


def temperatures() -> float | None:
    try:
        temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    best = None
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
        for entry in temps.get(key, []):
            if entry.current and (best is None or entry.current > best):
                best = entry.current
    return best


def snapshot(include_processes: bool = False) -> dict:
    global _init
    if not _init:
        psutil.cpu_percent(None)
        _init = True
    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(_main_disk())
        disk_info = {"percent": disk.percent, "used_gb": disk.used / 1e9, "total_gb": disk.total / 1e9}
    except OSError:
        disk_info = {"percent": 0, "used_gb": 0, "total_gb": 0}
    up, down = _net_rates()
    battery = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery = {"percent": round(b.percent), "plugged": bool(b.power_plugged),
                       "secs_left": b.secsleft if b.secsleft and b.secsleft > 0 else None}
    except (AttributeError, OSError):
        pass
    data = {
        "ts": time.time(),
        "cpu": psutil.cpu_percent(None),
        "cpu_cores": psutil.cpu_percent(None, percpu=True),
        "cpu_freq": (psutil.cpu_freq().current if psutil.cpu_freq() else None),
        "ram": {"percent": vm.percent, "used_gb": (vm.total - vm.available) / 1e9, "total_gb": vm.total / 1e9},
        "disk": disk_info,
        "net": {"up_bps": up, "down_bps": down},
        "battery": battery,
        "temp_c": temperatures(),
        "uptime_s": time.time() - psutil.boot_time(),
        "process_count": len(psutil.pids()),
    }
    if include_processes:
        data["top_processes"] = top_processes(6)
    return data


def top_processes(limit: int = 10, sort_by: str = "cpu", name_filter: str = "") -> list[dict]:
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = p.info
            name = info.get("name") or "?"
            if name_filter and name_filter.lower() not in name.lower():
                continue
            mem = info.get("memory_info")
            procs.append({
                "pid": info["pid"],
                "name": name,
                "cpu": round(info.get("cpu_percent") or 0.0, 1),
                "ram_mb": round((mem.rss if mem else 0) / 1e6, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = "ram_mb" if sort_by == "memory" else ("name" if sort_by == "name" else "cpu")
    procs.sort(key=lambda d: d[key], reverse=key != "name")
    return [p for p in procs if p["name"] not in ("System Idle Process", "Idle")][:limit]


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def system_identity() -> dict:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "hostname": socket.gethostname(),
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "python": platform.python_version(),
    }
