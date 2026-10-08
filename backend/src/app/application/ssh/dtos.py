from __future__ import annotations

from dataclasses import asdict
from datetime import UTC
from typing import Any

from app.domain.ssh_event import SshEvent


def ssh_event_to_dict(event: SshEvent) -> dict[str, Any]:
    """JSON-safe body, shared by the REST response and the `ssh.event` WebSocket event."""
    data = asdict(event)
    data["id"] = str(event.id)
    data["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return data
