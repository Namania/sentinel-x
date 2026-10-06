import asyncio
from contextlib import asynccontextmanager

import pytest

from app.infrastructure.mqtt.subscriber import MqttSubscriber
from tests.unit.fakes import InMemoryUnitOfWork


class FakeMessage:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class FakeBroker:
    """Scripted MQTT client: yields the queued messages, raising where an error is queued."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[FakeMessage | Exception | None] = asyncio.Queue()
        self.subscriptions: list[str] = []
        self.opens = 0

    def push(self, topic: str, payload: bytes) -> None:
        self.queue.put_nowait(FakeMessage(topic, payload))

    @asynccontextmanager
    async def open(self):
        self.opens += 1
        yield self

    async def subscribe(self, topic: str) -> None:
        self.subscriptions.append(topic)

    @property
    def messages(self):
        return self._iterate()

    async def _iterate(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


@pytest.fixture
def world():
    broker = FakeBroker()
    uow = InMemoryUnitOfWork()
    bus = RecordingBroadcaster()
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)

    subscriber = MqttSubscriber(
        connect=broker.open,
        topic="sentinel/+",
        uow_factory=lambda: uow,
        broadcaster=bus,
        sleep=sleep,
    )
    return broker, uow, bus, delays, subscriber


async def run_until(subscriber: MqttSubscriber, predicate, timeout: float = 1.0) -> asyncio.Task:
    task = asyncio.create_task(subscriber.run())
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)
    return task


async def test_stores_and_broadcasts_each_message(world):
    broker, uow, bus, _, subscriber = world
    broker.push(
        "sentinel/esp1", b'{"temperature":22.5,"humidite":48,"gaz_mv":1234,"etat_gaz":"ok"}'
    )
    broker.push(
        "sentinel/esp1", b'{"temperature":22.6,"humidite":47,"gaz_mv":2000,"etat_gaz":"alerte"}'
    )
    # The second message carries the device's gas alert: a reading event plus an alert event.
    task = await run_until(subscriber, lambda: len(bus.events) >= 3)
    assert broker.subscriptions == ["sentinel/+"]
    assert [r.gas_level for r in uow.readings.readings] == [1234, 2000]
    assert [e["type"] for e in bus.events] == ["sensor.reading", "sensor.reading", "alert.opened"]
    assert bus.events[1]["data"]["gas_alert"] is True
    task.cancel()


async def test_a_bad_message_is_skipped_not_fatal(world):
    broker, uow, bus, _, subscriber = world
    broker.push("sentinel/esp1", b"garbage")
    broker.push("sentinel/esp1", b'{"gaz_mv":500,"etat_gaz":"ok"}')
    task = await run_until(subscriber, lambda: len(bus.events) == 1)
    assert [r.gas_level for r in uow.readings.readings] == [500]
    task.cancel()


async def test_reconnects_with_growing_waits_after_a_broker_error(world):
    broker, _, bus, delays, subscriber = world
    broker.queue.put_nowait(ConnectionError("broker lost"))
    broker.queue.put_nowait(ConnectionError("broker lost again"))
    broker.push("sentinel/esp1", b'{"gaz_mv":500,"etat_gaz":"ok"}')
    task = await run_until(subscriber, lambda: len(bus.events) == 1)
    assert broker.opens == 3
    assert delays == [1.0, 2.0]
    task.cancel()


async def test_stops_cleanly_when_cancelled(world):
    broker, _, _, _, subscriber = world
    task = asyncio.create_task(subscriber.run())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert broker.opens == 1
