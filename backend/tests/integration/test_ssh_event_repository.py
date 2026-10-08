from datetime import UTC, datetime, timedelta

import pytest

from app.domain.ssh_event import SshEvent
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 8, 7, 0, tzinfo=UTC)


def event(journal_id="c1", minutes=0, outcome="accepted") -> SshEvent:
    return SshEvent.create(
        journal_id=journal_id,
        occurred_at=T0 + timedelta(minutes=minutes),
        outcome=outcome,
        username="sentinel-x",
        ip="192.168.0.18",
        port=49513 + minutes,
        method="publickey" if outcome == "accepted" else None,
        key_fingerprint="SHA256:abc" if outcome == "accepted" else None,
        key_comment="mael.namania@gmail.com" if outcome == "accepted" else None,
        reason=None if outcome == "accepted" else "key_rejected",
    )


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def test_add_refuses_a_second_event_with_the_same_journal_id(uow):
    async with uow as tx:
        assert await tx.ssh_events.add(event("c1")) is True
        assert await tx.ssh_events.add(event("c1", minutes=1)) is False
        await tx.commit()
    async with uow as tx:
        rows = await tx.ssh_events.list("all", 10)
    assert [r.journal_id for r in rows] == ["c1"]
    assert rows[0].key_comment == "mael.namania@gmail.com"


async def test_list_is_newest_first_filtered_and_limited(uow):
    async with uow as tx:
        for e in (event("a", 0), event("b", 2, "refused"), event("c", 1), event("d", 3, "refused")):
            await tx.ssh_events.add(e)
        await tx.commit()
    async with uow as tx:
        assert [r.journal_id for r in await tx.ssh_events.list("all", 10)] == ["d", "b", "c", "a"]
        assert [r.journal_id for r in await tx.ssh_events.list("refused", 10)] == ["d", "b"]
        assert [r.journal_id for r in await tx.ssh_events.list("accepted", 1)] == ["c"]
