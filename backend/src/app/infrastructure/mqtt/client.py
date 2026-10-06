"""aiomqtt-backed connection factory for the subscriber."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiomqtt


def connect_factory(host: str, port: int, identifier: str = "sentinel-x-api"):
    @asynccontextmanager
    async def connect() -> AsyncIterator[aiomqtt.Client]:
        async with aiomqtt.Client(host, port, identifier=identifier) as client:
            yield client

    return connect
