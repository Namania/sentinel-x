import json
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.presentation.dependencies import HubDep, TokenServiceDep, decode_access_token

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    tokens: TokenServiceDep,
    hub: HubDep,
    token: Annotated[str | None, Query()] = None,
) -> None:
    user_id = decode_access_token(token, tokens)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    hub.connect(user_id, websocket)
    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            raw = frame.get("text")
            if raw is None:
                await websocket.send_json({"type": "error", "detail": "expected text frame"})
                continue
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
