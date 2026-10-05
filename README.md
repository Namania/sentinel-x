# sentinel-x

Backend FastAPI (clean architecture, JWT auth, WebSocket) servi par nginx, pensé pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis changer JWT_SECRET
docker compose up -d
scripts/smoke.sh                        # register → login → me → ws ping
```

- API via nginx : `http://<hôte>:8080/api/...` (par exemple `/api/health`)
- WebSocket : `ws://<hôte>:8080/ws?token=<access_token>`
- Page d'accueil nginx : `http://<hôte>:8080/`

## Développer

```sh
docker compose up -d db
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
```

Les tests d'intégration utilisent la base `sentinel_test` créée par `docker/postgres/init-test-db.sql`.

## Structure

- `backend/src/app/domain` : entités et interfaces de dépôts, Python pur
- `backend/src/app/application` : use cases et ports
- `backend/src/app/infrastructure` : SQLAlchemy, Argon2, JWT, hub WebSocket, settings
- `backend/src/app/presentation` : FastAPI (HTTP, WS, composition root)
- `docs/superpowers/specs` : spécifications de design
