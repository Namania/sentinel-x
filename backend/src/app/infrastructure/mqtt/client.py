"""aiomqtt-backed connection factory for the subscriber."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiomqtt


def connect_factory(
    host: str,
    port: int,
    identifier: str = "sentinel-x-api",
    username: str | None = None,
    password: str | None = None,
):
    credentials = {"username": username, "password": password} if username is not None else {}

    @asynccontextmanager
    async def connect() -> AsyncIterator[aiomqtt.Client]:
        # A broker that accepts TCP but never answers must not stall the caller for ever.
        async with aiomqtt.Client(
            host, port, identifier=identifier, timeout=5, **credentials
        ) as client:
            yield client

    return connect
