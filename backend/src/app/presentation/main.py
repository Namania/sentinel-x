import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.application.alerts.siren import Siren
from app.application.server.health import HealthHistory
from app.infrastructure.camera.httpx_source import HttpxCameraSource
from app.infrastructure.camera.relay import CameraRelay
from app.infrastructure.config import Settings
from app.infrastructure.db.engine import create_engine, create_session_factory
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.mqtt.client import connect_factory
from app.infrastructure.mqtt.publisher import MqttSirenPublisher
from app.infrastructure.mqtt.subscriber import MqttSubscriber
from app.infrastructure.realtime.hub import ConnectionHub
from app.infrastructure.system.monitor import ServerHealthMonitor
from app.infrastructure.system.procfs import ProcfsSampler
from app.presentation.http import alerts, auth, camera, health, sensors, server, users
from app.presentation.http.errors import register_error_handlers
from app.presentation.ws import router as ws_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = [
            task
            for task in (
                _start_mqtt_subscriber(app, settings),
                _start_server_health(app, settings),
                _start_vision_worker(app, settings),
            )
            if task is not None
        ]
        await _announce_siren(app)
        try:
            yield
        finally:
            app.state.siren.close()
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
    app.state.siren = Siren(
        uow_factory=lambda: SqlAlchemyUnitOfWork(app.state.session_factory),
        publisher=_build_siren_publisher(settings),
        broadcaster=app.state.hub,
        triggers=settings.triggers(),
        mute_minutes=settings.buzzer_mute_minutes,
    )
    app.state.camera_relay = _build_camera_relay(settings)
    app.state.server_health = HealthHistory()

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(camera.router)
    app.include_router(sensors.router)
    app.include_router(alerts.router)
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
        on_alerts_changed=app.state.siren.refresh,
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


def _build_siren_publisher(settings: Settings) -> MqttSirenPublisher | None:
    """The ESP32 buzzer listens on a retained topic; without a broker the state is only shown."""
    if not settings.mqtt_host:
        return None
    connect = connect_factory(settings.mqtt_host, settings.mqtt_port, identifier="sentinel-x-siren")
    return MqttSirenPublisher(connect, settings.mqtt_buzzer_topic)


async def _announce_siren(app: FastAPI) -> None:
    """Publish the real state at start: the broker may still hold yesterday's retained `on`."""
    try:
        await app.state.siren.refresh()
    except Exception:  # noqa: BLE001 - the database may not be ready; the first alert will refresh
        logger.warning("siren: initial state not published", exc_info=True)


def _start_vision_worker(app: FastAPI, settings: Settings) -> asyncio.Task[None] | None:
    """Person detection (and optional face identification) on the camera stream."""
    if not settings.vision_enabled:
        return None
    camera_relay: CameraRelay | None = app.state.camera_relay
    if camera_relay is None:
        logger.warning("VISION_ENABLED is set but no camera is configured; vision worker disabled")
        return None

    import cv2

    from app.application.alerts.intruder import TrackBlacklistAlerts
    from app.infrastructure.vision.detection_worker import DetectionWorker
    from app.infrastructure.vision.face_whitelist import FaceEncoder, FaceList
    from app.infrastructure.vision.light_analyzer import LightVisionAnalyzer
    from app.infrastructure.vision.person_detector import PersonDetector

    models_dir = Path(settings.vision_models_dir)
    cv2.setNumThreads(settings.vision_threads)
    try:
        detector = PersonDetector(models_dir)
        faces = None
        blacklist = None
        if settings.vision_identify_faces:
            encoder = FaceEncoder(models_dir)
            known_faces_dir = Path(settings.vision_known_faces_dir)
            faces = (encoder, FaceList.load(known_faces_dir, encoder, label="whitelist"))
            blacklist = (
                encoder,
                FaceList.load(known_faces_dir / "blacklist", encoder, label="blacklist"),
            )
    except cv2.error:
        logger.exception(
            "vision models missing or unreadable in %s (the Docker image provides them); "
            "vision worker disabled",
            models_dir,
        )
        return None

    whitelist = faces[1] if faces is not None else None
    blacklisted = blacklist[1] if blacklist is not None else None
    analyzer = LightVisionAnalyzer(detector, faces, blacklist)
    blacklist_alerts = (
        TrackBlacklistAlerts(
            uow_factory=lambda: SqlAlchemyUnitOfWork(app.state.session_factory),
            broadcaster=app.state.hub,
            on_alerts_changed=app.state.siren.refresh,
        )
        if blacklisted is not None
        else None
    )
    worker = DetectionWorker(
        frames=camera_relay.frames(),
        analyzer=analyzer,
        broadcaster=app.state.hub,
        interval_seconds=settings.vision_interval_seconds,
        blacklist_alerts=blacklist_alerts,
    )
    logger.info(
        "vision worker starting (face identification %s, %d known face(s), %d blacklisted)",
        "on" if whitelist is not None else "off",
        whitelist.size if whitelist is not None else 0,
        blacklisted.size if blacklisted is not None else 0,
    )
    return asyncio.create_task(worker.run(), name="vision-detection-worker")
