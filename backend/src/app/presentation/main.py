from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infrastructure.camera.httpx_source import HttpxCameraSource
from app.infrastructure.camera.relay import CameraRelay
from app.infrastructure.config import Settings
from app.infrastructure.db.engine import create_engine, create_session_factory
from app.infrastructure.realtime.hub import ConnectionHub
from app.presentation.http import auth, camera, health, users
from app.presentation.http.errors import register_error_handlers
from app.presentation.ws import router as ws_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(
        title="sentinel-x API",
        version="0.1.0",
        description="Authentification JWT, canal WebSocket temps réel et relais vidéo caméra.",
        root_path=settings.api_root_path,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = create_session_factory(engine)
    app.state.hub = ConnectionHub()
    app.state.camera_relay = _build_camera_relay(settings)

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(camera.router)
    app.include_router(ws_router.router)
    return app


def _build_camera_relay(settings: Settings) -> CameraRelay | None:
    if not settings.camera_stream_url:
        return None
    return CameraRelay(HttpxCameraSource(settings.camera_stream_url).open)
