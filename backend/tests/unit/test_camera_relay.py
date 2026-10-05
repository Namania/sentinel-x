import asyncio

import pytest

from app.infrastructure.camera.relay import CameraRelay
from tests.unit.fakes import FakeCamera


async def next_frame(it, timeout: float = 1.0) -> bytes:
    return await asyncio.wait_for(anext(it), timeout)


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
def camera() -> FakeCamera:
    return FakeCamera()


@pytest.fixture
def relay(camera: FakeCamera) -> CameraRelay:
    return CameraRelay(camera.open, retry_delay=0.01)


async def test_subscriber_receives_frames_in_order(camera, relay):
    viewer = relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(viewer) == b"a"
    camera.push_frame(b"b")
    assert await next_frame(viewer) == b"b"
    await viewer.aclose()


async def test_upstream_is_opened_once_for_several_viewers(camera, relay):
    first, second = relay.frames(), relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(first) == b"a"
    assert await next_frame(second) == b"a"
    assert camera.opens == 1
    assert relay.viewer_count == 2
    await first.aclose()
    await second.aclose()


async def test_upstream_is_closed_when_last_viewer_leaves(camera, relay):
    first, second = relay.frames(), relay.frames()
    camera.push_frame(b"a")
    await next_frame(first)
    await next_frame(second)
    await first.aclose()
    assert camera.closes == 0
    await second.aclose()
    assert camera.closes == 1
    assert relay.viewer_count == 0


async def test_slow_viewer_skips_to_the_latest_frame(camera, relay):
    viewer = relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(viewer) == b"a"
    camera.push_frame(b"b")
    camera.push_frame(b"c")
    await wait_until(lambda: relay.frames_received == 3)
    assert await next_frame(viewer) == b"c"
    await viewer.aclose()


async def test_late_viewer_gets_the_last_frame_immediately(camera, relay):
    first = relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(first) == b"a"
    late = relay.frames()
    assert await next_frame(late) == b"a"
    await first.aclose()
    await late.aclose()


async def test_reconnects_after_upstream_failure(camera, relay):
    viewer = relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(viewer) == b"a"
    camera.fail()
    await wait_until(lambda: camera.opens == 2)
    camera.push_frame(b"b")
    assert await next_frame(viewer) == b"b"
    await viewer.aclose()


async def test_reconnects_when_upstream_ends_cleanly(camera, relay):
    viewer = relay.frames()
    camera.push_frame(b"a")
    assert await next_frame(viewer) == b"a"
    camera._chunks.put_nowait(None)
    await wait_until(lambda: camera.opens == 2)
    await viewer.aclose()
