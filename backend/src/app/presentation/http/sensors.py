from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.application.sensors.dtos import BucketOutput, DeviceOutput, ReadingInput, ReadingOutput
from app.application.sensors.queries import GetLatestReadings, GetReadings, ListDevices
from app.application.sensors.record import RecordReading
from app.presentation.dependencies import (
    CurrentUserIdDep,
    DeviceKeyDep,
    HubDep,
    ThresholdsDep,
    UowDep,
)

router = APIRouter(prefix="/sensors", tags=["sensors"])

BUCKET_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
Bucket = Literal["1m", "5m", "15m", "1h"]


class GasPayload(BaseModel):
    mostGaz: bool = False  # noqa: N815 - key chosen by the firmware
    quantity: int | None = Field(default=None, ge=0)


class TemperaturePayload(BaseModel):
    humidity: float | None = None
    temp: float | None = None


class ReadingRequest(BaseModel):
    """Exactly what the ESP32 sends (see the « data ESP32 » note)."""

    device_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    recorded_at: datetime | None = None
    gaz: GasPayload | None = None
    temperature: TemperaturePayload | None = None

    def to_input(self) -> ReadingInput:
        return ReadingInput(
            device_id=self.device_id,
            recorded_at=self.recorded_at,
            temperature_c=self.temperature.temp if self.temperature else None,
            humidity_pct=self.temperature.humidity if self.temperature else None,
            gas_level=self.gaz.quantity if self.gaz else None,
            gas_alert=self.gaz.mostGaz if self.gaz else False,
        )


class ReadingResponse(BaseModel):
    id: UUID
    device_id: str
    recorded_at: datetime
    temperature_c: float | None
    humidity_pct: float | None
    gas_level: int | None
    gas_alert: bool

    @classmethod
    def from_output(cls, output: ReadingOutput) -> "ReadingResponse":
        return cls(
            id=output.id,
            device_id=output.device_id,
            recorded_at=output.recorded_at,
            temperature_c=output.temperature_c,
            humidity_pct=output.humidity_pct,
            gas_level=output.gas_level,
            gas_alert=output.gas_alert,
        )


class BucketResponse(BaseModel):
    bucket_start: datetime
    count: int
    temperature_avg: float | None
    temperature_min: float | None
    temperature_max: float | None
    humidity_avg: float | None
    humidity_min: float | None
    humidity_max: float | None
    gas_avg: float | None
    gas_min: int | None
    gas_max: int | None
    gas_alerts: int

    @classmethod
    def from_output(cls, output: BucketOutput) -> "BucketResponse":
        return cls(
            bucket_start=output.bucket_start,
            count=output.count,
            temperature_avg=output.temperature_avg,
            temperature_min=output.temperature_min,
            temperature_max=output.temperature_max,
            humidity_avg=output.humidity_avg,
            humidity_min=output.humidity_min,
            humidity_max=output.humidity_max,
            gas_avg=output.gas_avg,
            gas_min=output.gas_min,
            gas_max=output.gas_max,
            gas_alerts=output.gas_alerts,
        )


class DeviceResponse(BaseModel):
    device_id: str
    last_seen: datetime

    @classmethod
    def from_output(cls, output: DeviceOutput) -> "DeviceResponse":
        return cls(device_id=output.device_id, last_seen=output.last_seen)


def _utc(moment: datetime | None, default: datetime) -> datetime:
    if moment is None:
        return default
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@router.post(
    "/readings",
    status_code=status.HTTP_201_CREATED,
    response_model=ReadingResponse,
    summary="Enregistre une mesure envoyée par un appareil",
    description="Authentification par l'en-tête `X-Device-Key` (réglage `DEVICE_API_KEY`). "
    "La mesure est stockée puis diffusée sur le WebSocket (`sensor.reading`). Un `recorded_at` "
    "absent, plus de 5 min dans le futur ou plus vieux que 30 jours est remplacé par l'heure du "
    "serveur.",
)
async def post_reading(
    body: ReadingRequest, _: DeviceKeyDep, uow: UowDep, hub: HubDep, thresholds: ThresholdsDep
) -> ReadingResponse:
    use_case = RecordReading(uow=uow, broadcaster=hub, thresholds=thresholds)
    output = await use_case.execute(body.to_input())
    return ReadingResponse.from_output(output)


@router.get(
    "/readings",
    response_model=list[ReadingResponse] | list[BucketResponse],
    summary="Historique des mesures d'un appareil",
    description="Sans `bucket` : mesures brutes (2000 max). Avec `bucket` (`1m`, `5m`, `15m`, "
    "`1h`) : moyennes, min, max et nombre d'alertes par intervalle. `from` vaut maintenant − 1 h "
    "par défaut, `to` maintenant.",
)
async def get_readings(
    _: CurrentUserIdDep,
    uow: UowDep,
    device_id: Annotated[str, Query(pattern=r"^[a-z0-9-]{1,64}$")],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    bucket: Annotated[Bucket | None, Query()] = None,
) -> list[ReadingResponse] | list[BucketResponse]:
    now = datetime.now(UTC)
    since = _utc(from_, now - timedelta(hours=1))
    until = _utc(to, now)
    rows = await GetReadings(uow=uow).execute(
        device_id, since, until, BUCKET_SECONDS[bucket] if bucket else None
    )
    if bucket:
        return [BucketResponse.from_output(b) for b in rows]  # type: ignore[arg-type]
    return [ReadingResponse.from_output(r) for r in rows]  # type: ignore[arg-type]


@router.get("/latest", response_model=list[ReadingResponse], summary="Dernière mesure par appareil")
async def get_latest(_: CurrentUserIdDep, uow: UowDep) -> list[ReadingResponse]:
    return [ReadingResponse.from_output(r) for r in await GetLatestReadings(uow=uow).execute()]


@router.get("/devices", response_model=list[DeviceResponse], summary="Appareils connus")
async def get_devices(_: CurrentUserIdDep, uow: UowDep) -> list[DeviceResponse]:
    return [DeviceResponse.from_output(d) for d in await ListDevices(uow=uow).execute()]
