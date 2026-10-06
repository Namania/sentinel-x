from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.event_broadcaster import Event

logger = logging.getLogger(__name__)


class Connection(Protocol):
    async def send_json(self, data: Any) -> None: ...


class ConnectionHub:
    """Registry of live WebSocket connections, keyed by user. One instance per process."""

    def __init__(self, send_timeout: float = 1.0) -> None:
        self._connections: dict[UUID, set[Connection]] = defaultdict(set)
        self._send_timeout = send_timeout

    def connect(self, user_id: UUID, connection: Connection) -> None:
        self._connections[user_id].add(connection)

    def disconnect(self, user_id: UUID, connection: Connection) -> None:
        bucket = self._connections.get(user_id)
        if bucket is None:
            return
        bucket.discard(connection)
        if not bucket:
            del self._connections[user_id]

    @property
    def connection_count(self) -> int:
        return sum(len(bucket) for bucket in self._connections.values())

    async def broadcast(self, event: Event) -> None:
        for bucket in list(self._connections.values()):
            for connection in list(bucket):
                await self._safe_send(connection, event)

    async def send_to_user(self, user_id: UUID, event: Event) -> None:
        for connection in list(self._connections.get(user_id, ())):
            await self._safe_send(connection, event)

    async def _safe_send(self, connection: Connection, event: Event) -> None:
        try:
            # A stalled socket (full send buffer) must not hold up the sender or the other clients.
            await asyncio.wait_for(connection.send_json(event), self._send_timeout)
        except Exception:  # noqa: BLE001 - a dead or stalled socket must not break the others
            logger.debug("dropping event for a closed or stalled connection", exc_info=True)
