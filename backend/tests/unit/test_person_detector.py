"""YOLO output decoding and letterboxing, on synthetic outputs (no model needed)."""

import numpy as np

from app.infrastructure.vision.person_detector import (
    CONFIDENCE_THRESHOLD,
    INPUT_SIZE,
    Letterbox,
    letterbox_image,
    parse_output,
)


def _output(*candidates: tuple[float, float, float, float, float, int]) -> np.ndarray:
    """(1, 84, N) YOLOv8 output from (cx, cy, w, h, score, class) candidates."""
    output = np.zeros((1, 84, len(candidates)), dtype=np.float32)
    for i, (cx, cy, w, h, score, cls) in enumerate(candidates):
        output[0, :4, i] = (cx, cy, w, h)
        output[0, 4 + cls, i] = score
    return output


def test_a_wide_frame_is_scaled_and_padded_top_and_bottom():
    square, letterbox = letterbox_image(np.zeros((480, 640, 3), np.uint8), INPUT_SIZE)
    assert square.shape == (INPUT_SIZE, INPUT_SIZE, 3)
    assert letterbox.scale == 0.5
    assert (letterbox.pad_x, letterbox.pad_y) == (0, 40)


def test_a_person_box_is_mapped_back_to_the_frame():
    # 640x480 frame -> scale 0.5, 40px padding top: a 50x100 box centred at (100, 90) in the
    # model input is at x = (75 - 0) / 0.5 = 150, y = (40 - 40) / 0.5 = 0, size 100x200.
    people = parse_output(_output((100, 90, 50, 100, 0.9, 0)), Letterbox(0.5, 0, 40), 640, 480)
    assert len(people) == 1
    assert people[0].box == (150, 0, 100, 200)
    assert people[0].confidence == np.float32(0.9)


def test_other_classes_and_low_scores_are_ignored():
    output = _output(
        (100, 100, 50, 50, 0.9, 2),  # a car
        (200, 100, 50, 50, CONFIDENCE_THRESHOLD - 0.05, 0),  # an unsure person
    )
    assert parse_output(output, Letterbox(1.0, 0, 0), 320, 320) == []


def test_overlapping_boxes_of_one_person_are_merged():
    output = _output((100, 100, 60, 120, 0.9, 0), (102, 101, 60, 120, 0.7, 0))
    people = parse_output(output, Letterbox(1.0, 0, 0), 320, 320)
    assert len(people) == 1
    assert people[0].confidence == np.float32(0.9)


def test_boxes_are_clipped_to_the_frame():
    people = parse_output(_output((10, 10, 60, 60, 0.9, 0)), Letterbox(1.0, 0, 0), 320, 320)
    assert people[0].box == (0, 0, 40, 40)
