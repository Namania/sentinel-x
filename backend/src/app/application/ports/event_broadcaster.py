from typing import Any, Protocol
from uuid import UUID

Event = dict[str, Any]


class EventBroadcaster(Protocol):
    async def broadcast(self, event: Event) -> None: ...

    async def send_to_user(self, user_id: UUID, event: Event) -> None: ...
