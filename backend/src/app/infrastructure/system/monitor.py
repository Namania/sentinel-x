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
