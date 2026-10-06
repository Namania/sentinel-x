from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.system.procfs import ProcfsSampler, SamplingError

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)

STAT_1 = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 200 1300 200 0 0 0 0 0\ncpu0 100 0 100 650 100 0 0 0 0 0\n"
MEMINFO = "MemTotal:        8000000 kB\nMemFree:         1000000 kB\nMemAvailable:    6000000 kB\n"
LOADAVG = "0.42 0.38 0.31 1/234 5678\n"
UPTIME = "86400.55 300000.00\n"


def fake_statvfs(_: Path) -> SimpleNamespace:
    return SimpleNamespace(f_blocks=1000, f_bfree=250, f_bavail=200, f_frsize=4096)


@pytest.fixture
def host(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text(STAT_1)
    (proc / "meminfo").write_text(MEMINFO)
    (proc / "loadavg").write_text(LOADAVG)
    (proc / "uptime").write_text(UPTIME)
    zone = tmp_path / "thermal" / "thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "temp").write_text("48200\n")
    (tmp_path / "root").mkdir()
    return tmp_path


def make_sampler(host: Path, **overrides) -> ProcfsSampler:
    kwargs = dict(
        proc=host / "proc",
        thermal=host / "thermal",
        disk=host / "root",
        statvfs=fake_statvfs,
        clock=lambda: NOW,
    )
    kwargs.update(overrides)
    return ProcfsSampler(**kwargs)


def cpu_of(sampler: ProcfsSampler) -> float | None:
    return sampler.sample().cpu_pct


def test_first_sample_reads_every_field_but_has_no_cpu_delta(host: Path):
    sample = make_sampler(host).sample()
    assert sample.recorded_at == NOW
    assert sample.cpu_pct is None
    assert (sample.mem_total_bytes, sample.mem_used_bytes) == (8_192_000_000, 2_048_000_000)
    assert (sample.disk_total_bytes, sample.disk_used_bytes) == (4_096_000, 3_072_000)
    assert sample.temperature_c == 48.2
    assert (sample.load_1, sample.load_5, sample.load_15) == (0.42, 0.38, 0.31)
    assert sample.uptime_s == 86_401


def test_second_sample_computes_cpu_from_the_delta(host: Path):
    sampler = make_sampler(host)
    sampler.sample()
    (host / "proc" / "stat").write_text(STAT_2)
    # Δtotal = 900, Δidle = (1300 + 200) - (700 + 100) = 700 → 22.2 %
    assert cpu_of(sampler) == pytest.approx(22.22, abs=0.01)


def test_unchanged_counters_give_no_cpu_value(host: Path):
    sampler = make_sampler(host)
    sampler.sample()
    assert cpu_of(sampler) is None


def test_four_field_cpu_line_is_accepted(host: Path):
    (host / "proc" / "stat").write_text("cpu 100 0 100 800\n")
    sampler = make_sampler(host)
    sampler.sample()
    (host / "proc" / "stat").write_text("cpu 200 0 200 1500\n")
    # Δtotal = 900, Δidle = 700 → 22.2 %, iowait treated as 0
    assert cpu_of(sampler) == pytest.approx(22.22, abs=0.01)


def test_missing_thermal_zone_means_no_temperature(host: Path):
    sample = make_sampler(host, thermal=host / "nowhere").sample()
    assert sample.temperature_c is None


def test_truncated_meminfo_is_a_sampling_error(host: Path):
    (host / "proc" / "meminfo").write_text("MemTotal:        8000000 kB\n")
    with pytest.raises(SamplingError):
        make_sampler(host).sample()


def test_missing_proc_is_a_sampling_error(host: Path):
    with pytest.raises(SamplingError):
        make_sampler(host, proc=host / "nowhere").sample()


def test_unreadable_disk_path_is_a_sampling_error(host: Path):
    def boom(_: Path):
        raise FileNotFoundError("no such mount")

    with pytest.raises(SamplingError):
        make_sampler(host, statvfs=boom).sample()
