"""Fan-out relay: one connection to the camera, any number of viewers.

The ESP32 camera firmware serves a single MJPEG client at a time, so every viewer must
share one upstream connection. The relay opens it when the first viewer arrives, keeps the
latest decoded frame, wakes viewers on each new frame and closes the camera when the last
viewer leaves. A slow viewer simply skips to the latest frame.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.infrastructure.camera.mjpeg import MjpegParser, boundary_from_content_type

logger = logging.getLogger(__name__)


class UpstreamStream(Protocol):
    @property
    def content_type(self) -> str: ...

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...


StreamOpener = Callable[[], AbstractAsyncContextManager[UpstreamStream]]


class CameraRelay:
    def __init__(self, open_stream: StreamOpener, retry_delay: float = 1.0) -> None:
        self._open_stream = open_stream
        self._retry_delay = retry_delay
        self._viewers = 0
        self._pump: asyncio.Task[None] | None = None
        self._latest: bytes | None = None
        self._sequence = 0
        self._new_frame = asyncio.Event()

    @property
    def viewer_count(self) -> int:
        return self._viewers

    @property
    def frames_received(self) -> int:
        return self._sequence

    async def frames(self) -> AsyncIterator[bytes]:
        self._viewers += 1
        if self._pump is None:
            self._pump = asyncio.create_task(self._run_pump(), name="camera-relay-pump")
        seen = 0
        try:
            while True:
                if self._sequence == seen:
                    event = self._new_frame
                    await event.wait()
                    continue
                seen = self._sequence
                assert self._latest is not None
                yield self._latest
        finally:
            self._viewers -= 1
            if self._viewers == 0:
                await self._stop_pump()

    async def _stop_pump(self) -> None:
        pump, self._pump = self._pump, None
        if pump is None:
            return
        pump.cancel()
        try:
            await pump
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():  # type: ignore[union-attr]
                raise

    async def _run_pump(self) -> None:
        while True:
            try:
                await self._relay_once()
                logger.info("camera stream ended, reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - any upstream failure just triggers a retry
                logger.warning("camera stream failed, retrying", exc_info=True)
            await asyncio.sleep(self._retry_delay)

    async def _relay_once(self) -> None:
        async with self._open_stream() as stream:
            parser = MjpegParser(boundary_from_content_type(stream.content_type))
            async for chunk in stream.aiter_bytes():
                for frame in parser.feed(chunk):
                    self._publish(frame)

    def _publish(self, frame: bytes) -> None:
        self._latest = frame
        self._sequence += 1
        waiters, self._new_frame = self._new_frame, asyncio.Event()
        waiters.set()
