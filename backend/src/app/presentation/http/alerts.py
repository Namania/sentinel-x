from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.application.alerts.dtos import AlertOutput
from app.domain.alert import Alert, Direction, Metric
from app.domain.repositories import AlertStatus
from app.presentation.dependencies import CurrentUserIdDep, UowDep

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float
    opened_at: datetime
    opened_value: float
    peak_value: float
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def from_entity(cls, alert: Alert) -> "AlertResponse":
        return cls(**asdict(AlertOutput.from_entity(alert)))


class AlertSummary(BaseModel):
    open: int = Field(ge=0)


@router.get(
    "",
    response_model=list[AlertResponse],
    summary="Alertes capteurs : ouvertes d'abord, puis les plus récentes",
    description="Une alerte s'ouvre quand une mesure sort des bornes (réglages `ALERT_*`) et se "
    "ferme seule quand la mesure revient dans les bornes, avec hystérésis.",
)
async def list_alerts(
    _: CurrentUserIdDep,
    uow: UowDep,
    status: Annotated[AlertStatus, Query()] = "all",
    device_id: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,64}$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertResponse]:
    async with uow as tx:
        alerts = await tx.alerts.list(status, device_id, limit)
    return [AlertResponse.from_entity(a) for a in alerts]


@router.get("/summary", response_model=AlertSummary, summary="Nombre d'alertes ouvertes")
async def alert_summary(_: CurrentUserIdDep, uow: UowDep) -> AlertSummary:
    async with uow as tx:
        return AlertSummary(open=await tx.alerts.count_open())
