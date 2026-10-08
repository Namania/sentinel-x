from datetime import UTC, datetime
from uuid import UUID

from app.domain.ssh_event import SshEvent

AT = datetime(2026, 10, 8, 7, 37, 35, tzinfo=UTC)


def test_create_generates_an_id_and_defaults_the_optional_fields():
    event = SshEvent.create(
        journal_id="s=1;i=2",
        occurred_at=AT,
        outcome="refused",
        username="root",
        ip="203.0.113.5",
        port=51234,
        reason="unknown_user",
    )
    assert isinstance(event.id, UUID)
    assert (event.method, event.key_fingerprint, event.key_comment) == (None, None, None)
    assert event.reason == "unknown_user"
    assert event.occurred_at == AT


def test_two_events_never_share_an_id():
    kwargs = dict(
        journal_id="x", occurred_at=AT, outcome="accepted", username="u", ip="1.2.3.4", port=1
    )
    assert SshEvent.create(**kwargs).id != SshEvent.create(**kwargs).id
