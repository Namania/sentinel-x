"""Publish the siren state as a retained MQTT message, opening a connection on demand."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from app.application.alerts.siren import siren_to_dict
from app.domain.siren import SirenState


class PublishingClient(Protocol):
    async def publish(
        self, topic: str, payload: str, qos: int = 0, retain: bool = False
    ) -> object: ...


Connect = Callable[[], AbstractAsyncContextManager[PublishingClient]]


class MqttSirenPublisher:
    """One short connection per publication: state changes are rare, nothing to keep alive."""

    def __init__(self, connect: Connect, topic: str) -> None:
        self._connect = connect
        self._topic = topic

    async def publish(self, state: SirenState, at: datetime) -> None:
        # Compact: the firmware matches the raw bytes (`"on":true`), no spaces to guess.
        payload = json.dumps(siren_to_dict(state, at), separators=(",", ":"))
        async with self._connect() as client:
            await client.publish(self._topic, payload, qos=1, retain=True)
