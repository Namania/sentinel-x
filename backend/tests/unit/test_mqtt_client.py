import aiomqtt

from app.infrastructure.mqtt import client as client_module


async def test_connections_wait_a_bounded_time_for_the_broker(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, host, port, **kwargs) -> None:
            captured.update(host=host, port=port, **kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

    monkeypatch.setattr(aiomqtt, "Client", FakeClient)
    async with client_module.connect_factory("broker", 1883, identifier="x")():
        pass
    assert captured["identifier"] == "x"
    # A broker that accepts TCP but never answers must not stall ingestion forever.
    assert captured["timeout"] == 5
