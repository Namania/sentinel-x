import shutil
from concurrent.futures import ThreadPoolExecutor

from app.presentation import cli
from tests.integration.conftest import TEST_SETTINGS


def _run_cli(answers: list[str], secrets: list[str]) -> tuple[int, list[str]]:
    """Run the command in a worker thread (it owns its own event loop) with scripted input."""
    prompts: list[str] = []
    answer_iter, secret_iter = iter(answers), iter(secrets)

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(answer_iter)

    def ask_secret(prompt: str) -> str:
        prompts.append(prompt)
        return next(secret_iter)

    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(
            cli.main, ask=ask, ask_secret=ask_secret, settings=TEST_SETTINGS
        ).result()
    return code, prompts


def test_create_user_then_login(client, capsys):
    code, prompts = _run_cli(["Alice@Example.com"], ["secret123", "secret123"])

    assert code == 0
    assert prompts == ["Email : ", "Mot de passe : ", "Confirmation : "]
    assert "alice@example.com" in capsys.readouterr().out
    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "secret123"}
    )
    assert response.status_code == 200


def test_duplicate_email_fails_with_code_1(client, capsys):
    assert _run_cli(["alice@example.com"], ["secret123", "secret123"])[0] == 0
    code, _ = _run_cli(["alice@example.com"], ["other1234", "other1234"])
    assert code == 1
    assert "existe déjà" in capsys.readouterr().err


def test_invalid_email_is_asked_again(client):
    code, prompts = _run_cli(["not-an-email", "bob@example.com"], ["secret123", "secret123"])
    assert code == 0
    assert prompts.count("Email : ") == 2


def test_short_or_mismatched_password_is_asked_again(client):
    code, prompts = _run_cli(
        ["carol@example.com"], ["short", "secret123", "different", "secret123", "secret123"]
    )
    assert code == 0
    assert prompts.count("Mot de passe : ") == 3


def test_unreachable_database_fails_with_code_2(capsys):
    unreachable = TEST_SETTINGS.model_copy(update={"postgres_port": 1})
    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(
            cli.main,
            ask=lambda _: "dave@example.com",
            ask_secret=lambda _: "secret123",
            settings=unreachable,
        ).result()
    assert code == 2
    assert "injoignable" in capsys.readouterr().err


def test_console_script_is_installed():
    assert shutil.which("create-user") is not None
