from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, model_validator

from app.application.ssh.dtos import ssh_event_to_dict
from app.application.ssh.record import SshEventInput
from app.domain.ssh_event import Outcome, Reason, SshEvent, SshEventFilter
from app.presentation.dependencies import CurrentUserIdDep, DeviceKeyDep, SshAccessDep, UowDep

router = APIRouter(prefix="/ssh", tags=["ssh"])


class SshEventRequest(BaseModel):
    """What scripts/ssh-log-agent.py sends for one sshd journal line."""

    journal_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    outcome: Outcome
    username: str = Field(min_length=1, max_length=64)
    ip: str = Field(min_length=1, max_length=45)
    port: int = Field(ge=1, le=65535)
    method: str | None = Field(default=None, max_length=32)
    key_fingerprint: str | None = Field(default=None, max_length=64)
    key_comment: str | None = Field(default=None, max_length=255)
    reason: Reason | None = None

    @model_validator(mode="after")
    def _reason_matches_outcome(self) -> "SshEventRequest":
        if self.outcome == "refused" and self.reason is None:
            raise ValueError("a refused connection needs a reason")
        if self.outcome == "accepted" and self.reason is not None:
            raise ValueError("an accepted connection has no reason")
        return self

    def to_input(self) -> SshEventInput:
        return SshEventInput(**self.model_dump())


class SshEventResponse(BaseModel):
    id: UUID
    journal_id: str
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None
    key_fingerprint: str | None
    key_comment: str | None
    reason: Reason | None

    @classmethod
    def from_entity(cls, event: SshEvent) -> "SshEventResponse":
        return cls(**ssh_event_to_dict(event))


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    response_model=SshEventResponse,
    summary="Enregistre une connexion SSH relayée par l'agent du Pi",
    description="Authentification par l'en-tête `X-Device-Key` (réglage `DEVICE_API_KEY`). "
    "Stockée puis diffusée sur le WebSocket (`ssh.event`) ; un refus ouvre ou incrémente l'alerte "
    "`ssh` de l'IP, résolue après `SSH_ALERT_QUIET_MINUTES` sans nouvelle tentative. Un "
    "`journal_id` déjà connu répond 200 sans rien changer.",
)
async def post_event(
    body: SshEventRequest, _: DeviceKeyDep, ssh_access: SshAccessDep, response: Response
) -> SshEventResponse:
    event, created = await ssh_access.record(body.to_input())
    if not created:
        response.status_code = status.HTTP_200_OK
    return SshEventResponse.from_entity(event)


@router.get(
    "/events",
    response_model=list[SshEventResponse],
    summary="Connexions SSH au Pi, les plus récentes d'abord",
)
async def list_events(
    _: CurrentUserIdDep,
    uow: UowDep,
    outcome: Annotated[SshEventFilter, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SshEventResponse]:
    async with uow as tx:
        events = await tx.ssh_events.list(outcome, limit)
    return [SshEventResponse.from_entity(e) for e in events]
