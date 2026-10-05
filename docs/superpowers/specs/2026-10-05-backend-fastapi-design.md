# Backend FastAPI — design

Date : 2026-10-05
Statut : validé en discussion, en attente de relecture du document

## Objectif

Poser la base d'un backend Python pour sentinel-x, hébergé sur un Raspberry Pi
(Docker rootless), avec :

- une clean architecture dont le cœur ne dépend d'aucun framework ;
- une authentification JWT email + mot de passe ;
- un canal WebSocket authentifié prêt à pousser des événements temps réel.

Le domaine métier n'est pas encore défini : le seul agrégat livré est `User`.
Un front séparé viendra plus tard dans son propre dossier ; le backend vit dans
`backend/`.

## Hors scope (volontairement)

- Révocation / rotation des refresh tokens.
- Vérification d'email, reset de mot de passe.
- Rôles et permissions.
- Scalabilité multi-instances du hub WebSocket (hub en mémoire, un seul process).
- Front-end.

## Stack

| Rôle | Choix |
|---|---|
| Langage | Python 3.12 |
| Gestion de projet | uv, `pyproject.toml` |
| Framework HTTP/WS | FastAPI + uvicorn (extra `standard`, inclut `websockets`) |
| ORM | SQLAlchemy 2 async + asyncpg |
| Migrations | Alembic |
| Config | pydantic-settings, variables d'environnement |
| Hash mot de passe | Argon2 (`pwdlib[argon2]`) |
| JWT | PyJWT |
| Tests | pytest, pytest-asyncio, httpx |
| Lint | ruff |
| Base | PostgreSQL 16 |

## Architecture

Quatre couches, règle de dépendance stricte vers l'intérieur :

```
presentation ──► application ──► domain
infrastructure ─┘
```

- **domain** : entités, erreurs métier, interfaces de dépôts. Python pur.
- **application** : use cases et ports (interfaces techniques). Dépend du domaine uniquement.
- **infrastructure** : adaptateurs concrets des ports et dépôts (SQLAlchemy, Argon2, JWT, hub WS, settings).
- **presentation** : FastAPI (routers HTTP, endpoint WS, dépendances), app factory et composition root.

Le domaine et l'application n'importent jamais FastAPI, SQLAlchemy, PyJWT ni pydantic.

### Arborescence

```
backend/
  pyproject.toml
  Dockerfile
  .env.example
  alembic.ini
  alembic/
    env.py
    versions/
  src/app/
    domain/
      user.py               # entité User (id, email, password_hash, created_at)
      errors.py             # DomainError, EmailAlreadyUsed, InvalidCredentials, UserNotFound
      repositories.py       # interface UserRepository
    application/
      ports/
        password_hasher.py  # hash(), verify()
        token_service.py    # issue_access(), issue_refresh(), decode()
        unit_of_work.py     # UnitOfWork avec .users, commit/rollback, async context manager
        event_broadcaster.py# broadcast(event), send_to_user(user_id, event)
      auth/
        dtos.py             # RegisterInput, LoginInput, TokenPair, UserOutput
        register.py         # RegisterUser
        login.py            # LoginUser
        refresh.py          # RefreshTokens
      users/
        get_me.py           # GetCurrentUser
    infrastructure/
      config.py             # Settings (pydantic-settings)
      db/
        engine.py           # engine + session factory
        models.py           # table users
        repositories.py     # SqlAlchemyUserRepository
        unit_of_work.py     # SqlAlchemyUnitOfWork
      security/
        argon2_hasher.py
        jwt_token_service.py
      realtime/
        hub.py              # ConnectionHub : registre de connexions, implémente EventBroadcaster
    presentation/
      dependencies.py       # composition root : settings, uow, hasher, tokens, hub, current_user
      http/
        auth.py             # /auth/register, /auth/login, /auth/refresh
        users.py            # /users/me
        errors.py           # mapping DomainError -> HTTP
      ws/
        router.py           # /ws
      main.py               # create_app()
  tests/
    unit/                   # use cases avec fakes en mémoire
    integration/            # HTTP et WS contre Postgres de test
    conftest.py
```

## Domaine

`User` : `id: UUID`, `email: str` (normalisé en minuscules), `password_hash: str`,
`created_at: datetime`. Dataclass figée ; la création passe par une factory
`User.create(email, password_hash)`.

`UserRepository` (interface) : `get_by_id`, `get_by_email`, `add`.

## Use cases

| Use case | Entrée | Sortie | Erreurs |
|---|---|---|---|
| `RegisterUser` | email, password | `UserOutput` | `EmailAlreadyUsed` |
| `LoginUser` | email, password | `TokenPair` | `InvalidCredentials` |
| `RefreshTokens` | refresh_token | `TokenPair` | `InvalidCredentials` |
| `GetCurrentUser` | user_id | `UserOutput` | `UserNotFound` |

`LoginUser` appelle `EventBroadcaster.broadcast({"type": "user.logged_in", "user_id": ...})`
après succès, pour prouver que la chaîne use case → WS fonctionne.

Les use cases reçoivent leurs ports par constructeur. Aucun décorateur, aucun
import de framework.

## Authentification

- Mot de passe hashé en Argon2id. Longueur minimale : 8 caractères (validée en présentation).
- Access token : JWT HS256, claims `sub` (user id), `type="access"`, `exp` (15 min par défaut).
- Refresh token : JWT HS256, claims `sub`, `type="refresh"`, `exp` (7 jours par défaut).
- `/auth/refresh` vérifie `type="refresh"` et émet une nouvelle paire. Pas de révocation.
- Secret, durées et algorithme viennent des settings.

### Routes HTTP

| Méthode | Route | Auth | Corps | Réponse |
|---|---|---|---|---|
| POST | `/auth/register` | non | `{email, password}` | 201 `{id, email, created_at}` |
| POST | `/auth/login` | non | `{email, password}` | 200 `{access_token, refresh_token, token_type}` |
| POST | `/auth/refresh` | non | `{refresh_token}` | 200 `TokenPair` |
| GET | `/users/me` | Bearer access | — | 200 `{id, email, created_at}` |
| GET | `/health` | non | — | 200 `{status: "ok"}` |

Mapping erreurs : `EmailAlreadyUsed` → 409, `InvalidCredentials` → 401,
`UserNotFound` → 404, token absent/invalide → 401.

## WebSocket

- Endpoint `GET /ws?token=<access_token>`. Le token est passé en query string
  car les navigateurs ne permettent pas d'en-têtes custom sur une connexion WS.
- Token invalide → fermeture avec code 1008 avant `accept()`.
- Après `accept()`, la connexion est enregistrée dans `ConnectionHub` sous
  l'id utilisateur. Un utilisateur peut avoir plusieurs connexions.
- Messages client → serveur : JSON `{"type": "ping"}` répond `{"type": "pong"}` ;
  tout autre message est renvoyé en echo `{"type": "echo", "data": ...}`.
- Messages serveur → client : les événements poussés via `EventBroadcaster`,
  sérialisés en JSON.
- À la déconnexion (normale ou erreur), la connexion est retirée du hub.

`ConnectionHub` est un singleton par process, créé dans le composition root.

## Configuration

Variables d'environnement (préfixe aucun, fichier `.env` lu par pydantic-settings) :

```
DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@db:5432/sentinel
JWT_SECRET=change-me
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=604800
```

`.env.example` est versionné, `.env` est ignoré.

## Docker et compose

`backend/Dockerfile` : image `python:3.12-slim`, installation via uv, utilisateur
non-root, commande `uvicorn app.presentation.main:app --host 0.0.0.0 --port 8000`.
Multi-arch (fonctionne sur arm64 pour le Pi).

`compose.yml` à la racine :

| Service | Image / build | Rôle |
|---|---|---|
| `db` | `postgres:16-alpine` | volume nommé `pgdata`, healthcheck `pg_isready` |
| `api` | build `./backend` | dépend de `db` healthy, lance les migrations Alembic puis uvicorn, lit `.env` |
| `web` | `nginx:alpine` | port `8080:80`, reverse proxy vers `api:8000`, en-têtes `Upgrade`/`Connection` pour `/ws` |

Config nginx dans `nginx/default.conf`, montée en lecture seule. Elle proxifie
`/api/` et `/ws` vers l'API ; la racine `/` sert la page par défaut de nginx
jusqu'à l'arrivée du front.

## Tests

- **Unitaires** : chaque use case avec un `InMemoryUserRepository`,
  un `FakePasswordHasher`, un `FakeTokenService`, un `RecordingBroadcaster`.
  Aucune base, aucun réseau.
- **Intégration** : `httpx.AsyncClient` sur l'app FastAPI, base Postgres de test
  (`DATABASE_URL` de test, tables créées/détruites par fixture). Couvre register,
  login, refresh, me, et une connexion WS ping/pong + réception de `user.logged_in`.
- **Smoke** : `scripts/smoke.sh` enchaîne register, login, me et un ping WS
  contre le compose démarré.

## Critères de succès

1. `docker compose up -d` sur le Pi démarre les trois services sans erreur.
2. Le smoke test passe contre `http://<pi>:8080/api` et `ws://<pi>:8080/ws`.
3. `pytest` passe en local.
4. `grep -r "fastapi\|sqlalchemy\|jwt" backend/src/app/domain backend/src/app/application` ne renvoie rien.
