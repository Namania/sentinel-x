"""Read the host's health from /proc, /sys/class/thermal and statvfs.

Inside Docker, /proc/stat, /proc/meminfo, /proc/loadavg and /proc/uptime already describe the
host. The thermal zone and the disk must be bind-mounted (see compose.yml).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.server.health import ServerHealth


class SamplingError(RuntimeError):
    """A /proc file is missing or malformed; the caller logs and retries later."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProcfsSampler:
    def __init__(
        self,
        proc: Path,
        thermal: Path,
        disk: Path,
        statvfs: Callable[[Path], Any] = os.statvfs,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._proc = proc
        self._thermal = thermal
        self._disk = disk
        self._statvfs = statvfs
        self._clock = clock
        self._last_cpu: tuple[int, int] | None = None  # (total, idle) jiffies

    def sample(self) -> ServerHealth:
        try:
            cpu_pct = self._cpu_pct()
            mem_total, mem_used = self._memory()
            load_1, load_5, load_15 = self._load()
            uptime_s = self._uptime()
            disk_total, disk_used = self._disk_usage()
        except (OSError, ValueError, IndexError) as exc:
            raise SamplingError(str(exc)) from exc
        return ServerHealth(
            recorded_at=self._clock(),
            cpu_pct=cpu_pct,
            mem_total_bytes=mem_total,
            mem_used_bytes=mem_used,
            disk_total_bytes=disk_total,
            disk_used_bytes=disk_used,
            temperature_c=self._temperature(),
            load_1=load_1,
            load_5=load_5,
            load_15=load_15,
            uptime_s=uptime_s,
        )

    def _read(self, name: str) -> str:
        return (self._proc / name).read_text()

    def _cpu_pct(self) -> float | None:
        fields = [int(v) for v in self._read("stat").splitlines()[0].split()[1:]]
        if len(fields) < 4:
            raise ValueError("cpu line too short")
        # user nice system idle iowait irq softirq steal; guest and guest_nice (fields 9-10) are
        # already folded into user and nice by the kernel, so they would count twice.
        total = sum(fields[:8])
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        previous, self._last_cpu = self._last_cpu, (total, idle)
        if previous is None:
            return None
        d_total = total - previous[0]
        d_idle = idle - previous[1]
        if d_total <= 0:
            return None
        return min(100.0, max(0.0, 100.0 * (1 - d_idle / d_total)))

    def _memory(self) -> tuple[int, int]:
        values: dict[str, int] = {}
        for line in self._read("meminfo").splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) * 1024
        if "MemTotal" not in values or "MemAvailable" not in values:
            raise ValueError("meminfo lacks MemTotal or MemAvailable")
        return values["MemTotal"], values["MemTotal"] - values["MemAvailable"]

    def _load(self) -> tuple[float, float, float]:
        parts = self._read("loadavg").split()
        return float(parts[0]), float(parts[1]), float(parts[2])

    def _uptime(self) -> int:
        return round(float(self._read("uptime").split()[0]))

    def _disk_usage(self) -> tuple[int, int]:
        st = self._statvfs(self._disk)
        total = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return total, used

    def _temperature(self) -> float | None:
        try:
            return int((self._thermal / "thermal_zone0" / "temp").read_text().strip()) / 1000
        except (OSError, ValueError):
            return None
