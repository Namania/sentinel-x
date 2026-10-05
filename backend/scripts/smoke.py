"""End-to-end smoke test against a running stack.

Usage: python scripts/smoke.py [base_url]   (default http://localhost:8080)
"""

import asyncio
import json
import sys
import uuid

import httpx
import websockets


async def main(base_url: str) -> None:
    api = f"{base_url.rstrip('/')}/api"
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws"
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    password = "smoke-secret-123"

    async with httpx.AsyncClient(timeout=10) as client:
        health = await client.get(f"{api}/health")
        assert health.status_code == 200, health.text
        print("health      OK")

        register = await client.post(
            f"{api}/auth/register", json={"email": email, "password": password}
        )
        assert register.status_code == 201, register.text
        print("register    OK")

        login = await client.post(f"{api}/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]
        print("login       OK")

        me = await client.get(f"{api}/users/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200 and me.json()["email"] == email, me.text
        print("me          OK")

    async with websockets.connect(f"{ws_url}?token={access}") as ws:
        await ws.send(json.dumps({"type": "ping"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert reply == {"type": "pong"}, reply
        print("ws ping     OK")

    print("smoke test passed")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"))
