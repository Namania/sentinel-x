import pytest

from app.domain.errors import InvalidReading
from app.infrastructure.mqtt.parser import parse_device_message


def test_maps_the_indoor_esp_payload():
    reading = parse_device_message(
        "sentinel/esp1",
        b'{"temperature":22.5,"humidite":48,"gaz_mv":1234,"etat_gaz":"ok"}',
    )
    assert reading.device_id == "esp1"
    assert (reading.temperature_c, reading.humidity_pct) == (22.5, 48.0)
    assert (reading.gas_level, reading.gas_alert) == (1234, False)
    assert reading.recorded_at is None  # the server timestamps the reading


def test_alert_state_sets_the_flag():
    reading = parse_device_message("sentinel/esp1", b'{"gaz_mv":3000,"etat_gaz":"alerte"}')
    assert (reading.gas_level, reading.gas_alert) == (3000, True)


def test_warm_up_readings_carry_no_gas_level():
    reading = parse_device_message(
        "sentinel/esp1",
        b'{"temperature":21.0,"humidite":50,"gaz_mv":900,"etat_gaz":"prechauffage"}',
    )
    assert (reading.gas_level, reading.gas_alert) == (None, False)
    assert reading.temperature_c == 21.0


def test_null_sensor_values_are_kept_as_missing():
    reading = parse_device_message(
        "sentinel/esp1", b'{"temperature":null,"humidite":null,"gaz_mv":500,"etat_gaz":"ok"}'
    )
    assert (reading.temperature_c, reading.humidity_pct, reading.gas_level) == (None, None, 500)


def test_device_id_is_the_last_topic_segment_lowercased():
    assert parse_device_message("sentinel/ESP-Ext", b"{}").device_id == "esp-ext"


@pytest.mark.parametrize(
    "payload", [b"not json", b"[1,2]", b'{"gaz_mv":"abc"}', b'{"temperature":"x"}']
)
def test_rejects_malformed_payloads(payload):
    with pytest.raises(InvalidReading):
        parse_device_message("sentinel/esp1", payload)
