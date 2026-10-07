import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.presentation.main import create_app
from tests.integration.conftest import TEST_SETTINGS, create_user_and_login


def write_fake_host(root: Path) -> None:
    proc = root / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  100 0 100 700 100 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal: 8000000 kB\nMemAvailable: 6000000 kB\n")
    (proc / "loadavg").write_text("0.42 0.38 0.31 1/234 5678\n")
    (proc / "uptime").write_text("86400.55 300000.00\n")
    zone = root / "thermal" / "thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "temp").write_text("48200\n")


def test_the_monitor_runs_with_the_app_when_enabled(tmp_path: Path):
    write_fake_host(tmp_path)
    settings = TEST_SETTINGS.model_copy(
        update={
            "server_health_enabled": True,
            "server_health_interval_s": 0.05,
            "host_proc_path": tmp_path / "proc",
            "host_thermal_path": tmp_path / "thermal",
            "host_disk_path": tmp_path,
        }
    )
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": f"Bearer {create_user_and_login(client)['access_token']}"}
        deadline = time.monotonic() + 3
        body = {"latest": None}
        while body["latest"] is None and time.monotonic() < deadline:
            body = client.get("/server/health", headers=headers).json()
            time.sleep(0.05)
        assert body["latest"] is not None
        assert body["latest"]["temperature_c"] == 48.2
        assert body["latest"]["mem_total_bytes"] == 8_192_000_000
        assert body["latest"]["disk_total_bytes"] > 0
