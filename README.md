# sentinel-x

Backend FastAPI (clean architecture, JWT auth, WebSocket) servi par nginx, pensé pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis renseigner POSTGRES_PASSWORD et JWT_SECRET
docker compose up -d
docker compose exec api create-user     # crée ton utilisateur (email + mot de passe demandés)
scripts/smoke.sh                        # create-user → login → me → ws ping
```

Le seul fichier de configuration est `backend/.env` (copié de `backend/.env.example`) : il contient les valeurs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` et le secret `JWT_SECRET` (32 caractères minimum). Il n'y a pas d'URL de base à renseigner : l'API construit l'URL de la base à partir des valeurs `POSTGRES_*`. La variable optionnelle `CAMERA_STREAM_URL` (ex. `http://192.168.1.50:81/stream`) pointe vers le flux MJPEG de la caméra ESP32.

- API via nginx : `http://<hôte>:8080/api/...` (par exemple `/api/health`)
- Swagger : `http://<hôte>:8080/api/docs` (en local sans nginx : `http://localhost:8000/docs`)
- WebSocket : `ws://<hôte>:8080/ws?token=<access_token>`
- Flux caméra : `http://<hôte>:8080/api/camera/stream?token=<access_token>` (MJPEG, utilisable dans une balise `<img>` ; l'en-tête `Authorization: Bearer` fonctionne aussi)
- Page d'accueil nginx : `http://<hôte>:8080/`

Il n'y a pas d'inscription par l'API : les comptes se créent uniquement avec la commande `create-user`, qui demande l'email puis le mot de passe (masqué, avec confirmation). En local hors Docker : `uv run create-user`.

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

## Caméra

L'ESP32-S3-CAM ne sert qu'un seul client vidéo à la fois. Le backend ouvre donc une unique connexion vers la caméra, dès qu'un premier spectateur arrive, et redistribue chaque image à tous les spectateurs connectés sur `/camera/stream`. Un spectateur lent saute des images au lieu de ralentir les autres ; quand le dernier se déconnecte, la connexion caméra est fermée. Si la caméra est injoignable, le backend réessaie toutes les 2 s tant qu'il reste des spectateurs.

## Structure

- `backend/src/app/domain` : entités et interfaces de dépôts, Python pur
- `backend/src/app/application` : use cases et ports
- `backend/src/app/infrastructure` : SQLAlchemy, Argon2, JWT, hub WebSocket, relais caméra, settings
- `backend/src/app/presentation` : FastAPI (HTTP, WS, composition root)
- `docs/superpowers/specs` : spécifications de design
