import httpx
import pytest

from app.infrastructure.camera.httpx_source import HttpxCameraSource
from tests.unit.fakes import MJPEG_BOUNDARY, mjpeg_part


def mjpeg_handler(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == "http://cam.local:81/stream"
    return httpx.Response(
        200,
        headers={"content-type": f"multipart/x-mixed-replace;boundary={MJPEG_BOUNDARY}"},
        stream=httpx.ByteStream(mjpeg_part(b"img-1") + mjpeg_part(b"img-2")),
    )


async def test_exposes_content_type_and_raw_bytes():
    source = HttpxCameraSource(
        "http://cam.local:81/stream", transport=httpx.MockTransport(mjpeg_handler)
    )
    async with source.open() as stream:
        assert stream.content_type.startswith("multipart/x-mixed-replace")
        data = b"".join([chunk async for chunk in stream.aiter_bytes()])
    assert data == mjpeg_part(b"img-1") + mjpeg_part(b"img-2")


async def test_non_200_upstream_is_an_error():
    source = HttpxCameraSource(
        "http://cam.local:81/stream",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        async with source.open():
            pass
