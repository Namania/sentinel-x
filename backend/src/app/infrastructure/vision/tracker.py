"""Follows each person from one analysed frame to the next, so their face is recognised once.

Matching is by box overlap (IoU): between two analyses a person moves a little, so their new box
overlaps their previous one more than anyone else's. A track that is not seen for a few analyses
is dropped (the person left).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import count

Box = tuple[int, int, int, int]  # x, y, width, height

# Minimum overlap for a new box to continue an existing track.
IOU_THRESHOLD = 0.3
# Analyses a track survives without being seen (someone briefly hidden or missed by YOLO).
MAX_MISSES = 2


@dataclass
class Track:
    id: int
    box: Box
    identity: str | None = None
    identity_confidence: float | None = None
    # When the face was last checked (time.monotonic); -inf = never.
    last_check: float = field(default=-math.inf)
    misses: int = 0


class PersonTracker:
    def __init__(self) -> None:
        self._tracks: list[Track] = []
        self._ids = count(1)

    def update(self, boxes: list[Box]) -> list[Track]:
        """The track of each box, in the same order (new people get a new track)."""
        pairs = sorted(
            (
                (iou(box, track.box), box_index, track_index)
                for box_index, box in enumerate(boxes)
                for track_index, track in enumerate(self._tracks)
            ),
            reverse=True,
        )
        assigned: dict[int, Track] = {}
        used_tracks: set[int] = set()
        for overlap, box_index, track_index in pairs:
            if overlap < IOU_THRESHOLD:
                break
            if box_index in assigned or track_index in used_tracks:
                continue
            assigned[box_index] = self._tracks[track_index]
            used_tracks.add(track_index)

        for track_index, track in enumerate(self._tracks):
            if track_index not in used_tracks:
                track.misses += 1

        result = []
        for box_index, box in enumerate(boxes):
            track = assigned.get(box_index)
            if track is None:
                track = Track(id=next(self._ids), box=box)
                self._tracks.append(track)
            track.box = box
            track.misses = 0
            result.append(track)

        self._tracks = [track for track in self._tracks if track.misses <= MAX_MISSES]
        return result


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two boxes: 1 = same box, 0 = no overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter_w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = inter_w * inter_h
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0
