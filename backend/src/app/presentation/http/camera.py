from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.presentation.dependencies import CameraRelayDep, StreamUserIdDep

router = APIRouter(prefix="/camera", tags=["camera"])

BOUNDARY = "sentinel-x-frame"
MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"


@router.get(
    "/stream",
    summary="Flux vidéo MJPEG de la caméra",
    description=(
        "Relaie le flux de la caméra ESP32. Authentification par en-tête `Authorization: "
        "Bearer` ou par `?token=<access_token>` (pour une balise `<img>`)."
    ),
    response_class=StreamingResponse,
    responses={
        200: {"content": {MEDIA_TYPE: {}}, "description": "Flux MJPEG"},
        401: {"description": "Token manquant ou invalide"},
        503: {"description": "Aucune caméra configurée (CAMERA_STREAM_URL)"},
    },
)
async def stream(_: StreamUserIdDep, relay: CameraRelayDep) -> StreamingResponse:
    if relay is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Camera not configured"
        )
    return StreamingResponse(
        _mjpeg(relay.frames()), media_type=MEDIA_TYPE, headers={"Cache-Control": "no-store"}
    )


async def _mjpeg(frames: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    async for frame in frames:
        yield (
            (
                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n"
            ).encode()
            + frame
            + b"\r\n"
        )


class CameraStatusResponse(BaseModel):
    configured: bool
    viewers: int
    # Frames relayed since the API started; the front compares two readings to spot a stalled
    # upstream and reopens its <img>, which an MJPEG stream that simply stops never signals.
    frames: int


@router.get(
    "/status",
    summary="État du relais caméra",
    description="Indique si une caméra est configurée (CAMERA_STREAM_URL) et combien de "
    "spectateurs regardent le flux relayé.",
    response_model=CameraStatusResponse,
)
async def camera_status(_: StreamUserIdDep, relay: CameraRelayDep) -> CameraStatusResponse:
    return CameraStatusResponse(
        configured=relay is not None,
        viewers=relay.viewer_count if relay else 0,
        frames=relay.frames_received if relay else 0,
    )
