import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.domain.siren import SirenState
from app.infrastructure.mqtt.publisher import MqttSirenPublisher


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish(self, topic, payload, qos=0, retain=False):
        self.calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})


async def test_publishes_the_retained_state_on_the_topic():
    client = FakeClient()
    opened = 0

    @asynccontextmanager
    async def connect():
        nonlocal opened
        opened += 1
        yield client

    publisher = MqttSirenPublisher(connect, "sentinel/cmd/buzzer")
    at = datetime(2026, 10, 7, 9, 12, 3, tzinfo=UTC)
    await publisher.publish(SirenState(on=True, reason="gas", open=2, muted_until=None), at)
    assert opened == 1
    call = client.calls[0]
    assert (call["topic"], call["qos"], call["retain"]) == ("sentinel/cmd/buzzer", 1, True)
    # The firmware matches the raw bytes: compact JSON, `on` first, no spaces.
    assert call["payload"].startswith('{"on":true,')
    body = json.loads(call["payload"])
    assert list(body)[0] == "on"
    assert body == {
        "on": True,
        "reason": "gas",
        "open": 2,
        "muted_until": None,
        "at": "2026-10-07T09:12:03Z",
    }
