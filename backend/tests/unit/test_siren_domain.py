from datetime import UTC, datetime, timedelta

import pytest

from app.domain.alert import Alert
from app.domain.siren import SirenState, Trigger, decide, parse_triggers

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
DEFAULT = parse_triggers("gas,temperature:high")


def alert(metric="temperature", direction="high") -> Alert:
    return Alert.open(
        device_id="esp-interieur",
        metric=metric,
        direction=direction,
        threshold=30.0,
        at=NOW,
        value=31.0,
    )


def test_parse_triggers_reads_metric_and_optional_direction():
    assert parse_triggers("gas,temperature:high") == (
        Trigger("gas", None),
        Trigger("temperature", "high"),
    )
    assert parse_triggers(" humidity:low , gas ") == (
        Trigger("humidity", "low"),
        Trigger("gas", None),
    )
    assert parse_triggers("") == ()


@pytest.mark.parametrize("spec", ["pressure", "temperature:sideways", "gas:high:now"])
def test_parse_triggers_rejects_unknown_tokens(spec):
    with pytest.raises(ValueError):
        parse_triggers(spec)


def test_no_open_alert_means_silence():
    assert decide([], DEFAULT, None, NOW) == SirenState(
        on=False, reason=None, open=0, muted_until=None
    )


def test_only_trigger_metrics_sound():
    humidity = alert("humidity", "high")
    cold = alert("temperature", "low")
    assert decide([humidity, cold], DEFAULT, None, NOW) == SirenState(
        on=False, reason=None, open=2, muted_until=None
    )
    assert decide([alert("temperature", "high")], DEFAULT, None, NOW).on is True


def test_gas_is_the_reason_before_temperature():
    state = decide([alert("temperature", "high"), alert("gas", "high")], DEFAULT, None, NOW)
    assert (state.on, state.reason, state.open) == (True, "gas", 2)


def test_an_active_mute_silences_but_keeps_the_reason():
    until = NOW + timedelta(minutes=10)
    state = decide([alert("gas", "high")], DEFAULT, until, NOW)
    assert state == SirenState(on=False, reason="gas", open=1, muted_until=until)


def test_an_expired_mute_is_forgotten():
    state = decide([alert("gas", "high")], DEFAULT, NOW - timedelta(seconds=1), NOW)
    assert state == SirenState(on=True, reason="gas", open=1, muted_until=None)


def test_empty_triggers_never_sound():
    assert decide([alert("gas", "high")], (), None, NOW).on is False


def test_a_metric_without_bounds_is_not_a_trigger():
    """Only the sensor metrics can ring the buzzer: "intruder" was removed with the camera alert."""
    with pytest.raises(ValueError, match="unknown metric"):
        parse_triggers("gas,intruder")
