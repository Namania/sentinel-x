from app.infrastructure.security.argon2_hasher import Argon2PasswordHasher


def test_hash_is_not_plaintext_and_verifies():
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("secret123")
    assert digest != "secret123"
    assert digest.startswith("$argon2")
    assert hasher.verify("secret123", digest) is True


def test_verify_rejects_wrong_password():
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("secret123")
    assert hasher.verify("wrong", digest) is False
