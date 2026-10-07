from datetime import UTC, datetime

from app.application.alerts.intruder import DEVICE_PREFIX, TrackBlacklistAlerts
from tests.unit.fakes import InMemoryUnitOfWork

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)

    async def send_to_user(self, user_id, event):
        self.events.append(event)


def _tracker(uow, bus, on_alerts_changed=None):
    return TrackBlacklistAlerts(
        uow_factory=lambda: uow,
        broadcaster=bus,
        on_alerts_changed=on_alerts_changed,
        clock=lambda: NOW,
    )


async def test_a_newly_seen_blacklisted_person_opens_an_alert():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await _tracker(uow, bus).sync(frozenset({"marc"}), {"marc": 0.9})

    assert len(uow.alerts.alerts) == 1
    alert = uow.alerts.alerts[0]
    assert alert.device_id == f"{DEVICE_PREFIX}marc"
    assert alert.metric == "intruder"
    assert alert.is_open
    assert alert.opened_value == 0.9
    assert len(bus.events) == 1
    assert bus.events[0]["type"] == "alert.opened"
    assert bus.events[0]["data"]["device_id"] == f"{DEVICE_PREFIX}marc"


async def test_a_person_no_longer_seen_resolves_their_alert():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    tracker = _tracker(uow, bus)
    await tracker.sync(frozenset({"marc"}), {"marc": 0.9})
    bus.events.clear()

    await tracker.sync(frozenset(), {})

    assert len(uow.alerts.alerts) == 1
    assert not uow.alerts.alerts[0].is_open
    assert bus.events[0]["type"] == "alert.resolved"


async def test_a_person_still_seen_does_not_reopen_or_duplicate_the_alert():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    tracker = _tracker(uow, bus)
    await tracker.sync(frozenset({"marc"}), {"marc": 0.9})
    bus.events.clear()

    await tracker.sync(frozenset({"marc"}), {"marc": 0.95})

    assert len(uow.alerts.alerts) == 1  # no duplicate alert
    assert bus.events == []  # no event: nothing changed


async def test_two_blacklisted_people_get_independent_alerts():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await _tracker(uow, bus).sync(frozenset({"marc", "alex"}), {"marc": 0.9, "alex": 0.8})

    assert {a.device_id for a in uow.alerts.alerts} == {
        f"{DEVICE_PREFIX}marc",
        f"{DEVICE_PREFIX}alex",
    }
    assert all(a.is_open for a in uow.alerts.alerts)


async def test_nothing_happens_when_nobody_is_seen_and_nothing_was_open():
    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    await _tracker(uow, bus).sync(frozenset(), {})

    assert uow.alerts.alerts == []
    assert bus.events == []
    assert not uow.committed  # no database round trip either


async def test_on_alerts_changed_is_called_once_per_sync_with_a_change():
    calls = []

    async def hook():
        calls.append(1)

    uow, bus = InMemoryUnitOfWork(), RecordingBroadcaster()
    tracker = _tracker(uow, bus, on_alerts_changed=hook)
    await tracker.sync(frozenset({"marc"}), {"marc": 0.9})
    assert calls == [1]

    await tracker.sync(frozenset({"marc"}), {"marc": 0.9})  # unchanged
    assert calls == [1]
