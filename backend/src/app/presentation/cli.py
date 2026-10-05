"""Command-line entry points. Installed as console scripts via pyproject.toml."""

from __future__ import annotations

import asyncio
import getpass
import sys
from collections.abc import Callable

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.application.auth.dtos import RegisterInput, UserOutput
from app.application.auth.register import RegisterUser
from app.domain.errors import EmailAlreadyUsed
from app.infrastructure.config import Settings
from app.infrastructure.db.engine import create_engine, create_session_factory
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.security.argon2_hasher import Argon2PasswordHasher

MIN_PASSWORD_LENGTH = 8

Prompt = Callable[[str], str]
_email_adapter: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


def _read_secret(prompt: str) -> str:
    """Hidden input on a terminal; plain line read when piped (no getpass warning)."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    print(prompt, end="", flush=True)
    return sys.stdin.readline().rstrip("\n")


def _prompt_email(ask: Prompt) -> str:
    while True:
        raw = ask("Email : ").strip()
        try:
            return _email_adapter.validate_python(raw)
        except ValidationError:
            print("Email invalide, réessaie.", file=sys.stderr)


def _prompt_password(ask: Prompt) -> str:
    while True:
        password = ask("Mot de passe : ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"{MIN_PASSWORD_LENGTH} caractères minimum, réessaie.", file=sys.stderr)
            continue
        if ask("Confirmation : ") != password:
            print("Les mots de passe ne correspondent pas, réessaie.", file=sys.stderr)
            continue
        return password


async def create_user(email: str, password: str, settings: Settings) -> UserOutput:
    engine = create_engine(settings.database_url)
    try:
        uow = SqlAlchemyUnitOfWork(create_session_factory(engine))
        use_case = RegisterUser(uow=uow, hasher=Argon2PasswordHasher())
        return await use_case.execute(RegisterInput(email=email, password=password))
    finally:
        await engine.dispose()


def main(
    *,
    ask: Prompt = input,
    ask_secret: Prompt = _read_secret,
    settings: Settings | None = None,
) -> int:
    email = _prompt_email(ask)
    password = _prompt_password(ask_secret)
    try:
        user = asyncio.run(create_user(email, password, settings or Settings()))
    except EmailAlreadyUsed:
        print(f"Un utilisateur existe déjà avec l'email {email}.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Base de données injoignable : {exc}", file=sys.stderr)
        return 2
    print(f"Utilisateur créé : {user.email} (id {user.id})")
    return 0


def create_user_command() -> None:
    sys.exit(main())
