from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.application.server.health import ServerHealth
from app.presentation.dependencies import CurrentUserIdDep, ServerHealthHistoryDep

router = APIRouter(prefix="/server", tags=["server"])


class ServerHealthResponse(BaseModel):
    recorded_at: datetime
    cpu_pct: float | None
    mem_total_bytes: int
    mem_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    temperature_c: float | None
    load_1: float
    load_5: float
    load_15: float
    uptime_s: int

    @classmethod
    def from_sample(cls, sample: ServerHealth) -> "ServerHealthResponse":
        return cls(**asdict(sample))


class ServerHealthEnvelope(BaseModel):
    latest: ServerHealthResponse | None
    history: list[ServerHealthResponse]


@router.get(
    "/health",
    response_model=ServerHealthEnvelope,
    summary="Santé du serveur : CPU, mémoire, disque, température, charge, uptime",
    description="Dernier échantillon et les 30 dernières minutes (un point toutes les 5 s), "
    "gardés en mémoire. Vide tant que le premier échantillon n'a pas abouti.",
)
async def get_server_health(
    _: CurrentUserIdDep, history: ServerHealthHistoryDep
) -> ServerHealthEnvelope:
    latest = history.latest()
    return ServerHealthEnvelope(
        latest=ServerHealthResponse.from_sample(latest) if latest else None,
        history=[ServerHealthResponse.from_sample(p) for p in history.points()],
    )
