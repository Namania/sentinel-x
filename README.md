# sentinel-x

Backend FastAPI (clean architecture, JWT auth, WebSocket) servi par nginx, pensé pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis renseigner POSTGRES_PASSWORD et JWT_SECRET
docker compose up -d
scripts/smoke.sh                        # register → login → me → ws ping
```

Le seul fichier de configuration est `backend/.env` (copié de `backend/.env.example`) : il contient les valeurs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` et le secret `JWT_SECRET` (32 caractères minimum). Il n'y a pas d'URL de base à renseigner : l'API construit l'URL de la base à partir des valeurs `POSTGRES_*`.

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
uv run uvicorn --factory app.presentation.main:create_app --reload   # serveur local
```

Les tests d'intégration utilisent la base `sentinel_test` créée par `docker/postgres/init-test-db.sql`. Les identifiants viennent de `backend/.env` ; `TEST_POSTGRES_HOST`, `TEST_POSTGRES_PORT` et `TEST_POSTGRES_DB` permettent optionnellement de surcharger la cible des tests.

## Structure

- `backend/src/app/domain` : entités et interfaces de dépôts, Python pur
- `backend/src/app/application` : use cases et ports
- `backend/src/app/infrastructure` : SQLAlchemy, Argon2, JWT, hub WebSocket, settings
- `backend/src/app/presentation` : FastAPI (HTTP, WS, composition root)
- `docs/superpowers/specs` : spécifications de design
