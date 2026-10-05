import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.application.ports.token_service import InvalidToken, TokenService
from app.presentation.dependencies import HubDep, TokenServiceDep

router = APIRouter(tags=["realtime"])


def _authenticate(token: str | None, tokens: TokenService) -> UUID | None:
    if not token:
        return None
    try:
        payload = tokens.decode(token)
    except InvalidToken:
        return None
    if payload.type != "access":
        return None
    return payload.user_id


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    tokens: TokenServiceDep,
    hub: HubDep,
    token: Annotated[str | None, Query()] = None,
) -> None:
    user_id = _authenticate(token, tokens)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    hub.connect(user_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid json"})
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "echo", "data": message})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(user_id, websocket)
