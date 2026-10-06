from datetime import UTC, datetime, timedelta

from app.application.server.health import HealthHistory, ServerHealth, to_dict, to_event

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def sample(i: int) -> ServerHealth:
    return ServerHealth(
        recorded_at=T0 + timedelta(seconds=5 * i),
        cpu_pct=None if i == 0 else 10.0 + i,
        mem_total_bytes=8_000,
        mem_used_bytes=2_000 + i,
        disk_total_bytes=64_000,
        disk_used_bytes=20_000,
        temperature_c=48.2,
        load_1=0.42,
        load_5=0.38,
        load_15=0.31,
        uptime_s=86_400 + 5 * i,
    )


def test_history_keeps_the_newest_points_in_order():
    history = HealthHistory(maxlen=3)
    for i in range(5):
        history.append(sample(i))
    assert len(history) == 3
    assert [p.uptime_s for p in history.points()] == [86_410, 86_415, 86_420]
    assert history.latest() == sample(4)


def test_empty_history_has_no_latest():
    history = HealthHistory()
    assert history.latest() is None
    assert history.points() == []
    assert len(history) == 0


def test_to_dict_uses_z_timestamps_and_keeps_nulls():
    data = to_dict(sample(0))
    assert data["recorded_at"] == "2026-10-06T09:00:00Z"
    assert data["cpu_pct"] is None
    assert data["mem_used_bytes"] == 2_000


def test_to_event_wraps_the_sample():
    event = to_event(sample(1))
    assert event["type"] == "server.health"
    assert event["data"]["cpu_pct"] == 11.0
