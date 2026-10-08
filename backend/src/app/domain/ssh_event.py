"""One SSH connection to the Pi, accepted or refused, as sshd journalled it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

Outcome = Literal["accepted", "refused"]
Reason = Literal["key_rejected", "unknown_user", "bad_password", "too_many_attempts"]
SshEventFilter = Literal["accepted", "refused", "all"]


@dataclass(frozen=True, slots=True)
class SshEvent:
    id: UUID
    journal_id: str  # journald __CURSOR: unique, lets the agent replay without duplicates
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None
    key_fingerprint: str | None
    key_comment: str | None  # the comment of the key in authorized_keys, usually a mail
    reason: Reason | None

    @classmethod
    def create(
        cls,
        *,
        journal_id: str,
        occurred_at: datetime,
        outcome: Outcome,
        username: str,
        ip: str,
        port: int,
        method: str | None = None,
        key_fingerprint: str | None = None,
        key_comment: str | None = None,
        reason: Reason | None = None,
    ) -> SshEvent:
        return cls(
            id=uuid4(),
            journal_id=journal_id,
            occurred_at=occurred_at,
            outcome=outcome,
            username=username,
            ip=ip,
            port=port,
            method=method,
            key_fingerprint=key_fingerprint,
            key_comment=key_comment,
            reason=reason,
        )
