from app.domain.detection import BoundingBox, DetectionSnapshot, PersonDetection

BOX = BoundingBox(x=0, y=0, width=10, height=10)


def test_person_without_identity_is_an_intruder():
    person = PersonDetection(box=BOX, confidence=0.9, identity=None)
    assert person.is_intruder is True


def test_person_with_identity_is_not_an_intruder():
    person = PersonDetection(box=BOX, confidence=0.9, identity="kevan")
    assert person.is_intruder is False


def test_snapshot_has_intruder_when_any_person_is_unrecognised():
    known = PersonDetection(box=BOX, confidence=0.9, identity="kevan")
    unknown = PersonDetection(box=BOX, confidence=0.9, identity=None)
    snapshot = DetectionSnapshot.now((known, unknown))
    assert snapshot.has_intruder is True


def test_snapshot_has_no_intruder_when_everyone_is_known():
    known = PersonDetection(box=BOX, confidence=0.9, identity="kevan")
    snapshot = DetectionSnapshot.now((known,))
    assert snapshot.has_intruder is False


def test_empty_snapshot_has_no_intruder():
    snapshot = DetectionSnapshot.now(())
    assert snapshot.has_intruder is False
