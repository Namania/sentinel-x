from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.application.alerts.dtos import AlertOutput
from app.domain.alert import Alert, Direction, Metric
from app.domain.repositories import AlertStatus
from app.domain.siren import SirenState
from app.presentation.dependencies import CurrentUserIdDep, SirenDep, SshAccessDep, UowDep

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
    device_id: Annotated[str | None, Query(pattern=r"^[a-z0-9.:-]{1,64}$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertResponse]:
    async with uow as tx:
        alerts = await tx.alerts.list(status, device_id, limit)
    return [AlertResponse.from_entity(a) for a in alerts]


@router.get("/summary", response_model=AlertSummary, summary="Nombre d'alertes ouvertes")
async def alert_summary(_: CurrentUserIdDep, uow: UowDep) -> AlertSummary:
    async with uow as tx:
        return AlertSummary(open=await tx.alerts.count_open())


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Clôturer à la main une alerte SSH ouverte",
    description="Les alertes capteurs se ferment seules quand la mesure revient dans les bornes ; "
    "une alerte `ssh` se ferme aussi d'elle-même après `SSH_ALERT_QUIET_MINUTES`, ou ici tout de "
    "suite. 404 si l'alerte n'existe pas, 409 si elle est déjà résolue ou n'est pas une alerte "
    "`ssh`. Diffuse `alert.resolved` et rafraîchit la sirène.",
)
async def resolve_alert(
    alert_id: UUID, user_id: CurrentUserIdDep, ssh_access: SshAccessDep
) -> AlertResponse:
    return AlertResponse.from_entity(await ssh_access.resolve(alert_id, by=user_id))


class SirenResponse(BaseModel):
    on: bool
    reason: Metric | None
    open: int
    muted_until: datetime | None

    @classmethod
    def from_state(cls, state: SirenState) -> "SirenResponse":
        return cls(on=state.on, reason=state.reason, open=state.open, muted_until=state.muted_until)


@router.get(
    "/siren",
    response_model=SirenResponse,
    summary="État de la sirène (buzzer de l'ESP32)",
    description="`on` quand une alerte ouverte correspond à `BUZZER_TRIGGERS` et qu'aucune coupure "
    "n'est en cours. L'état est relu depuis les alertes à chaque appel.",
)
async def siren_state(_: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.refresh())


@router.post(
    "/siren/mute", response_model=SirenResponse, summary="Couper la sirène quelques minutes"
)
async def mute_siren(user_id: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.mute(by=user_id))


@router.delete("/siren/mute", response_model=SirenResponse, summary="Réactiver la sirène")
async def unmute_siren(user_id: CurrentUserIdDep, siren: SirenDep) -> SirenResponse:
    return SirenResponse.from_state(await siren.unmute(by=user_id))
