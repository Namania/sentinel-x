from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx


class HttpxStream:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def content_type(self) -> str:
        return self._response.headers.get("content-type", "")

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        return self._response.aiter_raw()


class HttpxCameraSource:
    """Opens the camera's MJPEG endpoint over HTTP. Usable as a `StreamOpener`."""

    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = url
        self._transport = transport

    @asynccontextmanager
    async def open(self) -> AsyncIterator[HttpxStream]:
        # No read timeout: a healthy camera streams forever; connect failures still time out.
        timeout = httpx.Timeout(10.0, read=None)
        async with (
            httpx.AsyncClient(timeout=timeout, transport=self._transport) as client,
            client.stream("GET", self._url) as response,
        ):
            response.raise_for_status()
            yield HttpxStream(response)
