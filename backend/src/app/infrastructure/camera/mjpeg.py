"""Incremental parser for `multipart/x-mixed-replace` (MJPEG) byte streams."""

from __future__ import annotations

import re

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_HEADER_END = b"\r\n\r\n"


def boundary_from_content_type(content_type: str) -> str:
    match = _BOUNDARY_RE.search(content_type)
    if match is None:
        raise ValueError(f"no multipart boundary in content-type {content_type!r}")
    return match.group(1)


class MjpegParser:
    """Feed it raw bytes in any chunking; it returns the complete JPEG frames found so far.

    Each part must carry a `Content-Length` header (the ESP32 camera firmware always does),
    which lets frames contain boundary-like bytes without being cut.
    """

    def __init__(self, boundary: str) -> None:
        self._delimiter = f"--{boundary}".encode()
        self._buffer = bytearray()
        self._expected_length: int | None = None

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while True:
            if self._expected_length is None:
                if not self._read_part_headers():
                    break
            assert self._expected_length is not None
            if len(self._buffer) < self._expected_length:
                break
            frames.append(bytes(self._buffer[: self._expected_length]))
            del self._buffer[: self._expected_length]
            self._expected_length = None
        return frames

    def _read_part_headers(self) -> bool:
        """Consume up to the end of the next part's headers. Returns False if incomplete."""
        start = self._buffer.find(self._delimiter)
        if start == -1:
            # Keep only a tail long enough to hold a split delimiter.
            keep = len(self._delimiter) - 1
            if len(self._buffer) > keep:
                del self._buffer[:-keep]
            return False
        header_end = self._buffer.find(_HEADER_END, start)
        if header_end == -1:
            return False
        headers = bytes(self._buffer[start + len(self._delimiter) : header_end])
        self._expected_length = _content_length(headers)
        del self._buffer[: header_end + len(_HEADER_END)]
        return True


def _content_length(headers: bytes) -> int:
    for line in headers.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            return int(value.strip())
    raise ValueError("multipart part without Content-Length header")
