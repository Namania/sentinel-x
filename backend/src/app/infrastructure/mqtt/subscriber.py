"""Background MQTT subscriber: every device message becomes a stored, broadcast reading."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.unit_of_work import UnitOfWork
from app.application.sensors.record import RecordReading
from app.domain.alert import DEFAULT_THRESHOLDS, Thresholds
from app.domain.errors import DomainError
from app.infrastructure.mqtt.parser import parse_device_message

logger = logging.getLogger(__name__)

RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0)


class MessageLike(Protocol):
    @property
    def topic(self) -> object: ...

    @property
    def payload(self) -> bytes | bytearray | str | None: ...


class ClientLike(Protocol):
    async def subscribe(self, topic: str) -> object: ...

    @property
    def messages(self) -> AsyncIterator[MessageLike]: ...


Connect = Callable[[], AbstractAsyncContextManager[ClientLike]]


class MqttSubscriber:
    """Keeps a subscription alive, reconnecting with growing waits when the broker drops."""

    def __init__(
        self,
        connect: Connect,
        topic: str,
        uow_factory: Callable[[], UnitOfWork],
        broadcaster: EventBroadcaster,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        thresholds: Thresholds = DEFAULT_THRESHOLDS,
    ) -> None:
        self._connect = connect
        self._topic = topic
        self._uow_factory = uow_factory
        self._broadcaster = broadcaster
        self._sleep = sleep
        self._thresholds = thresholds

    async def run(self) -> None:
        attempt = 0
        while True:
            try:
                async with self._connect() as client:
                    await client.subscribe(self._topic)
                    logger.info("mqtt: subscribed to %s", self._topic)
                    async for message in client.messages:
                        attempt = 0  # a message proves the connection is healthy again
                        await self._handle(message)
                logger.warning("mqtt: connection closed, reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - any broker failure just triggers a retry
                logger.warning("mqtt: connection failed, retrying", exc_info=True)
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            attempt += 1
            await self._sleep(delay)

    async def _handle(self, message: MessageLike) -> None:
        payload = message.payload
        raw = payload.encode() if isinstance(payload, str) else bytes(payload or b"")
        try:
            reading = parse_device_message(str(message.topic), raw)
            await RecordReading(
                self._uow_factory(), self._broadcaster, thresholds=self._thresholds
            ).execute(reading)
        except DomainError as exc:
            logger.warning("mqtt: message on %s ignored: %s", message.topic, exc)
        except Exception:  # noqa: BLE001 - one bad message must not stop the subscription
            logger.exception("mqtt: failed to record message on %s", message.topic)
