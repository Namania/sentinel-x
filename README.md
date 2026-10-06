# sentinel-x
[![CI](https://github.com/Namania/sentinel-x/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Namania/sentinel-x/actions/workflows/ci.yml)

Backend FastAPI (clean architecture, JWT auth, WebSocket, relais caméra) et front React + shadcn/ui, servis par nginx, pensés pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis renseigner POSTGRES_PASSWORD et JWT_SECRET
make deploy                             # git pull puis docker compose up -d --build (images de production)
docker compose exec api create-user     # crée ton utilisateur (email + mot de passe demandés)
scripts/smoke.sh                        # create-user → login → me → ws ping
```

Le seul fichier de configuration est `backend/.env` (copié de `backend/.env.example`) : il contient les valeurs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` et le secret `JWT_SECRET` (32 caractères minimum). Il n'y a pas d'URL de base à renseigner : l'API construit l'URL de la base à partir des valeurs `POSTGRES_*`. La variable optionnelle `CAMERA_STREAM_URL` (ex. `http://192.168.1.50:81/stream`) pointe vers le flux MJPEG de la caméra ESP32.

- Front : `http://<hôte>:8080/` (connexion, puis dashboard et vue caméra sur `/camera`, navigation dans la barre latérale)
- API via nginx : `http://<hôte>:8080/api/...` (par exemple `/api/health`)
- Swagger : `http://<hôte>:8080/api/docs` (en local sans nginx : `http://localhost:8000/docs`)
- WebSocket : `ws://<hôte>:8080/ws?token=<access_token>`
- Flux caméra : `http://<hôte>:8080/api/camera/stream?token=<access_token>` (MJPEG, utilisable dans une balise `<img>` ; l'en-tête `Authorization: Bearer` fonctionne aussi)
- État caméra : `GET /api/camera/status` → `{"configured": true, "viewers": 1}` (même authentification)

Il n'y a pas d'inscription par l'API : les comptes se créent uniquement avec la commande `create-user`, qui demande l'email puis le mot de passe (masqué, avec confirmation). En local hors Docker : `uv run create-user`.

## Développer

Avec Docker, tout le stack en rechargement à chaud (uvicorn `--reload` et Vite HMR) :

```sh
make dev            # http://localhost:8080 (front Vite) ; API aussi sur http://localhost:8000
make down           # arrêter
```

`make dev` combine `compose.yml` et `compose.dev.yml` : les images sont construites avec la
cible `dev` des Dockerfiles, `backend/src` et `frontend/` sont montés dans les conteneurs et
chaque modification est rechargée. La détection des changements se fait par sondage (les
événements de fichiers ne traversent pas toujours les montages Docker) ; `VITE_USE_POLLING=false
make dev` revient aux événements natifs côté front.

Sans Docker pour l'API :

```sh
docker compose up -d db
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run uvicorn --factory app.presentation.main:create_app --reload   # serveur local
```

Les tests d'intégration utilisent la base `sentinel_test` créée par `.docker/postgres/init-test-db.sql`. Les identifiants viennent de `backend/.env` ; `TEST_POSTGRES_HOST`, `TEST_POSTGRES_PORT` et `TEST_POSTGRES_DB` permettent optionnellement de surcharger la cible des tests.

## Front

Prérequis : Node 24 et pnpm 12 (`corepack enable`).

```sh
cd frontend
pnpm install
pnpm dev          # http://localhost:5173, proxy /api et /ws vers l'uvicorn local (port 8000)
pnpm test         # Vitest
pnpm lint         # ESLint + Prettier
pnpm typecheck    # tsc
pnpm build        # dist/, copié dans l'image nginx par frontend/Dockerfile
```

Thème clair / sombre / système dans l'en-tête ; la session est restaurée au rechargement grâce au refresh token (`localStorage`), l'access token reste en mémoire.

## Structure

- `backend/src/app/domain` : entités et interfaces de dépôts, Python pur
- `backend/src/app/application` : use cases et ports
- `backend/src/app/infrastructure` : SQLAlchemy, Argon2, JWT, hub WebSocket, relais caméra, settings
- `backend/src/app/presentation` : FastAPI (HTTP, WS, composition root)
- `frontend/src` : `app` (routeur, layouts public et connecté, garde d'auth), `features` (thème, auth, caméra, dashboard), `pages`, `components` (sidebar, en-tête) et `components/ui` (shadcn, généré)
- `docs/superpowers/specs` : spécifications de design
