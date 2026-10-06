"""Send plausible fake readings to the API, to see the dashboard without hardware.

    uv run simulate-sensors [--base-url http://localhost:8000] [--device esp-interieur]
                            [--interval 2] [--count N] [--backfill-minutes M]

--backfill-minutes M posts one reading per minute over the last M minutes (timestamped), then
exits; without it the command streams live readings every --interval seconds.

The device key is read from DEVICE_API_KEY (the .env file is honoured through Settings).
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.infrastructure.config import Settings

GAS_ALERT_PPM = 1500


class SensorWalk:
    """Bounded random walk: small drifts, with an occasional gas spike."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.temperature = 22.0
        self.humidity = 45.0
        self.gas = 400.0

    def _step(self, value: float, step: float, low: float, high: float) -> float:
        return min(high, max(low, value + self._rng.uniform(-step, step)))

    def next_payload(self, device_id: str) -> dict[str, Any]:
        self.temperature = self._step(self.temperature, 0.3, 15.0, 35.0)
        self.humidity = self._step(self.humidity, 1.0, 20.0, 90.0)
        if self._rng.random() < 0.02:  # a spike that takes a few readings to decay
            self.gas = min(3000.0, self.gas + self._rng.uniform(800, 1500))
        else:
            self.gas = self._step(self.gas * 0.9 + 40, 30, 200.0, 3000.0)
        quantity = int(round(self.gas))
        return {
            "device_id": device_id,
            "gaz": {"mostGaz": quantity >= GAS_ALERT_PPM, "quantity": quantity},
            "temperature": {
                "humidity": round(self.humidity, 1),
                "temp": round(self.temperature, 1),
            },
        }


def run(
    base_url: str,
    device_key: str,
    device_id: str,
    interval: float,
    count: int | None,
    transport: httpx.BaseTransport | None = None,
    log: Callable[[str], None] = print,
    backfill_minutes: int | None = None,
) -> int:
    """Post readings until `count` is reached (or forever). Returns how many were accepted.

    With `backfill_minutes`, posts one timestamped reading per minute over that span (oldest
    first) and returns, so the dashboard has history to show.
    """
    walk = SensorWalk(random.Random())
    sent = 0
    headers = {"X-Device-Key": device_key}
    with httpx.Client(base_url=base_url, transport=transport, timeout=5.0) as client:
        if backfill_minutes is not None:
            end = datetime.now(UTC).replace(microsecond=0)
            for offset in range(backfill_minutes - 1, -1, -1):
                payload = walk.next_payload(device_id)
                payload["recorded_at"] = (end - timedelta(minutes=offset)).isoformat()
                response = client.post("/sensors/readings", json=payload, headers=headers)
                if response.status_code != 201:
                    log(f"refusé ({response.status_code}) : {response.text}")
                    return sent
                sent += 1
            log(f"{sent} mesures d'historique envoyées pour {device_id}")
            return sent

        while count is None or sent < count:
            payload = walk.next_payload(device_id)
            response = client.post("/sensors/readings", json=payload, headers=headers)
            if response.status_code != 201:
                log(f"refusé ({response.status_code}) : {response.text}")
                break
            sent += 1
            log(
                f"{device_id}: {payload['temperature']['temp']} °C, "
                f"{payload['temperature']['humidity']} %, {payload['gaz']['quantity']} mV"
                + (" ALERTE" if payload["gaz"]["mostGaz"] else "")
            )
            if count is None or sent < count:
                time.sleep(interval)
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Envoie des mesures factices à l'API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--device", default="esp-interieur")
    parser.add_argument("--interval", type=float, default=2.0, help="secondes entre deux mesures")
    parser.add_argument("--count", type=int, default=None, help="nombre de mesures (infini sinon)")
    parser.add_argument(
        "--backfill-minutes",
        type=int,
        default=None,
        help="remplit l'historique (une mesure par minute sur N minutes) puis quitte",
    )
    args = parser.parse_args(argv)
    key = Settings().device_api_key
    if not key:
        print("DEVICE_API_KEY manquant dans backend/.env", file=sys.stderr)
        return 2
    try:
        run(
            args.base_url,
            key,
            args.device,
            args.interval,
            args.count,
            backfill_minutes=args.backfill_minutes,
        )
    except KeyboardInterrupt:
        pass
    return 0


def simulate_sensors_command() -> None:
    raise SystemExit(main())
