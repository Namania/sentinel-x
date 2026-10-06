from typing import Any
from uuid import uuid4

import pytest

from app.infrastructure.realtime.hub import ConnectionHub


class FakeConnection:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Any] = []
        self.fail = fail

    async def send_json(self, data: Any) -> None:
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


@pytest.fixture
def hub() -> ConnectionHub:
    return ConnectionHub()


async def test_broadcast_reaches_every_connection(hub):
    alice, bob = uuid4(), uuid4()
    a1, a2, b1 = FakeConnection(), FakeConnection(), FakeConnection()
    hub.connect(alice, a1)
    hub.connect(alice, a2)
    hub.connect(bob, b1)

    await hub.broadcast({"type": "hello"})

    assert a1.sent == a2.sent == b1.sent == [{"type": "hello"}]
    assert hub.connection_count == 3


async def test_send_to_user_targets_only_that_user(hub):
    alice, bob = uuid4(), uuid4()
    a1, b1 = FakeConnection(), FakeConnection()
    hub.connect(alice, a1)
    hub.connect(bob, b1)

    await hub.send_to_user(alice, {"type": "private"})

    assert a1.sent == [{"type": "private"}]
    assert b1.sent == []


async def test_disconnect_removes_connection(hub):
    alice = uuid4()
    a1 = FakeConnection()
    hub.connect(alice, a1)
    hub.disconnect(alice, a1)

    await hub.broadcast({"type": "hello"})

    assert a1.sent == []
    assert hub.connection_count == 0


async def test_failing_connection_does_not_break_broadcast(hub):
    alice = uuid4()
    dead, alive = FakeConnection(fail=True), FakeConnection()
    hub.connect(alice, dead)
    hub.connect(alice, alive)

    await hub.broadcast({"type": "hello"})

    assert alive.sent == [{"type": "hello"}]


def test_disconnect_unknown_is_noop(hub):
    hub.disconnect(uuid4(), FakeConnection())
    assert hub.connection_count == 0


async def test_a_stalled_connection_does_not_block_the_others():
    import asyncio

    from app.infrastructure.realtime.hub import ConnectionHub

    class Stalled:
        async def send_json(self, data):
            await asyncio.sleep(10)

    class Fast:
        def __init__(self):
            self.received = []

        async def send_json(self, data):
            self.received.append(data)

    hub = ConnectionHub(send_timeout=0.05)
    fast = Fast()
    hub.connect(uuid4(), Stalled())
    hub.connect(uuid4(), fast)
    async with asyncio.timeout(1):
        await hub.broadcast({"type": "x"})
    assert fast.received == [{"type": "x"}]
