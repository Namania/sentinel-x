"""Turn an MQTT message from an ESP32 into a `ReadingInput`.

Topic: `sentinel/<device>` — the last segment is the device id.
Payload (indoor ESP32, see esp32/esp_interieur.cc):

    {"temperature": 22.5 | null, "humidite": 48 | null, "gaz_mv": 1234,
     "etat_gaz": "prechauffage" | "ok" | "alerte"}

The MQ-2 reports a raw level in millivolts; during warm-up the value is meaningless and
is stored as missing. The server timestamps the reading (the ESP has no reliable clock).
"""

from __future__ import annotations

import json
from typing import Any

from app.application.sensors.dtos import ReadingInput
from app.domain.errors import InvalidReading

WARM_UP_STATE = "prechauffage"
ALERT_STATE = "alerte"


def _number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidReading(f"{key} must be a number")
    return float(value)


def parse_device_message(topic: str, payload: bytes) -> ReadingInput:
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidReading("payload is not valid JSON") from exc
    if not isinstance(data, dict):
        raise InvalidReading("payload must be a JSON object")

    state = data.get("etat_gaz")
    gas = _number(data, "gaz_mv")
    return ReadingInput(
        device_id=topic.rsplit("/", 1)[-1].lower(),
        recorded_at=None,
        temperature_c=_number(data, "temperature"),
        humidity_pct=_number(data, "humidite"),
        gas_level=None if gas is None or state == WARM_UP_STATE else int(round(gas)),
        gas_alert=state == ALERT_STATE,
    )
