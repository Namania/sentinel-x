from datetime import UTC
from uuid import UUID

from app.domain.user import User


def test_create_generates_id_and_timestamp():
    user = User.create(email="alice@example.com", password_hash="hash")
    assert isinstance(user.id, UUID)
    assert user.created_at.tzinfo is UTC
    assert user.password_hash == "hash"


def test_create_normalises_email():
    user = User.create(email="  Alice@Example.COM ", password_hash="hash")
    assert user.email == "alice@example.com"


def test_two_users_have_distinct_ids():
    a = User.create(email="a@example.com", password_hash="h")
    b = User.create(email="b@example.com", password_hash="h")
    assert a.id != b.id
