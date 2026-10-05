import pytest

from app.infrastructure.camera.mjpeg import MjpegParser, boundary_from_content_type

BOUNDARY = "123456789000000000000987654321"


def part(payload: bytes) -> bytes:
    return (
        f"\r\n--{BOUNDARY}\r\n".encode()
        + f"Content-Type: image/jpeg\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
        + payload
    )


def test_yields_frame_when_fed_a_whole_part():
    parser = MjpegParser(BOUNDARY)
    assert parser.feed(part(b"\xff\xd8jpeg-1\xff\xd9")) == [b"\xff\xd8jpeg-1\xff\xd9"]


def test_yields_several_frames_from_a_single_chunk():
    parser = MjpegParser(BOUNDARY)
    frames = parser.feed(part(b"one") + part(b"two") + part(b"three"))
    assert frames == [b"one", b"two", b"three"]


def test_reassembles_frames_split_at_arbitrary_positions():
    parser = MjpegParser(BOUNDARY)
    data = part(b"first-frame") + part(b"second-frame")
    frames: list[bytes] = []
    for i in range(len(data)):
        frames.extend(parser.feed(data[i : i + 1]))
    assert frames == [b"first-frame", b"second-frame"]


def test_ignores_preamble_before_first_boundary():
    parser = MjpegParser(BOUNDARY)
    assert parser.feed(b"garbage" + part(b"img")) == [b"img"]


def test_frame_body_may_contain_boundary_like_bytes():
    parser = MjpegParser(BOUNDARY)
    payload = b"\xff\xd8" + f"--{BOUNDARY}".encode() + b"\xff\xd9"
    assert parser.feed(part(payload)) == [payload]


def test_part_without_content_length_is_rejected():
    parser = MjpegParser(BOUNDARY)
    data = f"\r\n--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n\r\nabc".encode()
    with pytest.raises(ValueError):
        parser.feed(data)


def test_boundary_is_read_from_content_type_header():
    assert boundary_from_content_type(f"multipart/x-mixed-replace;boundary={BOUNDARY}") == BOUNDARY
    assert boundary_from_content_type('multipart/x-mixed-replace; boundary="abc"') == "abc"


def test_missing_boundary_is_an_error():
    with pytest.raises(ValueError):
        boundary_from_content_type("image/jpeg")
