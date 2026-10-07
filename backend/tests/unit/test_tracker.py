from app.infrastructure.vision.tracker import MAX_MISSES, PersonTracker, iou


def test_iou_of_identical_and_disjoint_boxes():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0.0


def test_a_person_moving_a_little_keeps_their_track():
    tracker = PersonTracker()
    [first] = tracker.update([(100, 100, 50, 100)])
    first.identity = "kevan"
    [second] = tracker.update([(105, 102, 50, 100)])
    assert second is first
    assert second.identity == "kevan"
    assert second.box == (105, 102, 50, 100)


def test_two_people_keep_their_own_tracks():
    tracker = PersonTracker()
    left, right = tracker.update([(0, 0, 50, 100), (300, 0, 50, 100)])
    right_again, left_again = tracker.update([(305, 0, 50, 100), (5, 0, 50, 100)])
    assert left_again is left
    assert right_again is right


def test_someone_new_gets_a_new_track():
    tracker = PersonTracker()
    [first] = tracker.update([(0, 0, 50, 100)])
    [other] = tracker.update([(400, 0, 50, 100)])
    assert other.id != first.id


def test_a_briefly_hidden_person_is_found_again_then_forgotten():
    tracker = PersonTracker()
    [person] = tracker.update([(0, 0, 50, 100)])
    for _ in range(MAX_MISSES):
        tracker.update([])
    [back] = tracker.update([(0, 0, 50, 100)])
    assert back is person

    for _ in range(MAX_MISSES + 1):
        tracker.update([])
    [stranger] = tracker.update([(0, 0, 50, 100)])
    assert stranger is not person
