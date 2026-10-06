import json
import random
from datetime import UTC, datetime, timedelta

import httpx

from app.presentation.simulate import SensorWalk, run


def test_walk_stays_within_plausible_bounds():
    walk = SensorWalk(random.Random(1))
    for _ in range(1000):
        p = walk.next_payload("esp-interieur")
        assert p["device_id"] == "esp-interieur"
        assert 15.0 <= p["temperature"]["temp"] <= 35.0
        assert 20.0 <= p["temperature"]["humidity"] <= 90.0
        assert 200 <= p["gaz"]["quantity"] <= 3000
        assert p["gaz"]["mostGaz"] == (p["gaz"]["quantity"] >= 1500)


def test_walk_produces_an_occasional_gas_alert():
    walk = SensorWalk(random.Random(7))
    alerts = sum(walk.next_payload("esp-interieur")["gaz"]["mostGaz"] for _ in range(2000))
    assert 0 < alerts < 400


def test_run_posts_readings_with_the_device_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"ok": True})

    sent = run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=3,
        transport=httpx.MockTransport(handler),
        log=lambda _: None,
    )
    assert sent == 3 and len(seen) == 3
    assert str(seen[0].url) == "http://api.test/sensors/readings"
    assert seen[0].headers["X-Device-Key"] == "k" * 16
    assert json.loads(seen[0].content)["device_id"] == "esp-interieur"


def test_backfill_posts_timestamped_readings_oldest_first():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"ok": True})

    sent = run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=None,
        transport=httpx.MockTransport(handler),
        log=lambda _: None,
        backfill_minutes=3,
    )
    assert sent == 3
    stamps = [p["recorded_at"] for p in seen]
    assert stamps == sorted(stamps)
    parsed = [datetime.fromisoformat(s) for s in stamps]
    assert (parsed[1] - parsed[0]).total_seconds() == 60
    assert datetime.now(UTC) - parsed[-1] < timedelta(seconds=5)


def test_spike_overrides_one_metric():
    walk = SensorWalk(random.Random(3))
    assert walk.next_payload("esp-interieur", spike="temperature")["temperature"]["temp"] == 33.0
    assert walk.next_payload("esp-interieur", spike="humidity")["temperature"]["humidity"] == 78.0
    gas = walk.next_payload("esp-interieur", spike="gas")["gaz"]
    assert gas["mostGaz"] is True and gas["quantity"] >= 1600


def test_run_with_spike_posts_five_normal_six_hot_five_normal_then_stops():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"ok": True})

    sent = run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=None,
        transport=httpx.MockTransport(handler),
        log=lambda _: None,
        spike="temperature",
    )
    assert sent == 16
    temps = [b["temperature"]["temp"] for b in bodies]
    assert all(t == 33.0 for t in temps[5:11])
    assert all(t < 33.0 for t in temps[:5] + temps[11:])


def test_gas_spike_keeps_the_flag_down_outside_the_burst_and_logs_the_gas():
    bodies: list[dict] = []
    lines: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"ok": True})

    run(
        base_url="http://api.test",
        device_key="k" * 16,
        device_id="esp-interieur",
        interval=0,
        count=None,
        transport=httpx.MockTransport(handler),
        log=lines.append,
        spike="gas",
    )
    flags = [b["gaz"]["mostGaz"] for b in bodies]
    assert flags == [False] * 5 + [True] * 6 + [False] * 5
    assert all("mV" in line for line in lines)
