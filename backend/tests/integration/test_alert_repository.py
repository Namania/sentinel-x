from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.alert import Alert
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def alert(device="esp-interieur", metric="temperature", minutes=0, resolved=False) -> Alert:
    a = Alert.open(
        device_id=device,
        metric=metric,
        direction="high",
        threshold=30.0,
        at=T0 + timedelta(minutes=minutes),
        value=30.4,
    )
    return a.resolve(at=T0 + timedelta(minutes=minutes + 5), value=29.0) if resolved else a


@pytest.fixture
async def uow(session_factory):
    return SqlAlchemyUnitOfWork(session_factory)


async def seed(uow, alerts):
    async with uow as tx:
        for a in alerts:
            await tx.alerts.add(a)
        await tx.commit()


async def test_open_for_finds_only_the_open_alert_of_that_device_and_metric(uow):
    open_temp = alert()
    await seed(uow, [alert(resolved=True, minutes=-60), open_temp, alert(metric="humidity")])
    async with uow as tx:
        found = await tx.alerts.open_for("esp-interieur", "temperature")
        assert found == open_temp
        assert await tx.alerts.open_for("esp-interieur", "gas") is None
        assert await tx.alerts.open_for("esp-exterieur", "temperature") is None


async def test_save_updates_peak_and_resolution(uow):
    a = alert()
    await seed(uow, [a])
    async with uow as tx:
        await tx.alerts.save(a.worsen(31.5).resolve(at=T0 + timedelta(minutes=9), value=29.0))
        await tx.commit()
    async with uow as tx:
        rows = await tx.alerts.list("all", None, 10)
        assert rows[0].peak_value == 31.5
        assert rows[0].resolved_at == T0 + timedelta(minutes=9)
        assert await tx.alerts.open_for("esp-interieur", "temperature") is None


async def test_list_orders_open_first_then_newest_and_filters(uow):
    old_resolved = alert(minutes=-120, resolved=True)
    new_resolved = alert(minutes=-30, resolved=True, metric="humidity")
    open_now = alert(metric="gas")
    other = alert(device="esp-exterieur", minutes=-10)
    await seed(uow, [old_resolved, new_resolved, open_now, other])
    async with uow as tx:
        everything = await tx.alerts.list("all", None, 10)
        assert [a.id for a in everything] == [
            open_now.id,
            other.id,
            new_resolved.id,
            old_resolved.id,
        ]
        assert [a.id for a in await tx.alerts.list("open", None, 10)] == [open_now.id, other.id]
        assert [a.id for a in await tx.alerts.list("resolved", "esp-interieur", 10)] == [
            new_resolved.id,
            old_resolved.id,
        ]
        assert len(await tx.alerts.list("all", None, 2)) == 2
        assert await tx.alerts.count_open() == 2


async def test_only_one_open_alert_per_device_and_metric(uow):
    await seed(uow, [alert()])
    with pytest.raises(IntegrityError):
        async with uow as tx:
            await tx.alerts.add(alert(minutes=1))
            await tx.commit()
    # A resolved one does not block a new open one.
    async with uow as tx:
        current = await tx.alerts.open_for("esp-interieur", "temperature")
        assert current is not None
        await tx.alerts.save(current.resolve(at=T0, value=29.0))
        await tx.alerts.add(alert(minutes=2))
        await tx.commit()


async def test_open_for_device_returns_the_open_alerts_by_metric(uow):
    temp, gas = alert(), alert(metric="gas")
    await seed(uow, [alert(resolved=True, minutes=-60), temp, gas, alert(device="esp-exterieur")])
    async with uow as tx:
        found = await tx.alerts.open_for_device("esp-interieur")
        assert found == {"temperature": temp, "gas": gas}
        assert await tx.alerts.open_for_device("esp-nowhere") == {}
