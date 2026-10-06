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
