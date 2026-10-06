# Dashboard écran infra — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Dashboard into a wall screen for the infra team: collapsed sidebar, a live camera card linking to `/camera`, a server-health card (CPU, RAM, disk, SoC temperature, load, uptime) linking to a new `/serveur` page, sensors section unchanged below.

**Architecture:** The API samples `/proc`, `/sys/class/thermal` and `statvfs` every 5 s in a background task (like the MQTT subscriber), keeps a 360-point in-memory ring buffer, exposes it on `GET /server/health` and pushes each sample as a `server.health` WebSocket event on the existing hub. The front gains a generic `useEventStream` hook (sensors and server are two filters of it), a `features/server/` feature, a reusable `CameraStream` extracted from `CameraView`, and a new dashboard layout.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pydantic-settings, pytest; React 19, TypeScript, Recharts 3 via shadcn `chart`, React Router 8, Vitest + MSW 3.

**Spec:** `docs/superpowers/specs/2026-10-06-infra-dashboard-design.md`

## Global Constraints

- Backend: ruff `line-length = 100`, rules `E F I UP B`; tests under `backend/tests/{unit,integration}`; `uv run` for every command; `asyncio_mode = "auto"`.
- Backend: no new dependency; no database table; history is in memory only (`maxlen = 360`, 5 s interval = 30 min).
- Frontend: French UI copy; `cn` from `@/lib/utils`; number formatting through `src/lib/format-number.ts` (`fr-FR`, en dash `–` for missing); Recharts series `isAnimationActive={false}`; `ChartContainer` with `initialDimension` so jsdom renders.
- Frontend toolchain must be green before each commit: `pnpm format && pnpm lint && pnpm typecheck && pnpm test && pnpm build` (run from `frontend/`).
- Colour is never the only signal: every gauge shows its numeric value; thresholds `USAGE_WARN_PCT = 85`, `TEMPERATURE_WARN_C = 70` switch the bar to `var(--destructive)`; normal bar colour `var(--chart-3)`.
- No controls inside a `<Link>` (camera card, server card).
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; branch `feat/infra-dashboard` cut from `main`; linear history.
- Use absolute paths in shell commands (the harness's cwd is unreliable).

## Review Focus

1. `/proc/stat` from a kernel that prints only 4 CPU fields (`cpu 1 2 3 4`): the sampler must treat the missing `iowait` as 0, not crash. Test in Task 2.
2. `HOST_DISK_PATH` pointing at a path that does not exist (bad mount): `statvfs` raises; the monitor must log and keep ticking, and `/server/health` must answer `latest: null` instead of 500. Tests in Tasks 2, 3, 4.
3. A `server.health` event arriving while the history request is still in flight: the point must not be lost nor duplicated once the history lands. Test in Task 7.
4. Navigating Dashboard → Caméra: the dashboard's `CameraStream` must release its `<img>` on unmount so the browser does not keep a second MJPEG connection open. Test in Task 10.
5. The first sample has `cpu_pct: null` and Docker Desktop has no thermal zone: the card shows `–` and the charts skip the point instead of drawing 0. Tests in Tasks 8 and 9.

---

## File structure

Backend (new):
- `backend/src/app/application/server/__init__.py` (empty)
- `backend/src/app/application/server/health.py` — `ServerHealth`, `HealthHistory`, `to_dict`, `to_event`
- `backend/src/app/infrastructure/system/__init__.py` (empty)
- `backend/src/app/infrastructure/system/procfs.py` — `SamplingError`, `ProcfsSampler`
- `backend/src/app/infrastructure/system/monitor.py` — `ServerHealthMonitor`
- `backend/src/app/presentation/http/server.py` — `GET /server/health`

Backend (modified): `infrastructure/config.py`, `presentation/dependencies.py`, `presentation/main.py`, `tests/integration/conftest.py`, `compose.yml`, `README.md`.

Frontend (new):
- `frontend/src/features/realtime/use-event-stream.ts`
- `frontend/src/features/server/server-api.ts`, `use-server-health.ts`, `health-gauge.tsx`, `server-health-card.tsx`, `server-charts.tsx`, `server-detail.tsx`
- `frontend/src/features/camera/camera-stream.tsx`, `camera-card.tsx`
- `frontend/src/pages/server.tsx`, `frontend/src/pages/dashboard.test.tsx`
- `frontend/src/test/server-health.ts` (fixtures)

Frontend (modified): `features/metrics/use-sensor-stream.ts`, `features/metrics/metrics-section.tsx` (+ test), `features/camera/camera-view.tsx`, `pages/dashboard.tsx`, `app/app-shell.tsx`, `app/router.tsx`, `components/app-sidebar.tsx` (+ test), `test/server.ts`.

---

## Task 0: Branch

- [ ] **Step 1: Create the branch from main**

```bash
cd /Users/namania/git/sentinel-x && git checkout -q main && git pull -q --ff-only && git checkout -b feat/infra-dashboard
```

Expected: `Switched to a new branch 'feat/infra-dashboard'`.

---

### Task 1: `ServerHealth` sample and `HealthHistory`

**Files:**
- Create: `backend/src/app/application/server/__init__.py`, `backend/src/app/application/server/health.py`
- Test: `backend/tests/unit/test_health_history.py`

**Interfaces:**
- Produces: `ServerHealth` frozen dataclass (fields below), `to_dict(sample) -> dict[str, Any]`, `to_event(sample) -> dict[str, Any]` (`{"type": "server.health", "data": …}`), `HealthHistory(maxlen=360)` with `append`, `latest`, `points`, `__len__`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_health_history.py
from datetime import UTC, datetime, timedelta

from app.application.server.health import HealthHistory, ServerHealth, to_dict, to_event

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def sample(i: int) -> ServerHealth:
    return ServerHealth(
        recorded_at=T0 + timedelta(seconds=5 * i),
        cpu_pct=None if i == 0 else 10.0 + i,
        mem_total_bytes=8_000,
        mem_used_bytes=2_000 + i,
        disk_total_bytes=64_000,
        disk_used_bytes=20_000,
        temperature_c=48.2,
        load_1=0.42,
        load_5=0.38,
        load_15=0.31,
        uptime_s=86_400 + 5 * i,
    )


def test_history_keeps_the_newest_points_in_order():
    history = HealthHistory(maxlen=3)
    for i in range(5):
        history.append(sample(i))
    assert len(history) == 3
    assert [p.uptime_s for p in history.points()] == [86_410, 86_415, 86_420]
    assert history.latest() == sample(4)


def test_empty_history_has_no_latest():
    history = HealthHistory()
    assert history.latest() is None
    assert history.points() == []
    assert len(history) == 0


def test_to_dict_uses_z_timestamps_and_keeps_nulls():
    data = to_dict(sample(0))
    assert data["recorded_at"] == "2026-10-06T09:00:00Z"
    assert data["cpu_pct"] is None
    assert data["mem_used_bytes"] == 2_000


def test_to_event_wraps_the_sample():
    event = to_event(sample(1))
    assert event["type"] == "server.health"
    assert event["data"]["cpu_pct"] == 11.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_health_history.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.server'`.

- [ ] **Step 3: Implement**

```python
# backend/src/app/application/server/__init__.py
# (empty)
```

```python
# backend/src/app/application/server/health.py
"""Health of the machine hosting the API: one sample every few seconds, kept in memory."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

EVENT_TYPE = "server.health"
DEFAULT_MAXLEN = 360  # 30 min at one sample every 5 s


@dataclass(frozen=True, slots=True)
class ServerHealth:
    recorded_at: datetime
    cpu_pct: float | None  # None on the first sample (no delta yet)
    mem_total_bytes: int
    mem_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    temperature_c: float | None  # None when the host exposes no thermal zone
    load_1: float
    load_5: float
    load_15: float
    uptime_s: int


def to_dict(sample: ServerHealth) -> dict[str, Any]:
    """JSON-safe payload, same shape as the REST response."""
    data = asdict(sample)
    data["recorded_at"] = sample.recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return data


def to_event(sample: ServerHealth) -> dict[str, Any]:
    return {"type": EVENT_TYPE, "data": to_dict(sample)}


class HealthHistory:
    """Ring buffer of the most recent samples, oldest first."""

    def __init__(self, maxlen: int = DEFAULT_MAXLEN) -> None:
        self._points: deque[ServerHealth] = deque(maxlen=maxlen)

    def append(self, sample: ServerHealth) -> None:
        self._points.append(sample)

    def latest(self) -> ServerHealth | None:
        return self._points[-1] if self._points else None

    def points(self) -> list[ServerHealth]:
        return list(self._points)

    def __len__(self) -> int:
        return len(self._points)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_health_history.py -q && uv run ruff check . && uv run ruff format --check .`
Expected: `4 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/application/server backend/tests/unit/test_health_history.py && git commit -q -m "$(cat <<'EOF'
feat(server): in-memory server health sample and history

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `ProcfsSampler`

**Files:**
- Create: `backend/src/app/infrastructure/system/__init__.py`, `backend/src/app/infrastructure/system/procfs.py`
- Test: `backend/tests/unit/test_procfs_sampler.py`

**Interfaces:**
- Consumes: `ServerHealth` from Task 1.
- Produces: `SamplingError(RuntimeError)`; `ProcfsSampler(proc: Path, thermal: Path, disk: Path, statvfs=os.statvfs, clock=lambda: datetime.now(UTC))` with `sample() -> ServerHealth` (synchronous).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_procfs_sampler.py
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.system.procfs import ProcfsSampler, SamplingError

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)

STAT_1 = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 200 1300 200 0 0 0 0 0\ncpu0 100 0 100 650 100 0 0 0 0 0\n"
MEMINFO = "MemTotal:        8000000 kB\nMemFree:         1000000 kB\nMemAvailable:    6000000 kB\n"
LOADAVG = "0.42 0.38 0.31 1/234 5678\n"
UPTIME = "86400.55 300000.00\n"


def fake_statvfs(_: Path) -> SimpleNamespace:
    return SimpleNamespace(f_blocks=1000, f_bfree=250, f_bavail=200, f_frsize=4096)


@pytest.fixture
def host(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text(STAT_1)
    (proc / "meminfo").write_text(MEMINFO)
    (proc / "loadavg").write_text(LOADAVG)
    (proc / "uptime").write_text(UPTIME)
    zone = tmp_path / "thermal" / "thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "temp").write_text("48200\n")
    (tmp_path / "root").mkdir()
    return tmp_path


def make_sampler(host: Path, **overrides) -> ProcfsSampler:
    kwargs = dict(
        proc=host / "proc",
        thermal=host / "thermal",
        disk=host / "root",
        statvfs=fake_statvfs,
        clock=lambda: NOW,
    )
    kwargs.update(overrides)
    return ProcfsSampler(**kwargs)


def test_first_sample_reads_every_field_but_has_no_cpu_delta(host: Path):
    sample = make_sampler(host).sample()
    assert sample.recorded_at == NOW
    assert sample.cpu_pct is None
    assert (sample.mem_total_bytes, sample.mem_used_bytes) == (8_192_000_000, 2_048_000_000)
    assert (sample.disk_total_bytes, sample.disk_used_bytes) == (4_096_000, 3_072_000)
    assert sample.temperature_c == 48.2
    assert (sample.load_1, sample.load_5, sample.load_15) == (0.42, 0.38, 0.31)
    assert sample.uptime_s == 86_401


def test_second_sample_computes_cpu_from_the_delta(host: Path):
    sampler = make_sampler(host)
    sampler.sample()
    (host / "proc" / "stat").write_text(STAT_2)
    # Δtotal = 900, Δidle = (1300 + 200) - (700 + 100) = 700 → 22.2 %
    assert make_cpu(sampler) == pytest.approx(22.22, abs=0.01)


def make_cpu(sampler: ProcfsSampler) -> float | None:
    return sampler.sample().cpu_pct


def test_unchanged_counters_give_no_cpu_value(host: Path):
    sampler = make_sampler(host)
    sampler.sample()
    assert make_cpu(sampler) is None


def test_four_field_cpu_line_is_accepted(host: Path):
    (host / "proc" / "stat").write_text("cpu 100 0 100 800\n")
    sampler = make_sampler(host)
    sampler.sample()
    (host / "proc" / "stat").write_text("cpu 200 0 200 1500\n")
    # Δtotal = 900, Δidle = 700 → 22.2 %, iowait treated as 0
    assert make_cpu(sampler) == pytest.approx(22.22, abs=0.01)


def test_missing_thermal_zone_means_no_temperature(host: Path):
    sample = make_sampler(host, thermal=host / "nowhere").sample()
    assert sample.temperature_c is None


def test_truncated_meminfo_is_a_sampling_error(host: Path):
    (host / "proc" / "meminfo").write_text("MemTotal:        8000000 kB\n")
    with pytest.raises(SamplingError):
        make_sampler(host).sample()


def test_missing_proc_is_a_sampling_error(host: Path):
    with pytest.raises(SamplingError):
        make_sampler(host, proc=host / "nowhere").sample()


def test_unreadable_disk_path_is_a_sampling_error(host: Path):
    def boom(_: Path):
        raise FileNotFoundError("no such mount")

    with pytest.raises(SamplingError):
        make_sampler(host, statvfs=boom).sample()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_procfs_sampler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.system'`.

- [ ] **Step 3: Implement**

```python
# backend/src/app/infrastructure/system/__init__.py
# (empty)
```

```python
# backend/src/app/infrastructure/system/procfs.py
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
        total = sum(fields)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_procfs_sampler.py -q && uv run ruff check . && uv run ruff format --check .`
Expected: `8 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/infrastructure/system backend/tests/unit/test_procfs_sampler.py && git commit -q -m "$(cat <<'EOF'
feat(server): sample CPU, memory, disk, temperature, load and uptime from /proc and /sys

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `ServerHealthMonitor`

**Files:**
- Create: `backend/src/app/infrastructure/system/monitor.py`
- Test: `backend/tests/unit/test_server_health_monitor.py`

**Interfaces:**
- Consumes: `HealthHistory`, `to_event` (Task 1); `SamplingError` (Task 2); `EventBroadcaster` port (`broadcast(event)`).
- Produces: `ServerHealthMonitor(sampler, history, broadcaster, interval: float = 5.0, sleep=asyncio.sleep)` with `async run() -> None`. `sampler` only needs a synchronous `sample()` method.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_server_health_monitor.py
import asyncio
from datetime import UTC, datetime

import pytest

from app.application.server.health import HealthHistory, ServerHealth
from app.infrastructure.system.monitor import ServerHealthMonitor
from app.infrastructure.system.procfs import SamplingError


def sample(i: int) -> ServerHealth:
    return ServerHealth(
        recorded_at=datetime(2026, 10, 6, 9, 0, 5 * i, tzinfo=UTC),
        cpu_pct=None if i == 0 else 10.0,
        mem_total_bytes=8,
        mem_used_bytes=2,
        disk_total_bytes=64,
        disk_used_bytes=20,
        temperature_c=None,
        load_1=0.1,
        load_5=0.1,
        load_15=0.1,
        uptime_s=i,
    )


class ScriptedSampler:
    """Returns the queued samples in order, raising where an exception is queued."""

    def __init__(self, *script: ServerHealth | Exception) -> None:
        self.script = list(script)

    def sample(self) -> ServerHealth:
        if not self.script:
            raise SamplingError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


def build(sampler: ScriptedSampler):
    history = HealthHistory()
    bus = RecordingBroadcaster()
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)

    monitor = ServerHealthMonitor(sampler, history, bus, interval=5.0, sleep=sleep)
    return monitor, history, bus, delays


async def run_until(monitor: ServerHealthMonitor, predicate, timeout: float = 1.0) -> asyncio.Task:
    task = asyncio.create_task(monitor.run())
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)
    return task


async def test_each_tick_stores_and_broadcasts_a_sample():
    monitor, history, bus, delays = build(ScriptedSampler(sample(0), sample(1)))
    task = await run_until(monitor, lambda: len(bus.events) == 2)
    assert [p.uptime_s for p in history.points()] == [0, 1]
    assert bus.events[1]["type"] == "server.health"
    assert bus.events[1]["data"]["cpu_pct"] == 10.0
    assert delays[:2] == [5.0, 5.0]
    task.cancel()


async def test_a_sampling_error_is_logged_not_fatal(caplog):
    monitor, history, bus, _ = build(ScriptedSampler(SamplingError("no mount"), sample(1)))
    task = await run_until(monitor, lambda: len(bus.events) == 1)
    assert [p.uptime_s for p in history.points()] == [1]
    assert "no mount" in caplog.text
    task.cancel()


async def test_stops_cleanly_when_cancelled():
    monitor, _, _, _ = build(ScriptedSampler(sample(0)))
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_server_health_monitor.py -q`
Expected: FAIL with `ImportError: cannot import name 'ServerHealthMonitor'`.

- [ ] **Step 3: Implement**

```python
# backend/src/app/infrastructure/system/monitor.py
"""Background task: sample the host every `interval` seconds, keep history, push to WebSocket."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.server.health import HealthHistory, ServerHealth, to_event
from app.infrastructure.system.procfs import SamplingError

logger = logging.getLogger(__name__)


class Sampler(Protocol):
    def sample(self) -> ServerHealth: ...


class ServerHealthMonitor:
    def __init__(
        self,
        sampler: Sampler,
        history: HealthHistory,
        broadcaster: EventBroadcaster,
        interval: float = 5.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sampler = sampler
        self._history = history
        self._broadcaster = broadcaster
        self._interval = interval
        self._sleep = sleep

    async def run(self) -> None:
        while True:
            try:
                # statvfs on a struggling disk can block: keep it off the event loop.
                sample = await asyncio.to_thread(self._sampler.sample)
            except SamplingError as exc:
                logger.warning("server health sample failed: %s", exc)
            else:
                self._history.append(sample)
                await self._broadcaster.broadcast(to_event(sample))
            await self._sleep(self._interval)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_server_health_monitor.py -q && uv run ruff check . && uv run ruff format --check .`
Expected: `3 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend/src/app/infrastructure/system/monitor.py backend/tests/unit/test_server_health_monitor.py && git commit -q -m "$(cat <<'EOF'
feat(server): background monitor that samples the host and broadcasts server.health

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Settings, route `GET /server/health`, lifespan wiring, compose mounts

**Files:**
- Modify: `backend/src/app/infrastructure/config.py`, `backend/src/app/presentation/dependencies.py`, `backend/src/app/presentation/main.py`, `backend/tests/integration/conftest.py`, `compose.yml`
- Create: `backend/src/app/presentation/http/server.py`
- Test: `backend/tests/unit/test_settings.py` (append), `backend/tests/integration/test_server_http.py`

**Interfaces:**
- Consumes: `HealthHistory`, `ServerHealth`, `to_dict` (Task 1); `ProcfsSampler` (Task 2); `ServerHealthMonitor` (Task 3); `CurrentUserIdDep`, `get_current_user_id` pattern from `dependencies.py`.
- Produces: settings `host_proc_path`, `host_thermal_path`, `host_disk_path` (`Path`), `server_health_interval_s: float = 5.0`, `server_health_enabled: bool = True`; `app.state.server_health: HealthHistory`; `ServerHealthHistoryDep`; route `GET /server/health` → `{"latest": …|null, "history": […]}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_settings.py`:

```python
def test_server_health_defaults_point_at_the_container_proc():
    from pathlib import Path

    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.host_proc_path == Path("/proc")
    assert settings.host_thermal_path == Path("/sys/class/thermal")
    assert settings.host_disk_path == Path("/")
    assert settings.server_health_interval_s == 5.0
    assert settings.server_health_enabled is True


def test_server_health_paths_come_from_the_environment(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("HOST_DISK_PATH", "/host/root")
    monkeypatch.setenv("HOST_THERMAL_PATH", "/host/thermal")
    settings = Settings(_env_file=None, jwt_secret="x" * 32)
    assert settings.host_disk_path == Path("/host/root")
    assert settings.host_thermal_path == Path("/host/thermal")
```

```python
# backend/tests/integration/test_server_http.py
from datetime import UTC, datetime

from app.application.server.health import HealthHistory, ServerHealth
from tests.integration.conftest import create_user_and_login


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_server_health_requires_a_token(client):
    assert client.get("/server/health").status_code == 401


def test_server_health_is_empty_before_the_first_sample(client, app):
    saved, app.state.server_health = app.state.server_health, HealthHistory()
    try:
        response = client.get("/server/health", headers=auth(create_user_and_login(client)))
        assert response.status_code == 200
        assert response.json() == {"latest": None, "history": []}
    finally:
        app.state.server_health = saved


def test_server_health_returns_the_latest_sample_and_the_history(client, app):
    history = HealthHistory()
    history.append(
        ServerHealth(
            recorded_at=datetime(2026, 10, 6, 9, 0, 5, tzinfo=UTC),
            cpu_pct=12.5,
            mem_total_bytes=8_589_934_592,
            mem_used_bytes=2_147_483_648,
            disk_total_bytes=62_000_000_000,
            disk_used_bytes=21_000_000_000,
            temperature_c=48.2,
            load_1=0.42,
            load_5=0.38,
            load_15=0.31,
            uptime_s=86_400,
        )
    )
    saved, app.state.server_health = app.state.server_health, history
    try:
        body = client.get("/server/health", headers=auth(create_user_and_login(client))).json()
    finally:
        app.state.server_health = saved
    assert body["latest"]["cpu_pct"] == 12.5
    assert body["latest"]["recorded_at"].startswith("2026-10-06T09:00:05")
    assert body["latest"]["temperature_c"] == 48.2
    assert body["history"] == [body["latest"]]


def test_openapi_lists_server_health(client):
    schema = client.get("/openapi.json").json()
    assert "/server/health" in schema["paths"]
    assert schema["paths"]["/server/health"]["get"]["tags"] == ["server"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run pytest tests/unit/test_settings.py tests/integration/test_server_http.py -q`
Expected: settings tests FAIL with `AttributeError: 'Settings' object has no attribute 'host_proc_path'`; integration tests FAIL with 404 / `AttributeError: server_health` (the integration suite needs the test Postgres: `docker compose up -d db` first if it is not running).

- [ ] **Step 3: Settings**

In `backend/src/app/infrastructure/config.py`, add `from pathlib import Path` to the imports and, after the MQTT block:

```python
    # Host health shown on the dashboard. /proc inside Docker already describes the host; the
    # thermal zone and the disk are bind-mounted by compose.yml (see HOST_* there).
    host_proc_path: Path = Path("/proc")
    host_thermal_path: Path = Path("/sys/class/thermal")
    host_disk_path: Path = Path("/")
    server_health_interval_s: float = 5.0
    server_health_enabled: bool = True
```

- [ ] **Step 4: Dependency**

In `backend/src/app/presentation/dependencies.py`, import `from app.application.server.health import HealthHistory` and add after `get_camera_relay`:

```python
def get_server_health_history(conn: HTTPConnection) -> HealthHistory:
    return conn.app.state.server_health
```

At the bottom of the file, where the `*Dep` aliases are defined (search for `CurrentUserIdDep = `), add:

```python
ServerHealthHistoryDep = Annotated[HealthHistory, Depends(get_server_health_history)]
```

- [ ] **Step 5: Route**

```python
# backend/src/app/presentation/http/server.py
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.application.server.health import ServerHealth, to_dict
from app.presentation.dependencies import CurrentUserIdDep, ServerHealthHistoryDep

router = APIRouter(prefix="/server", tags=["server"])


class ServerHealthResponse(BaseModel):
    recorded_at: datetime
    cpu_pct: float | None
    mem_total_bytes: int
    mem_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    temperature_c: float | None
    load_1: float
    load_5: float
    load_15: float
    uptime_s: int

    @classmethod
    def from_sample(cls, sample: ServerHealth) -> "ServerHealthResponse":
        return cls(**to_dict(sample))


class ServerHealthEnvelope(BaseModel):
    latest: ServerHealthResponse | None
    history: list[ServerHealthResponse]


@router.get(
    "/health",
    response_model=ServerHealthEnvelope,
    summary="Santé du serveur : CPU, mémoire, disque, température, charge, uptime",
    description="Dernier échantillon et les 30 dernières minutes (un point toutes les 5 s), "
    "gardés en mémoire. Vide tant que le premier échantillon n'a pas abouti.",
)
async def get_server_health(
    _: CurrentUserIdDep, history: ServerHealthHistoryDep
) -> ServerHealthEnvelope:
    latest = history.latest()
    return ServerHealthEnvelope(
        latest=ServerHealthResponse.from_sample(latest) if latest else None,
        history=[ServerHealthResponse.from_sample(p) for p in history.points()],
    )
```

- [ ] **Step 6: Lifespan wiring in `main.py`**

Add imports:

```python
from app.application.server.health import HealthHistory
from app.infrastructure.system.monitor import ServerHealthMonitor
from app.infrastructure.system.procfs import ProcfsSampler
from app.presentation.http import auth, camera, health, sensors, server, users
```

Replace the lifespan body and add the monitor starter:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [
            task
            for task in (_start_mqtt_subscriber(app, settings), _start_server_health(app, settings))
            if task is not None
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await engine.dispose()
```

After `app.state.camera_relay = …`:

```python
    app.state.server_health = HealthHistory()
```

After `app.include_router(sensors.router)`:

```python
    app.include_router(server.router)
```

New helper at the end of the file:

```python
def _start_server_health(app: FastAPI, settings: Settings) -> asyncio.Task[None] | None:
    """Sample the host every few seconds for the dashboard's server card. Disabled in tests."""
    if not settings.server_health_enabled:
        return None
    monitor = ServerHealthMonitor(
        sampler=ProcfsSampler(
            proc=settings.host_proc_path,
            thermal=settings.host_thermal_path,
            disk=settings.host_disk_path,
        ),
        history=app.state.server_health,
        broadcaster=app.state.hub,
        interval=settings.server_health_interval_s,
    )
    return asyncio.create_task(monitor.run(), name="server-health-monitor")
```

- [ ] **Step 7: Test settings and compose**

In `backend/tests/integration/conftest.py`, add `server_health_enabled=False,` to `TEST_SETTINGS` (after `device_api_key=…`). The test machine may have no `/proc` (macOS), and a sampler ticking during tests would only add noise.

In `compose.yml`, service `api`, add after `environment:` entries and a `volumes:` block:

```yaml
    environment:
      API_ROOT_PATH: /api
      MQTT_HOST: mosquitto
      HOST_THERMAL_PATH: /host/thermal
      HOST_DISK_PATH: /host/root
    volumes:
      # Host health for the dashboard: SoC temperature and root disk usage, read-only.
      - /sys/class/thermal:/host/thermal:ro
      - /:/host/root:ro
```

- [ ] **Step 8: Run the whole backend suite**

Run: `cd /Users/namania/git/sentinel-x/backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q && cd /Users/namania/git/sentinel-x && docker compose config -q && docker compose -f compose.yml -f compose.dev.yml config -q`
Expected: ruff clean, all tests pass (previous 156 + 4 + 8 + 3 + 2 + 4 = 177), both compose configs valid.

- [ ] **Step 9: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add backend compose.yml && git commit -q -m "$(cat <<'EOF'
feat(server): GET /server/health, monitor started with the app, host mounts in compose

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Generic `useEventStream`, `useSensorStream` as a wrapper

**Files:**
- Create: `frontend/src/features/realtime/use-event-stream.ts`
- Modify: `frontend/src/features/metrics/use-sensor-stream.ts`
- Test: existing `frontend/src/features/metrics/use-sensor-stream.test.tsx` must stay green.

**Interfaces:**
- Produces: `useEventStream(enabled: boolean, onEvent: (type: string, data: unknown) => void): { connected: boolean }`, `RECONNECT_DELAYS_MS`, `streamUrl(token)` (moved). `useSensorStream(enabled, onReading)` keeps its signature and re-exports `RECONNECT_DELAYS_MS`.

- [ ] **Step 1: Run the existing stream tests to record the baseline**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/metrics/use-sensor-stream.test.tsx`
Expected: all pass (this is a refactor; the tests are the safety net).

- [ ] **Step 2: Create the generic hook**

```ts
// frontend/src/features/realtime/use-event-stream.ts
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";

export const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000] as const;

export function streamUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
}

/**
 * The app WebSocket: every message is `{ type, data }`. Reconnects with growing waits, reopens
 * when the access token changes, closes on unmount or when disabled. Callers filter by `type`.
 */
export function useEventStream(enabled: boolean, onEvent: (type: string, data: unknown) => void) {
  const { accessToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled || !accessToken) return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(streamUrl(accessToken));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as { type?: unknown; data?: unknown };
          if (typeof message.type === "string") onEventRef.current(message.type, message.data);
        } catch {
          // Not JSON: ignore.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]!;
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
      setConnected(false);
    };
  }, [enabled, accessToken]);

  return { connected };
}
```

- [ ] **Step 3: Rewrite `useSensorStream` on top of it**

Replace the whole content of `frontend/src/features/metrics/use-sensor-stream.ts` with:

```ts
import { useCallback } from "react";
import { useEventStream } from "@/features/realtime/use-event-stream";
import type { Reading } from "./metrics-api";

export { RECONNECT_DELAYS_MS, streamUrl } from "@/features/realtime/use-event-stream";

/** `sensor.reading` events of the app WebSocket. */
export function useSensorStream(enabled: boolean, onReading: (reading: Reading) => void) {
  const onEvent = useCallback(
    (type: string, data: unknown) => {
      if (type === "sensor.reading" && data) onReading(data as Reading);
    },
    [onReading],
  );
  return useEventStream(enabled, onEvent);
}
```

- [ ] **Step 4: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: lint clean, typecheck clean, `99 passed` (unchanged count).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/realtime frontend/src/features/metrics/use-sensor-stream.ts && git commit -q -m "$(cat <<'EOF'
refactor(frontend): generic useEventStream, sensors as one filter of it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `server-api.ts` helpers and test fixtures

**Files:**
- Create: `frontend/src/features/server/server-api.ts`, `frontend/src/test/server-health.ts`
- Modify: `frontend/src/test/server.ts` (MSW handler)
- Test: `frontend/src/features/server/server-api.test.ts`

**Interfaces:**
- Produces: types `ServerHealth`, `ServerHealthResponse`; constants `SERVER_HEALTH_PATH = "/server/health"`, `HISTORY_MAXLEN = 360`, `USAGE_WARN_PCT = 85`, `TEMPERATURE_WARN_C = 70`; `appendHealth(history, sample, maxlen?)`, `ratio(used, total): number | null`, `formatPct(value: number | null)`, `formatBytes(n)`, `formatBytesPair(used, total)`, `formatUptime(s)`, `formatTemperature(c: number | null)`. Fixtures: `makeHealth(overrides?)`, `healthFixture(n, endMs, stepMs = 5000)`, `SERVER_NOW_MS`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/server/server-api.test.ts
import { describe, expect, it } from "vitest";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import {
  appendHealth,
  formatBytes,
  formatBytesPair,
  formatPct,
  formatTemperature,
  formatUptime,
  ratio,
} from "./server-api";

describe("server api helpers", () => {
  it("appends newer samples and drops the oldest beyond maxlen", () => {
    const history = healthFixture(3, SERVER_NOW_MS);
    const next = makeHealth({ recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString() });
    const result = appendHealth(history, next, 3);
    expect(result).toHaveLength(3);
    expect(result.at(-1)).toBe(next);
    expect(result[0]).toBe(history[1]);
  });

  it("ignores a sample that is not newer than the last one", () => {
    const history = healthFixture(2, SERVER_NOW_MS);
    const duplicate = makeHealth({ recorded_at: history[1]!.recorded_at });
    expect(appendHealth(history, duplicate)).toBe(history);
  });

  it("computes a usage ratio, null without a total", () => {
    expect(ratio(2, 8)).toBeCloseTo(0.25);
    expect(ratio(0, 0)).toBeNull();
  });

  it("formats percentages, bytes, temperatures and uptimes in French", () => {
    expect(formatPct(12.49)).toBe("12 %");
    expect(formatPct(null)).toBe("–");
    expect(formatBytes(2 * 2 ** 30)).toBe("2,0 Gio");
    expect(formatBytesPair(2 * 2 ** 30, 8 * 2 ** 30)).toBe("2,0 / 8,0 Gio");
    expect(formatTemperature(48.26)).toBe("48,3 °C");
    expect(formatTemperature(null)).toBe("–");
    expect(formatUptime(3 * 86_400 + 4 * 3600 + 7 * 60)).toBe("3 j 4 h");
    expect(formatUptime(4 * 3600 + 12 * 60)).toBe("4 h 12 min");
    expect(formatUptime(12 * 60 + 30)).toBe("12 min");
    expect(formatUptime(30)).toBe("< 1 min");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/server/server-api.test.ts`
Expected: FAIL, `Failed to resolve import "@/test/server-health"`.

- [ ] **Step 3: Implement the helpers**

```ts
// frontend/src/features/server/server-api.ts
import { formatNumber } from "@/lib/format-number";

export type ServerHealth = {
  recorded_at: string;
  cpu_pct: number | null;
  mem_total_bytes: number;
  mem_used_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  temperature_c: number | null;
  load_1: number;
  load_5: number;
  load_15: number;
  uptime_s: number;
};

export type ServerHealthResponse = { latest: ServerHealth | null; history: ServerHealth[] };

export const SERVER_HEALTH_PATH = "/server/health";
export const HISTORY_MAXLEN = 360;
/** Above these, a gauge's bar turns to the destructive colour; the value is always shown too. */
export const USAGE_WARN_PCT = 85;
export const TEMPERATURE_WARN_C = 70;

/** History plus one live sample, oldest first, bounded; not-newer samples are ignored. */
export function appendHealth(
  history: ServerHealth[],
  sample: ServerHealth,
  maxlen = HISTORY_MAXLEN,
): ServerHealth[] {
  const last = history.at(-1);
  if (last && Date.parse(sample.recorded_at) <= Date.parse(last.recorded_at)) return history;
  return [...history, sample].slice(-maxlen);
}

export function ratio(used: number, total: number): number | null {
  return total > 0 ? used / total : null;
}

export function formatPct(value: number | null): string {
  return value === null ? "–" : `${formatNumber(value, 0)} %`;
}

export function formatBytes(bytes: number): string {
  return `${formatNumber(bytes / 2 ** 30, 1)} Gio`;
}

/** "2,0 / 8,0 Gio" — used and total share the unit. */
export function formatBytesPair(used: number, total: number): string {
  return `${formatNumber(used / 2 ** 30, 1)} / ${formatNumber(total / 2 ** 30, 1)} Gio`;
}

export function formatTemperature(celsius: number | null): string {
  return celsius === null ? "–" : `${formatNumber(celsius, 1)} °C`;
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days} j ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min`;
  return "< 1 min";
}
```

- [ ] **Step 4: Fixtures and MSW handler**

```ts
// frontend/src/test/server-health.ts
import type { ServerHealth } from "@/features/server/server-api";

export const SERVER_NOW_MS = Date.UTC(2026, 9, 6, 9, 0, 0);

export function makeHealth(overrides: Partial<ServerHealth> = {}): ServerHealth {
  return {
    recorded_at: new Date(SERVER_NOW_MS).toISOString(),
    cpu_pct: 12.5,
    mem_total_bytes: 8 * 2 ** 30,
    mem_used_bytes: 2 * 2 ** 30,
    disk_total_bytes: 64 * 2 ** 30,
    disk_used_bytes: 20 * 2 ** 30,
    temperature_c: 48.2,
    load_1: 0.42,
    load_5: 0.38,
    load_15: 0.31,
    uptime_s: 3 * 86_400 + 4 * 3600,
    ...overrides,
  };
}

/** n samples `stepMs` apart ending at `endMs`; the first one has no CPU value, like the real API. */
export function healthFixture(n: number, endMs: number, stepMs = 5000): ServerHealth[] {
  return Array.from({ length: n }, (_, i) =>
    makeHealth({
      recorded_at: new Date(endMs - (n - 1 - i) * stepMs).toISOString(),
      cpu_pct: i === 0 ? null : 10 + i,
      uptime_s: 3 * 86_400 + 4 * 3600 + (i * stepMs) / 1000,
    }),
  );
}
```

In `frontend/src/test/server.ts`, import `healthFixture, SERVER_NOW_MS` from `./server-health` and add to `handlers` (after the camera status handler):

```ts
  http.get("/api/server/health", ({ request }) => {
    if (!isValidAccessToken(bearer(request))) return unauthenticated();
    const history = healthFixture(4, SERVER_NOW_MS);
    return HttpResponse.json({ latest: history.at(-1) ?? null, history });
  }),
```

- [ ] **Step 5: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: all tests pass (103 with the new ones).

- [ ] **Step 6: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/server/server-api.ts frontend/src/features/server/server-api.test.ts frontend/src/test/server-health.ts frontend/src/test/server.ts && git commit -q -m "$(cat <<'EOF'
feat(frontend): server health types, formatting helpers and test fixtures

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `useServerHealth`

**Files:**
- Create: `frontend/src/features/server/use-server-health.ts`
- Test: `frontend/src/features/server/use-server-health.test.tsx`

**Interfaces:**
- Consumes: `useEventStream` (Task 5); `appendHealth`, `SERVER_HEALTH_PATH`, types (Task 6); `useAuth().authFetch<T>(path)`.
- Produces: `useServerHealth(enabled = true): { status: "loading" | "ready" | "error"; latest: ServerHealth | null; history: ServerHealth[]; connected: boolean }`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/server/use-server-health.test.tsx
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import { useServerHealth } from "./use-server-health";

function Probe() {
  const { status, latest, history, connected } = useServerHealth();
  return (
    <div>
      <p>status:{status}</p>
      <p>connected:{String(connected)}</p>
      <p>count:{history.length}</p>
      <p>uptime:{latest?.uptime_s ?? "-"}</p>
    </div>
  );
}

function renderProbe() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("useServerHealth", () => {
  it("loads the history then applies server.health events", async () => {
    let send: ((data: string) => void) | null = null;
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        send = (data) => client.send(data);
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("count:4")).toBeInTheDocument();
    await screen.findByText("connected:true");
    send!(
      JSON.stringify({
        type: "server.health",
        data: makeHealth({
          recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString(),
          uptime_s: 999,
        }),
      }),
    );
    expect(await screen.findByText("uptime:999")).toBeInTheDocument();
    expect(screen.getByText("count:5")).toBeInTheDocument();
  });

  it("keeps an event received while the history is loading", async () => {
    server.use(
      http.get("/api/server/health", async () => {
        await wait(150);
        const history = healthFixture(4, SERVER_NOW_MS);
        return HttpResponse.json({ latest: history.at(-1), history });
      }),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(
          JSON.stringify({
            type: "server.health",
            data: makeHealth({
              recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString(),
              uptime_s: 777,
            }),
          }),
        );
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(await screen.findByText("uptime:777")).toBeInTheDocument();
    expect(screen.getByText("count:5")).toBeInTheDocument();
  });

  it("ignores other event types", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "sensor.reading", data: { uptime_s: 1 } }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    await wait(100);
    expect(screen.getByText("count:4")).toBeInTheDocument();
  });

  it("reports an error when the history cannot be loaded", async () => {
    server.use(http.get("/api/server/health", () => HttpResponse.error()));
    renderProbe();
    expect(await screen.findByText("status:error")).toBeInTheDocument();
    expect(screen.getByText("uptime:-")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/server/use-server-health.test.tsx`
Expected: FAIL, `Failed to resolve import "./use-server-health"`.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/server/use-server-health.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { useEventStream } from "@/features/realtime/use-event-stream";
import {
  appendHealth,
  SERVER_HEALTH_PATH,
  type ServerHealth,
  type ServerHealthResponse,
} from "./server-api";

type Status = "loading" | "ready" | "error";

/** Server health history (30 min) kept up to date by `server.health` WebSocket events. */
export function useServerHealth(enabled = true) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [history, setHistory] = useState<ServerHealth[]>([]);
  // Events that arrive before the history response; merged once it lands.
  const pending = useRef<ServerHealth[]>([]);
  const loaded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    loaded.current = false;
    authFetch<ServerHealthResponse>(SERVER_HEALTH_PATH)
      .then((response) => {
        if (cancelled) return;
        const merged = pending.current.reduce(appendHealth, response.history);
        pending.current = [];
        loaded.current = true;
        setHistory(merged);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const onEvent = useCallback((type: string, data: unknown) => {
    if (type !== "server.health" || !data) return;
    const sample = data as ServerHealth;
    if (!loaded.current) {
      pending.current = appendHealth(pending.current, sample);
      return;
    }
    setHistory((current) => appendHealth(current, sample));
  }, []);
  const { connected } = useEventStream(enabled, onEvent);

  return { status, latest: history.at(-1) ?? null, history, connected };
}
```

- [ ] **Step 4: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: all tests pass (107 with the new ones).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/server/use-server-health.ts frontend/src/features/server/use-server-health.test.tsx && git commit -q -m "$(cat <<'EOF'
feat(frontend): useServerHealth loads the history and follows server.health events

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `HealthGauge` and `ServerHealthCard`

**Files:**
- Create: `frontend/src/features/server/health-gauge.tsx`, `frontend/src/features/server/server-health-card.tsx`
- Test: `frontend/src/features/server/server-health-card.test.tsx`

**Interfaces:**
- Consumes: `useServerHealth` (Task 7); helpers and thresholds (Task 6); `Card*`, `Skeleton`, `ChartContainer` from `@/components/ui`.
- Produces: `HealthGauge({ label, valueText, ratio, warn, series }: { label: string; valueText: string; ratio: number | null; warn: boolean; series: (number | null)[] })`; `ServerHealthCard({ className? })` (a `Link` to `/serveur`).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/server/server-health-card.test.tsx
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import { ServerHealthCard } from "./server-health-card";

function renderCard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([
    { path: "/", element: <ServerHealthCard /> },
    { path: "/serveur", element: <h1>Serveur</h1> },
  ]);
}

async function card() {
  renderCard();
  return within(await screen.findByRole("link", { name: "Santé du serveur, voir le détail" }));
}

describe("ServerHealthCard", () => {
  it("links to the server page and shows the four gauges with their values", async () => {
    const link = await card();
    expect(screen.getByRole("link", { name: "Santé du serveur, voir le détail" })).toHaveAttribute(
      "href",
      "/serveur",
    );
    const cpu = within(await link.findByRole("group", { name: "CPU" }));
    expect(cpu.getByText("13 %")).toBeInTheDocument();
    expect(within(link.getByRole("group", { name: "Mémoire" })).getByText("2,0 / 8,0 Gio"));
    expect(within(link.getByRole("group", { name: "Disque" })).getByText("20,0 / 64,0 Gio"));
    expect(within(link.getByRole("group", { name: "Température" })).getByText("48,2 °C"));
    expect(link.getByText("Charge 0,42 · 0,38 · 0,31")).toBeInTheDocument();
    expect(link.getByText("Démarré depuis 3 j 4 h")).toBeInTheDocument();
  });

  it("shows dashes when CPU and temperature are unknown", async () => {
    server.use(
      http.get("/api/server/health", () => {
        const history = [makeHealth({ cpu_pct: null, temperature_c: null })];
        return HttpResponse.json({ latest: history[0], history });
      }),
    );
    const link = await card();
    expect(within(await link.findByRole("group", { name: "CPU" })).getByText("–"));
    expect(within(link.getByRole("group", { name: "Température" })).getByText("–"));
  });

  it("marks a gauge above its threshold without hiding the value", async () => {
    server.use(
      http.get("/api/server/health", () => {
        const history = healthFixture(2, SERVER_NOW_MS).map((h) => ({ ...h, cpu_pct: 92 }));
        return HttpResponse.json({ latest: history.at(-1), history });
      }),
    );
    const link = await card();
    const cpu = within(await link.findByRole("group", { name: "CPU" }));
    expect(cpu.getByText("92 %")).toBeInTheDocument();
    expect(cpu.getByRole("progressbar")).toHaveAttribute("data-warn", "true");
    expect(cpu.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "92");
  });

  it("shows a skeleton while loading and a message on error", async () => {
    server.use(http.get("/api/server/health", () => HttpResponse.error()));
    renderCard();
    expect(await screen.findByRole("status", { name: "Chargement de la santé du serveur" }));
    expect(await screen.findByText("Santé du serveur indisponible")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Santé du serveur, voir le détail" })).toHaveAttribute(
      "href",
      "/serveur",
    );
  });
});
```

`card()` renders the card itself; the loading/error test calls `renderCard()` directly because it
asserts on the skeleton before the link's content settles.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/server/server-health-card.test.tsx`
Expected: FAIL, `Failed to resolve import "./server-health-card"`.

- [ ] **Step 3: Implement the gauge**

```tsx
// frontend/src/features/server/health-gauge.tsx
import { Area, AreaChart } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { cn } from "@/lib/utils";

type Props = {
  label: string;
  valueText: string;
  /** 0..1 fill of the bar, null when unknown. */
  ratio: number | null;
  warn: boolean;
  /** Last 30 min of the metric, oldest first; null points are skipped. */
  series: (number | null)[];
};

const sparkConfig = { v: { label: "", color: "var(--chart-3)" } } satisfies ChartConfig;
const sparkDimension = { width: 120, height: 28 };

/** A compact gauge: label, value, bar, sparkline. Colour is never the only signal. */
export function HealthGauge({ label, valueText, ratio, warn, series }: Props) {
  const pct = ratio === null ? null : Math.round(Math.min(1, Math.max(0, ratio)) * 100);
  const data = series.map((v, i) => ({ i, v }));
  return (
    <div role="group" aria-label={label} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-right text-sm font-semibold tabular-nums">{valueText}</p>
      <div
        role="progressbar"
        aria-label={`${label} : ${valueText}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
        data-warn={warn ? "true" : "false"}
        className="bg-muted h-1.5 w-full self-center overflow-hidden rounded-full"
      >
        <div
          className={cn("h-full rounded-full", warn ? "bg-destructive" : "bg-[var(--chart-3)]")}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
      <ChartContainer
        config={sparkConfig}
        className="h-7 w-[120px] [&_svg]:overflow-visible"
        initialDimension={sparkDimension}
      >
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Area
            dataKey="v"
            type="monotone"
            stroke={warn ? "var(--destructive)" : "var(--chart-3)"}
            fill={warn ? "var(--destructive)" : "var(--chart-3)"}
            fillOpacity={0.15}
            strokeWidth={1.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartContainer>
    </div>
  );
}
```

- [ ] **Step 4: Implement the card**

```tsx
// frontend/src/features/server/server-health-card.tsx
import { Link } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/format-number";
import { cn } from "@/lib/utils";
import { HealthGauge } from "./health-gauge";
import {
  formatBytesPair,
  formatPct,
  formatTemperature,
  formatUptime,
  ratio,
  TEMPERATURE_WARN_C,
  USAGE_WARN_PCT,
  type ServerHealth,
} from "./server-api";
import { useServerHealth } from "./use-server-health";

const WARN_RATIO = USAGE_WARN_PCT / 100;

/** "Charge 0,42 · 0,38 · 0,31" as one text node so tests and screen readers get one phrase. */
export function loadLabel(h: ServerHealth): string {
  return `Charge ${formatNumber(h.load_1, 2)} · ${formatNumber(h.load_5, 2)} · ${formatNumber(h.load_15, 2)}`;
}

function Gauges({ latest, history }: { latest: ServerHealth; history: ServerHealth[] }) {
  const mem = ratio(latest.mem_used_bytes, latest.mem_total_bytes);
  const disk = ratio(latest.disk_used_bytes, latest.disk_total_bytes);
  const cpu = latest.cpu_pct === null ? null : latest.cpu_pct / 100;
  return (
    <>
      <HealthGauge
        label="CPU"
        valueText={formatPct(latest.cpu_pct)}
        ratio={cpu}
        warn={(latest.cpu_pct ?? 0) >= USAGE_WARN_PCT}
        series={history.map((h) => h.cpu_pct)}
      />
      <HealthGauge
        label="Mémoire"
        valueText={formatBytesPair(latest.mem_used_bytes, latest.mem_total_bytes)}
        ratio={mem}
        warn={(mem ?? 0) >= WARN_RATIO}
        series={history.map((h) => ratio(h.mem_used_bytes, h.mem_total_bytes))}
      />
      <HealthGauge
        label="Disque"
        valueText={formatBytesPair(latest.disk_used_bytes, latest.disk_total_bytes)}
        ratio={disk}
        warn={(disk ?? 0) >= WARN_RATIO}
        series={history.map((h) => ratio(h.disk_used_bytes, h.disk_total_bytes))}
      />
      <HealthGauge
        label="Température"
        valueText={formatTemperature(latest.temperature_c)}
        ratio={latest.temperature_c === null ? null : latest.temperature_c / 100}
        warn={(latest.temperature_c ?? 0) >= TEMPERATURE_WARN_C}
        series={history.map((h) => h.temperature_c)}
      />
    </>
  );
}

/** Wall-screen card: the host's health at a glance; the whole card opens the detail page. */
export function ServerHealthCard({ className }: { className?: string }) {
  const { status, latest, history, connected } = useServerHealth();
  return (
    <Link
      to="/serveur"
      aria-label="Santé du serveur, voir le détail"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium">Serveur</CardTitle>
          <span className="flex items-center gap-1.5 text-xs">
            <span
              className={cn("inline-block size-2 rounded-full", connected ? "bg-emerald-500" : "bg-muted-foreground/50")}
              aria-hidden="true"
            />
            <span className="sr-only">{connected ? "temps réel actif" : "temps réel interrompu"}</span>
          </span>
        </CardHeader>
        <CardContent className="space-y-3">
          {status === "loading" && (
            <Skeleton role="status" aria-label="Chargement de la santé du serveur" className="h-40 w-full" />
          )}
          {status === "error" && (
            <p className="text-destructive text-sm">Santé du serveur indisponible</p>
          )}
          {status === "ready" && latest && <Gauges latest={latest} history={history} />}
          {status === "ready" && !latest && (
            <p className="text-muted-foreground text-sm">En attente du premier échantillon…</p>
          )}
          {latest && (
            <div className="text-muted-foreground text-xs tabular-nums">
              <p>{loadLabel(latest)}</p>
              <p>Démarré depuis {formatUptime(latest.uptime_s)}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
```

- [ ] **Step 5: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: all tests pass (111 with the new ones). If `ChartContainer` children typing rejects a bare `AreaChart`, keep it: that is how `charts.tsx` already uses it.

- [ ] **Step 6: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/server && git commit -q -m "$(cat <<'EOF'
feat(frontend): server health card with CPU, memory, disk and temperature gauges

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `/serveur` page: charts, route, nav entry

**Files:**
- Create: `frontend/src/features/server/server-charts.tsx`, `frontend/src/features/server/server-detail.tsx`, `frontend/src/pages/server.tsx`
- Modify: `frontend/src/app/router.tsx`, `frontend/src/app/app-shell.tsx` (TITLES), `frontend/src/components/app-sidebar.tsx` (nav item)
- Test: `frontend/src/features/server/server-detail.test.tsx`, `frontend/src/components/app-sidebar.test.tsx` (extend)

**Interfaces:**
- Consumes: `useServerHealth` (Task 7), helpers (Task 6), `tooltipTimeLabel` from `@/features/metrics/tooltip-label`, `ChartContainer`, `ChartTooltip`, `ChartTooltipContent`.
- Produces: `toServerPoints(history): ServerPoint[]` with `ServerPoint = { time: number; cpu: number | null; memGib: number; temp: number | null }`; `ServerCharts({ history })`; `ServerDetail()`; `ServerPage()`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/server/server-detail.test.tsx
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { VALID_REFRESH } from "@/test/server";
import { healthFixture, SERVER_NOW_MS } from "@/test/server-health";
import { toServerPoints } from "./server-charts";
import { ServerDetail } from "./server-detail";

describe("toServerPoints", () => {
  it("maps samples to chart points, keeping unknown CPU and temperature as null", () => {
    const points = toServerPoints(healthFixture(2, SERVER_NOW_MS));
    expect(points[0]).toEqual({ time: SERVER_NOW_MS - 5000, cpu: null, memGib: 2, temp: 48.2 });
    expect(points[1]!.cpu).toBe(11);
  });
});

describe("ServerDetail", () => {
  it("renders the three charts, the disk gauge and the load line", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes([{ path: "/serveur", element: <ServerDetail /> }], "/serveur");
    expect(await screen.findByRole("heading", { name: "CPU (%)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mémoire utilisée (Gio)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Température (°C)" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Disque" })).getByText("20,0 / 64,0 Gio"));
    expect(screen.getByText("Charge 0,42 · 0,38 · 0,31")).toBeInTheDocument();
    expect(document.querySelectorAll(".recharts-surface").length).toBeGreaterThanOrEqual(3);
  });
});
```

Extend `frontend/src/components/app-sidebar.test.tsx`: in the test "links to the dashboard and the camera", add

```tsx
    expect(nav.getByRole("link", { name: "Serveur" })).toHaveAttribute("href", "/serveur");
```

and rename the test to "links to the dashboard, the camera and the server".

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/server/server-detail.test.tsx src/components/app-sidebar.test.tsx`
Expected: detail FAILS on the missing import; sidebar FAILS with `Unable to find an accessible element with the role "link" and name "Serveur"`.

- [ ] **Step 3: Charts**

```tsx
// frontend/src/features/server/server-charts.tsx
import type { ReactNode } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { tooltipTimeLabel } from "@/features/metrics/tooltip-label";
import { formatNumber, formatTime } from "@/lib/format-number";
import type { ServerHealth } from "./server-api";

export type ServerPoint = { time: number; cpu: number | null; memGib: number; temp: number | null };

export function toServerPoints(history: ServerHealth[]): ServerPoint[] {
  return history.map((h) => ({
    time: Date.parse(h.recorded_at),
    cpu: h.cpu_pct,
    memGib: h.mem_used_bytes / 2 ** 30,
    temp: h.temperature_c,
  }));
}

const cpuConfig = { cpu: { label: "CPU (%)", color: "var(--chart-3)" } } satisfies ChartConfig;
const memConfig = {
  memGib: { label: "Mémoire utilisée (Gio)", color: "var(--chart-3)" },
} satisfies ChartConfig;
const tempConfig = {
  temp: { label: "Température (°C)", color: "var(--chart-3)" },
} satisfies ChartConfig;

const axisProps = { tickLine: false, axisLine: false, tickMargin: 8, minTickGap: 32 } as const;
const initialDimension = { width: 600, height: 224 };

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          <h2>{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function timeAxis() {
  return <XAxis dataKey="time" tickFormatter={(v) => formatTime(Number(v))} {...axisProps} />;
}

export function CpuChart({ points }: { points: ServerPoint[] }) {
  return (
    <ChartCard title="CPU (%)">
      <ChartContainer config={cpuConfig} className="h-56 w-full" initialDimension={initialDimension}>
        <AreaChart data={points}>
          <CartesianGrid vertical={false} />
          {timeAxis()}
          <YAxis domain={[0, 100]} width={36} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          <Area dataKey="cpu" type="monotone" stroke="var(--color-cpu)" fill="var(--color-cpu)" fillOpacity={0.15} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function MemoryChart({ points, totalGib }: { points: ServerPoint[]; totalGib: number }) {
  return (
    <ChartCard title="Mémoire utilisée (Gio)">
      <ChartContainer config={memConfig} className="h-56 w-full" initialDimension={initialDimension}>
        <AreaChart data={points}>
          <CartesianGrid vertical={false} />
          {timeAxis()}
          <YAxis domain={[0, Math.ceil(totalGib)]} width={36} tickFormatter={(v) => formatNumber(Number(v), 0)} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          <Area dataKey="memGib" type="monotone" stroke="var(--color-memGib)" fill="var(--color-memGib)" fillOpacity={0.15} strokeWidth={2} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function ServerTemperatureChart({ points }: { points: ServerPoint[] }) {
  return (
    <ChartCard title="Température (°C)">
      <ChartContainer config={tempConfig} className="h-56 w-full" initialDimension={initialDimension}>
        <LineChart data={points}>
          <CartesianGrid vertical={false} />
          {timeAxis()}
          <YAxis domain={["dataMin - 2", "dataMax + 2"]} width={36} tickFormatter={(v) => formatNumber(Number(v), 0)} {...axisProps} />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={tooltipTimeLabel} />} />
          <Line dataKey="temp" type="monotone" stroke="var(--color-temp)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function ServerCharts({ history }: { history: ServerHealth[] }) {
  const points = toServerPoints(history);
  const totalGib = (history.at(-1)?.mem_total_bytes ?? 0) / 2 ** 30;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <CpuChart points={points} />
      <MemoryChart points={points} totalGib={totalGib} />
      <ServerTemperatureChart points={points} />
    </div>
  );
}
```

Prettier will reflow the long JSX lines; that is expected.

- [ ] **Step 4: Detail section and page**

```tsx
// frontend/src/features/server/server-detail.tsx
import { Skeleton } from "@/components/ui/skeleton";
import { HealthGauge } from "./health-gauge";
import { formatBytesPair, formatUptime, ratio, USAGE_WARN_PCT } from "./server-api";
import { ServerCharts } from "./server-charts";
import { loadLabel } from "./server-health-card";
import { useServerHealth } from "./use-server-health";

/** The `/serveur` page body: the server card's series, full size, over the last 30 minutes. */
export function ServerDetail() {
  const { status, latest, history } = useServerHealth();
  const disk = latest ? ratio(latest.disk_used_bytes, latest.disk_total_bytes) : null;
  return (
    <section aria-labelledby="server-title" className="space-y-4">
      <h1 id="server-title" className="text-2xl font-semibold">
        Serveur
      </h1>
      {status === "loading" && (
        <Skeleton role="status" aria-label="Chargement de la santé du serveur" className="h-56 w-full" />
      )}
      {status === "error" && <p className="text-destructive">Santé du serveur indisponible.</p>}
      {status === "ready" && !latest && (
        <p className="text-muted-foreground">En attente du premier échantillon…</p>
      )}
      {latest && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <HealthGauge
              label="Disque"
              valueText={formatBytesPair(latest.disk_used_bytes, latest.disk_total_bytes)}
              ratio={disk}
              warn={(disk ?? 0) >= USAGE_WARN_PCT / 100}
              series={history.map((h) => ratio(h.disk_used_bytes, h.disk_total_bytes))}
            />
            <div className="text-muted-foreground self-center text-sm tabular-nums">
              <p>{loadLabel(latest)}</p>
              <p>Démarré depuis {formatUptime(latest.uptime_s)}</p>
            </div>
          </div>
          <ServerCharts history={history} />
        </>
      )}
    </section>
  );
}
```

```tsx
// frontend/src/pages/server.tsx
import { ServerDetail } from "@/features/server/server-detail";
import { useDocumentTitle } from "@/lib/use-document-title";

export function ServerPage() {
  useDocumentTitle("Serveur · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <ServerDetail />
    </div>
  );
}
```

`frontend/src/app/router.tsx`: import `ServerPage` from `@/pages/server` and add `{ path: "/serveur", element: <ServerPage /> }` after the camera route.

`frontend/src/app/app-shell.tsx`: `const TITLES = { "/": "Dashboard", "/camera": "Caméra", "/serveur": "Serveur" }`.

`frontend/src/components/app-sidebar.tsx`: import `Server` from `lucide-react` and add `{ to: "/serveur", label: "Serveur", icon: Server, end: false }` to `NAV_ITEMS`.

`loadLabel` is exported by `server-health-card.tsx` (Task 8); ESLint's react-refresh rule accepts a
non-component export next to a component only when it is a plain function, which it is. If the rule
still complains, move `loadLabel` to `server-api.ts` and import it from there in both files.

- [ ] **Step 5: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: all tests pass (113 with the new ones).

- [ ] **Step 6: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): /serveur page with CPU, memory and temperature charts, nav entry

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `CameraStream` extracted from `CameraView`, `CameraCard`

**Files:**
- Create: `frontend/src/features/camera/camera-stream.tsx`, `frontend/src/features/camera/camera-card.tsx`
- Modify: `frontend/src/features/camera/camera-view.tsx`
- Test: `frontend/src/features/camera/camera-card.test.tsx`; existing `camera-view.test.tsx` must stay green.

**Interfaces:**
- Consumes: `streamUrl`, `CAMERA_STATUS_PATH`, `CameraStatus` from `camera-api.ts`; `useAuth`.
- Produces: `type StreamState = "checking" | "unconfigured" | "connecting" | "live"`; `CameraStream({ onStateChange?, onStatus?, className? })`; `CameraCard({ className? })` (a `Link` to `/camera`).

- [ ] **Step 1: Write the failing card tests**

```tsx
// frontend/src/features/camera/camera-card.test.tsx
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { CameraCard } from "./camera-card";

const ALT = "Flux vidéo de la caméra";

function renderCard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([
    { path: "/", element: <CameraCard /> },
    { path: "/camera", element: <h1>Caméra</h1> },
  ]);
}

describe("CameraCard", () => {
  it("opens the stream and shows the live badge once frames arrive", async () => {
    renderCard();
    const img = await screen.findByAltText(ALT);
    expect(img.getAttribute("src")).toMatch(/^\/api\/camera\/stream\?token=/);
    expect(screen.queryByText("EN DIRECT")).not.toBeInTheDocument();
    fireEvent.load(img);
    expect(screen.getByText("EN DIRECT")).toBeInTheDocument();
  });

  it("navigates to the camera page when clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderCard();
    await user.click(await screen.findByRole("link", { name: "Caméra, voir en grand" }));
    expect(router.state.location.pathname).toBe("/camera");
  });

  it("says so when no camera is configured", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: false, viewers: 0 })),
    );
    renderCard();
    expect(await screen.findByText("Aucune caméra configurée")).toBeInTheDocument();
    expect(screen.queryByAltText(ALT)).not.toBeInTheDocument();
  });

  it("releases the stream on unmount", async () => {
    const view = renderCard();
    const img = await screen.findByAltText(ALT);
    view.unmount();
    expect(img.getAttribute("src")).toBe("");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/features/camera/camera-card.test.tsx`
Expected: FAIL, `Failed to resolve import "./camera-card"`.

- [ ] **Step 3: Extract `CameraStream`**

```tsx
// frontend/src/features/camera/camera-stream.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import { cn } from "@/lib/utils";
import { CAMERA_STATUS_PATH, streamUrl, type CameraStatus } from "./camera-api";

export const RECONNECT_DELAY_MS = 2000;

export type StreamState = "checking" | "unconfigured" | "connecting" | "live";

type Props = {
  onStateChange?: (state: StreamState) => void;
  onStatus?: (status: CameraStatus) => void;
  className?: string;
};

/**
 * The relayed MJPEG stream: asks `/camera/status`, opens `<img>` on the relay, reconnects 2 s
 * after an error, releases the image on unmount. Renders nothing when no camera is configured;
 * the parent decides what to say.
 */
export function CameraStream({ onStateChange, onStatus, className }: Props) {
  const { accessToken, authFetch } = useAuth();
  // The stream keeps the token it was opened with; only a reconnection uses a newer one.
  const tokenRef = useRef(accessToken);
  // Set when the stream should open but the session token has not been committed yet.
  const pendingConnect = useRef(false);
  const [state, setStateRaw] = useState<StreamState>("checking");
  const [src, setSrc] = useState<string | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // React nulls element refs before effect cleanups run, so keep the last <img> ourselves.
  const lastImg = useRef<HTMLImageElement | null>(null);
  const onStateChangeRef = useRef(onStateChange);
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStateChangeRef.current = onStateChange;
    onStatusRef.current = onStatus;
  });

  const setState = useCallback((next: StreamState) => {
    setStateRaw(next);
    onStateChangeRef.current?.(next);
  }, []);

  const connect = useCallback(() => {
    if (!tokenRef.current) {
      pendingConnect.current = true;
      return;
    }
    pendingConnect.current = false;
    attemptRef.current += 1;
    setState("connecting");
    setSrc(streamUrl(tokenRef.current, attemptRef.current));
  }, [setState]);

  useEffect(() => {
    tokenRef.current = accessToken;
    if (pendingConnect.current && accessToken) connect();
  }, [accessToken, connect]);

  useEffect(() => {
    let cancelled = false;
    authFetch<CameraStatus>(CAMERA_STATUS_PATH)
      .then((status) => {
        if (cancelled) return;
        onStatusRef.current?.(status);
        if (status.configured) connect();
        else setState("unconfigured");
      })
      .catch(() => {
        // Status unknown (network hiccup): try the stream anyway, it will retry on error.
        if (!cancelled) connect();
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, connect, setState]);

  useEffect(() => {
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (lastImg.current) lastImg.current.src = "";
    };
  }, []);

  const scheduleReconnect = () => {
    setState("connecting");
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
  };

  if (state === "unconfigured") return null;

  return (
    <div className={cn("relative bg-black", className)}>
      {src && (
        <img
          ref={(element) => {
            if (element) lastImg.current = element;
          }}
          src={src}
          alt="Flux vidéo de la caméra"
          className="absolute inset-0 h-full w-full object-contain"
          onLoad={() => setState("live")}
          onError={scheduleReconnect}
        />
      )}
      {state !== "live" && (
        <p
          role="status"
          className="absolute inset-0 grid place-items-center text-sm text-neutral-400"
        >
          Connexion à la caméra…
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `CameraView` on top of it**

Replace the whole content of `frontend/src/features/camera/camera-view.tsx` with:

```tsx
import { Maximize, Minimize } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { viewersLabel } from "./camera-api";
import { CameraStream, type StreamState } from "./camera-stream";

export { RECONNECT_DELAY_MS } from "./camera-stream";

const IDLE_DELAY_MS = 2500;

export function CameraView() {
  const [state, setState] = useState<StreamState>("checking");
  const [otherViewers, setOtherViewers] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [idle, setIdle] = useState(false);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, []);

  const toggleFullscreen = useCallback(() => {
    const element = containerRef.current;
    if (!element || typeof element.requestFullscreen !== "function") return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void element.requestFullscreen();
  }, []);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest?.('[role="menu"], input, textarea, [contenteditable="true"]')) return;
      if (target?.isContentEditable) return;
      if (event.key === "f" || event.key === "F") toggleFullscreen();
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("keydown", onKey);
    };
  }, [toggleFullscreen]);

  const wake = () => {
    setIdle(false);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setIdle(true), IDLE_DELAY_MS);
  };

  if (state === "unconfigured") {
    return (
      <section className="flex flex-1 items-center justify-center p-4 text-center">
        <div className="max-w-md space-y-2">
          <h1 className="text-xl font-semibold">Aucune caméra configurée</h1>
          <p className="text-muted-foreground">
            Renseigne <code>CAMERA_STREAM_URL</code> dans <code>backend/.env</code> puis redémarre
            l'API.
          </p>
        </div>
      </section>
    );
  }

  // iPhone Safari has no element fullscreen: hide the button there.
  const fullscreenSupported = Boolean(document.fullscreenEnabled);
  const viewers = otherViewers + (state === "live" ? 1 : 0);

  return (
    <div
      ref={containerRef}
      onMouseMove={wake}
      onTouchStart={wake}
      onClick={wake}
      onDoubleClick={toggleFullscreen}
      className={cn("relative flex flex-1 bg-black", idle && "cursor-none")}
    >
      <CameraStream
        className="flex-1"
        onStateChange={setState}
        onStatus={(status) => setOtherViewers(status.viewers)}
      />
      <div
        className={cn(
          "absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent p-4 transition-opacity",
          idle && "pointer-events-none opacity-0",
        )}
      >
        <div className="flex items-center gap-3">
          {state === "live" && (
            <Badge className="bg-red-600 text-white">
              <span className="mr-1 inline-block size-2 animate-pulse rounded-full bg-white" />
              EN DIRECT
            </Badge>
          )}
          <span className="text-xs text-neutral-300">{viewersLabel(viewers)}</span>
        </div>
        {fullscreenSupported && (
          <Button
            variant="ghost"
            size="icon"
            className="text-white hover:bg-white/15 hover:text-white"
            aria-label={fullscreen ? "Quitter le plein écran" : "Plein écran"}
            onClick={(event) => {
              event.stopPropagation();
              toggleFullscreen();
            }}
          >
            {fullscreen ? <Minimize className="size-6" /> : <Maximize className="size-6" />}
          </Button>
        )}
      </div>
    </div>
  );
}
```

Caveat for the "unconfigured" branch: when `CameraStream` reports `unconfigured`, `CameraView` re-renders without it, which unmounts the stream. That is intended; the view's own section takes over.

- [ ] **Step 5: The card**

```tsx
// frontend/src/features/camera/camera-card.tsx
import { useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { CameraStream, type StreamState } from "./camera-stream";

/** Wall-screen card: the live stream in a 16:9 frame; the whole card opens the camera page. */
export function CameraCard({ className }: { className?: string }) {
  const [state, setState] = useState<StreamState>("checking");
  return (
    <Link
      to="/camera"
      aria-label="Caméra, voir en grand"
      className={cn("block rounded-xl focus-visible:ring-2 focus-visible:outline-none", className)}
    >
      <Card className="hover:bg-accent/40 h-full gap-2 transition-colors">
        <CardHeader className="flex flex-row items-center justify-between pb-0">
          <CardTitle className="text-sm font-medium">Caméra</CardTitle>
          {state === "live" && (
            <Badge className="bg-red-600 text-white">
              <span className="mr-1 inline-block size-2 animate-pulse rounded-full bg-white" />
              EN DIRECT
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {state === "unconfigured" ? (
            <p className="text-muted-foreground grid aspect-video place-items-center text-sm">
              Aucune caméra configurée
            </p>
          ) : (
            <CameraStream className="aspect-video overflow-hidden rounded-lg" onStateChange={setState} />
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
```

- [ ] **Step 6: Run the toolchain**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6`
Expected: all tests pass (117 with the new ones), including all of `camera-view.test.tsx` unchanged. If the camera-view test "releases the stream on unmount" fails, check that `lastImg` is set in the `ref` callback of `CameraStream` and cleared in its unmount effect (both are in Step 3).

- [ ] **Step 7: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src/features/camera && git commit -q -m "$(cat <<'EOF'
feat(frontend): CameraStream extracted from CameraView, camera card linking to /camera

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Dashboard layout and collapsed sidebar

**Files:**
- Modify: `frontend/src/pages/dashboard.tsx`, `frontend/src/features/metrics/metrics-section.tsx`, `frontend/src/features/metrics/metrics-section.test.tsx`, `frontend/src/app/app-shell.tsx`
- Test: `frontend/src/pages/dashboard.test.tsx` (new), `frontend/src/components/app-sidebar.test.tsx` (extend)

**Interfaces:**
- Consumes: `CameraCard` (Task 10), `ServerHealthCard` (Task 8), `MetricsSection`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/pages/dashboard.test.tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { VALID_REFRESH } from "@/test/server";

function renderDashboard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, "/");
}

describe("Dashboard (wall screen)", () => {
  it("shows the camera card, the server card and the sensors section under one heading", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Caméra, voir en grand" })).toHaveAttribute("href", "/camera");
    expect(screen.getByRole("link", { name: "Santé du serveur, voir le détail" })).toHaveAttribute("href", "/serveur");
    const sensors = within(await screen.findByRole("region", { name: "Capteurs" }));
    expect(sensors.getByRole("heading", { level: 2, name: "Capteurs" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("opens the camera page when the camera card is clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderDashboard();
    await user.click(await screen.findByRole("link", { name: "Caméra, voir en grand" }));
    expect(router.state.location.pathname).toBe("/camera");
    expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
  });
});
```

Add to `frontend/src/components/app-sidebar.test.tsx`:

```tsx
  it("starts collapsed so the wall screen keeps the room for the content", async () => {
    renderAuthenticated("/");
    await sidebar();
    expect(document.querySelector('[data-slot="sidebar"]')).toHaveAttribute(
      "data-state",
      "collapsed",
    );
  });
```

Update `frontend/src/features/metrics/metrics-section.test.tsx`: the region is now named "Capteurs" (`screen.findByRole("region", { name: "Capteurs" })`), the describe becomes `"Sensors section"`, and the test "has a single Dashboard heading and no status cards" becomes "has a single Capteurs heading (level 2) and no status cards" asserting `screen.getAllByRole("heading", { level: 2 })` contains one named "Capteurs" and `screen.queryByRole("heading", { level: 1 })` is null.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm vitest run src/pages/dashboard.test.tsx src/components/app-sidebar.test.tsx src/features/metrics/metrics-section.test.tsx`
Expected: dashboard FAILS (no camera link), sidebar FAILS (`data-state="expanded"`), metrics-section FAILS (region "Capteurs" not found).

- [ ] **Step 3: Implement**

`frontend/src/features/metrics/metrics-section.tsx`: change the heading to

```tsx
      <h2 id="metrics-title" className="text-xl font-semibold">
        Capteurs
      </h2>
```

`frontend/src/pages/dashboard.tsx`:

```tsx
import { CameraCard } from "@/features/camera/camera-card";
import { MetricsSection } from "@/features/metrics/metrics-section";
import { ServerHealthCard } from "@/features/server/server-health-card";
import { useDocumentTitle } from "@/lib/use-document-title";

/** Wall screen for the infra team: everything at a glance, each card opens its detail page. */
export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <CameraCard className="lg:col-span-2" />
        <ServerHealthCard />
      </div>
      <MetricsSection />
    </div>
  );
}
```

`frontend/src/app/app-shell.tsx`: `<SidebarProvider defaultOpen={false}>` with a comment: `{/* Wall screen first: collapsed on load, the user can still open it for the session. */}` placed above the provider inside the TooltipProvider.

- [ ] **Step 4: Run the toolchain and the build**

Run: `cd /Users/namania/git/sentinel-x/frontend && pnpm format >/dev/null && pnpm lint && pnpm typecheck && pnpm test 2>&1 | tail -6 && pnpm build 2>&1 | tail -4`
Expected: all tests pass (120 with the new ones), build OK. `router.test.tsx` still finds the "Dashboard" heading (it is the page's h1 now).

- [ ] **Step 5: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add frontend/src && git commit -q -m "$(cat <<'EOF'
feat(frontend): wall-screen dashboard with camera and server cards, sidebar collapsed by default

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: README, spec status, visual check

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-06-infra-dashboard-design.md` (status line)

- [ ] **Step 1: README**

Insert a new section before `## Front`:

```markdown
## Dashboard

La page d'accueil est pensée pour un écran mural : sidebar repliée, une carte caméra (flux en
direct, clic → `/camera`), une carte santé du serveur (clic → `/serveur`) et la section capteurs.

La santé du serveur (CPU, mémoire, disque, température du SoC, charge, uptime) est lue par l'API
dans `/proc`, `/sys/class/thermal` et `statvfs`, toutes les 5 s (`SERVER_HEALTH_INTERVAL_S`),
gardée 30 min en mémoire (rien en base) et diffusée sur le WebSocket
(`{"type":"server.health","data":{…}}`) ; `GET /api/server/health` renvoie le dernier point et
l'historique. `compose.yml` monte `/sys/class/thermal` et `/` en lecture seule dans le conteneur
`api` (`HOST_THERMAL_PATH`, `HOST_DISK_PATH`) ; `/proc` du conteneur décrit déjà l'hôte. Sous
Docker Desktop (Mac) il n'y a pas de zone thermique : la température s'affiche « – ».
`SERVER_HEALTH_ENABLED=false` désactive l'échantillonnage (c'est le cas dans les tests).
```

In the spec, change `Statut : validé, à implémenter` to `Statut : implémenté le 2026-10-06`.

- [ ] **Step 2: Visual check in the dev stack**

Run: `cd /Users/namania/git/sentinel-x && make dev` (background) then, once up, log in at http://localhost:8080 and look at the Dashboard: sidebar collapsed, camera card (or « Connexion à la caméra… » if the ESP is unreachable from this machine), server card with four gauges updating every 5 s, sensors below. Open `/serveur`: three charts filling over time. Resize the window below 1024 px: cards stack. Check `docker compose logs api | grep -i "server health"` shows no warnings (on Docker Desktop the temperature is simply `–`).

Expected: no console error, server card values change every 5 s.

- [ ] **Step 3: Commit**

```bash
cd /Users/namania/git/sentinel-x && git add README.md docs/superpowers/specs/2026-10-06-infra-dashboard-design.md && git commit -q -m "$(cat <<'EOF'
docs: wall-screen dashboard, server health sources and Docker mounts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

## Finish

Final whole-branch review, then superpowers:finishing-a-development-branch: rebase `feat/infra-dashboard` on `origin/main` if it moved, fast-forward `develop` and `main`, delete the branch, push both. Then on the Pi: `make deploy` (the new bind mounts need a container recreate, which `compose up --build` does).
