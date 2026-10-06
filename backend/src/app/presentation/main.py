import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.application.server.health import HealthHistory
from app.infrastructure.camera.httpx_source import HttpxCameraSource
from app.infrastructure.camera.relay import CameraRelay
from app.infrastructure.config import Settings
from app.infrastructure.db.engine import create_engine, create_session_factory
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.mqtt.client import connect_factory
from app.infrastructure.mqtt.subscriber import MqttSubscriber
from app.infrastructure.realtime.hub import ConnectionHub
from app.infrastructure.system.monitor import ServerHealthMonitor
from app.infrastructure.system.procfs import ProcfsSampler
from app.presentation.http import auth, camera, health, sensors, server, users
from app.presentation.http.errors import register_error_handlers
from app.presentation.ws import router as ws_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [
            task
            for task in (_start_mqtt_subscriber(app, settings), _start_server_health(app, settings))
            if task is not None
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await engine.dispose()

    app = FastAPI(
        title="sentinel-x API",
        version="0.1.0",
        description="Authentification JWT, canal WebSocket temps réel, relais vidéo caméra et "
        "mesures capteurs.",
        root_path=settings.api_root_path,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.thresholds = settings.thresholds()
    app.state.session_factory = create_session_factory(engine)
    app.state.hub = ConnectionHub()
    app.state.camera_relay = _build_camera_relay(settings)
    app.state.server_health = HealthHistory()

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(camera.router)
    app.include_router(sensors.router)
    app.include_router(server.router)
    app.include_router(ws_router.router)
    return app


def _build_camera_relay(settings: Settings) -> CameraRelay | None:
    if not settings.camera_stream_url:
        return None
    return CameraRelay(HttpxCameraSource(settings.camera_stream_url).open)


def _start_mqtt_subscriber(app: FastAPI, settings: Settings) -> asyncio.Task[None] | None:
    """Subscribe to the devices' topic when a broker is configured. Readings go through
    RecordReading, exactly like the HTTP route, so storage and WebSocket push are shared."""
    if not settings.mqtt_host:
        return None
    subscriber = MqttSubscriber(
        connect=connect_factory(settings.mqtt_host, settings.mqtt_port),
        topic=settings.mqtt_topic,
        uow_factory=lambda: SqlAlchemyUnitOfWork(app.state.session_factory),
        broadcaster=app.state.hub,
        thresholds=app.state.thresholds,
    )
    return asyncio.create_task(subscriber.run(), name="mqtt-subscriber")


def _start_server_health(app: FastAPI, settings: Settings) -> asyncio.Task[None] | None:
    """Sample the host every few seconds for the dashboard's server card. Disabled in tests."""
    if not settings.server_health_enabled:
        return None
    monitor = ServerHealthMonitor(
        sampler=ProcfsSampler(
            proc=settings.host_proc_path,
            thermal=settings.host_thermal_path,
            disk=settings.host_disk_path,
        ),
        history=app.state.server_health,
        broadcaster=app.state.hub,
        interval=settings.server_health_interval_s,
    )
    return asyncio.create_task(monitor.run(), name="server-health-monitor")
