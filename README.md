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

Le seul fichier de configuration est `backend/.env` (copié de `backend/.env.example`) : il contient les valeurs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` et le secret `JWT_SECRET` (32 caractères minimum). Il n'y a pas d'URL de base à renseigner : l'API construit l'URL de la base à partir des valeurs `POSTGRES_*`. La variable optionnelle `CAMERA_STREAM_URL` pointe vers le flux MJPEG à relayer : la webcam USB du Pi (`http://webcam:8080/stream`, voir « Caméra ») ou une caméra ESP32 (`http://<ip>:81/stream`).

- Front : `http://<hôte>:8080/` (connexion, puis dashboard et vue caméra sur `/camera`, navigation dans la barre latérale)
- API via nginx : `http://<hôte>:8080/api/...` (par exemple `/api/health`)
- Swagger : `http://<hôte>:8080/api/docs` (en local sans nginx : `http://localhost:8000/docs`)
- WebSocket : `ws://<hôte>:8080/ws?token=<access_token>`
- Mesures : section « Mesures » du Dashboard (temps réel via le WebSocket)
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

## Caméra

La caméra est une webcam USB branchée sur le Pi, servie en MJPEG par le service `webcam`
(µStreamer, `.docker/webcam/Dockerfile`) sur `http://webcam:8080/stream`, que l'API relaie sur
`/api/camera/stream` (une seule connexion vers la source, diffusion à tous les spectateurs). Dans
`backend/.env` : `CAMERA_STREAM_URL=http://webcam:8080/stream`. Une caméra ESP32 reste possible en
mettant son URL à la place.

Réglages par variables d'environnement (shell ou `.env` à la racine) : `WEBCAM_DEVICE`
(`/dev/video0`), `WEBCAM_FORMAT` (`MJPEG` ; `YUYV` si la webcam ne sort pas de MJPEG, µStreamer
encode alors lui-même), `WEBCAM_RESOLUTION` (`960x720`), `WEBCAM_FPS` (`10`), `WEBCAM_CONTROLS`
(réglages V4L2 appliqués au démarrage, par défaut `exposure_auto_priority=0,exposure_dynamic_framerate=0` :
sans ça la Logitech C270 divise son débit d'images par quatre en basse lumière, ce qui se voit comme
des saccades ; `power_line_frequency=1` en plus contre le scintillement à 50 Hz).

Côté navigateur, le flux n'est pas donné à une balise `<img src=…>` : celle-ci décode chaque image
reçue dans l'ordre et prend du retard dès que les images arrivent plus vite qu'elle ne les dessine
(latence qui grandit avec le temps). Le front lit le flux avec `fetch`, découpe les images et
n'affiche que la plus récente ; une image qui arrive pendant le décodage de la précédente remplace
celle en attente. Sans image pendant 5 s, le flux est rouvert ; le relais retente la source après
1 s. Sur le Pi :

```sh
v4l2-ctl --list-devices                      # quel /dev/videoN est la webcam
v4l2-ctl -d /dev/video0 --list-formats-ext   # formats et résolutions (chercher MJPG)
curl -s -N http://localhost:8080/api/camera/stream?token=… | head -c 300   # le flux relayé
```

Docker rootless : le processus du conteneur ne porte pas le groupe `video` de l'hôte, et le
périphérique est en `root:video 660`, donc µStreamer log « Can't access device: Permission denied »
et sert « NO SIGNAL ». Ouvrir le nœud, et le garder ouvert après un redémarrage ou un rebranchement :

```sh
sudo chmod 666 /dev/video0 /dev/video1
echo 'SUBSYSTEM=="video4linux", MODE="0666"' | sudo tee /etc/udev/rules.d/99-webcam.rules
sudo udevadm control --reload && sudo udevadm trigger
```

En dev sur un portable le service ne démarre pas (profil `hardware` dans `compose.dev.yml`).

## Capteurs

Les ESP32 publient leurs mesures sur le broker MQTT du stack (service `mosquitto`, port 1883,
config dans `.docker/mosquitto/mosquitto.conf`). L'API s'abonne à `sentinel/+` (réglages
`MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC` ; sans `MQTT_HOST`, pas d'abonné) : le dernier segment du
topic est l'identifiant de l'appareil, et le message de l'ESP intérieur est

```json
{"temperature": 22.5, "humidite": 48, "gaz_mv": 1234, "etat_gaz": "ok"}
```

(`etat_gaz` ∈ `prechauffage` | `ok` | `alerte` ; pendant le préchauffage le niveau de gaz n'est pas
stocké). Chaque mesure est horodatée par le serveur, stockée puis diffusée sur le WebSocket
(`{"type":"sensor.reading","data":{…}}`), ce qui met le Dashboard à jour en direct. Le gaz est le
niveau brut du MQ-2 en millivolts (`gas_level`), pas des ppm.

Une route HTTP équivalente existe pour les tests : `POST /api/sensors/readings` avec l'en-tête
`X-Device-Key` (`DEVICE_API_KEY`, 16 caractères minimum). Historique :
`GET /api/sensors/readings?device_id=…&from=…&to=…&bucket=1m|5m|15m|1h`, dernière mesure par
appareil : `GET /api/sensors/latest`, appareils : `GET /api/sensors/devices`.

Sans matériel : `cd backend && uv run simulate-sensors` envoie des mesures factices toutes les 2 s
(`--base-url`, `--device`, `--interval`, `--count` ; sur le Pi, derrière nginx : `--base-url http://localhost:8080/api`) ; `--backfill-minutes 1440` remplit 24 h
d'historique (une mesure par minute) puis quitte. Tester le broker à la main :
`docker compose exec mosquitto mosquitto_pub -t sentinel/esp1 -m '{"temperature":22.5,"humidite":48,"gaz_mv":1234,"etat_gaz":"ok"}'`.

## Dashboard

La page d'accueil est pensée pour un écran mural : sidebar repliée, une carte caméra (flux en
direct, clic → `/camera`), une carte santé du serveur (clic → `/serveur`) et la section capteurs.

La santé du serveur (CPU, mémoire, disque, température du SoC, charge, uptime) est lue par l'API
dans `/proc`, `/sys/class/thermal` et `statvfs`, toutes les 5 s (`SERVER_HEALTH_INTERVAL_S`),
gardée 30 min en mémoire (rien en base) et diffusée sur le WebSocket
(`{"type":"server.health","data":{…}}`) ; `GET /api/server/health` renvoie le dernier point et
l'historique. `compose.yml` monte le fichier `/sys/class/thermal/thermal_zone0/temp` (le dossier seul ne
contient que des liens symboliques, inutilisables dans le conteneur) et un fichier de la partition
racine (`/etc/os-release`, `statvfs` suffit) en lecture seule dans le conteneur `api`
(`HOST_THERMAL_PATH`, `HOST_DISK_PATH`) ; `/proc` du conteneur décrit déjà l'hôte. Sous
Docker Desktop (Mac) il n'y a pas de zone thermique : la température s'affiche « – ».
`SERVER_HEALTH_ENABLED=false` désactive l'échantillonnage (c'est le cas dans les tests).

## Alertes

Une mesure hors bornes ouvre une alerte (table `alerts`), diffusée sur le WebSocket
(`alert.opened`) ; elle se ferme seule quand la mesure revient dans les bornes avec une marge
(0,5 °C, 2 % d'humidité, 5 % du max gaz) : `alert.resolved`. Bornes, identiques pour tous les
appareils : `ALERT_TEMPERATURE_MIN_C=10`, `ALERT_TEMPERATURE_MAX_C=30`, `ALERT_HUMIDITY_MIN_PCT=20`,
`ALERT_HUMIDITY_MAX_PCT=70`, `ALERT_GAS_MAX_MV` (vide : seul l'état « alerte » de l'ESP compte).
`GET /api/alerts?status=open|resolved|all&device_id=…&limit=…` (ouvertes d'abord),
`GET /api/alerts/summary` → `{"open": n}`. Le Dashboard, la page `/alertes` et le badge de la nav
suivent la liste en direct. Sans matériel : `uv run simulate-sensors --spike
[--spike-metric temperature|humidity|gas]` envoie 5 mesures normales, 6 hors bornes, 5 normales.

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
