# sentinel-x
[![CI](https://github.com/Namania/sentinel-x/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Namania/sentinel-x/actions/workflows/ci.yml)

Backend FastAPI (clean architecture, JWT auth, WebSocket, relais caméra) et front React + shadcn/ui, servis par nginx, pensés pour un Raspberry Pi avec Docker rootless.

## Démarrer

```sh
cp backend/.env.example backend/.env   # puis renseigner POSTGRES_PASSWORD et JWT_SECRET
make deploy                             # git pull, pull des images Docker Hub, docker compose up -d (voir « Images »)
docker compose exec api create-user     # crée ton utilisateur (email + mot de passe demandés)
scripts/smoke.sh                        # create-user → login → me → ws ping
```

Sur le Pi, la carte SD se remplit vite avec les images de build : `make docker-size` montre ce que
Docker occupe, `make docker-clean` libère les images inutilisées, les conteneurs arrêtés et le cache de
build (stack démarrée, sinon ses images partent aussi et `make deploy` les reconstruit ; les volumes,
donc la base, ne sont jamais touchés).

Le seul fichier de configuration est `backend/.env` (copié de `backend/.env.example`) : il contient les valeurs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` et le secret `JWT_SECRET` (32 caractères minimum). Il n'y a pas d'URL de base à renseigner : l'API construit l'URL de la base à partir des valeurs `POSTGRES_*`. La variable optionnelle `CAMERA_STREAM_URL` pointe vers le flux MJPEG à relayer : la webcam USB du Pi (`http://webcam:8080/stream`, voir « Caméra ») ou une caméra ESP32 (`http://<ip>:81/stream`).

- Front : `https://<hôte>:8443/` (connexion, puis dashboard et vue caméra sur `/camera`, navigation dans la barre latérale ; HTTPS seulement, voir « HTTPS »)
- API via nginx : `https://<hôte>:8443/api/...` (par exemple `/api/health`)
- Swagger : `https://<hôte>:8443/api/docs` (en local sans nginx : `http://localhost:8000/docs`)
- WebSocket : `wss://<hôte>:8443/ws?token=<access_token>`
- Mesures : section « Mesures » du Dashboard (temps réel via le WebSocket)
- Flux caméra : `https://<hôte>:8443/api/camera/stream?token=<access_token>` (MJPEG, utilisable dans une balise `<img>` ; l'en-tête `Authorization: Bearer` fonctionne aussi)
- État caméra : `GET /api/camera/status` → `{"configured": true, "viewers": 1}` (même authentification)

Il n'y a pas d'inscription par l'API : les comptes se créent uniquement avec la commande `create-user`, qui demande l'email puis le mot de passe (masqué, avec confirmation). En local hors Docker : `uv run create-user`.

## Accès SSH au Pi

La connexion se fait par clé uniquement (port non standard, mots de passe refusés). Pour autoriser
quelqu'un sur le compte `sentinel-x` : il génère sa clé sur sa machine (`ssh-keygen -t ed25519`) et
envoie le `.pub` ; sur le Pi, `make ssh-add` demande la clé, la vérifie, refuse les doublons et
l'écrit sans droit de tunnel. `make ssh-remove` liste les clés autorisées et en retire une.

**Journal des connexions.** `make ssh-log-install` (sur le Pi) installe un agent hors Docker
(`scripts/ssh-log-agent.py`, service utilisateur systemd `sentinel-ssh-log`, linger activé) qui
suit le journal de sshd et pousse chaque connexion à l'API (`POST /api/ssh/events`, en-tête
`X-Device-Key`) : acceptée, avec le **commentaire de la clé** (le mail) retrouvé dans
`~/.ssh/authorized_keys` ; refusée, avec l'utilisateur tenté, l'IP et la raison (clé non acceptée,
utilisateur inconnu, mot de passe refusé, trop de tentatives). La page `/ssh` « Accès SSH » les
liste en direct (`GET /api/ssh/events?outcome=all|accepted|refused&limit=…`, événement WebSocket
`ssh.event`). Un refus ouvre une alerte `ssh` par IP (`device_id` = `ip:…`, valeur = nombre de
tentatives), résolue après `SSH_ALERT_QUIET_MINUTES` (10) sans nouvelle tentative ; ajouter `ssh` à
`BUZZER_TRIGGERS` pour qu'elle fasse sonner le buzzer. Au premier démarrage l'agent rejoue les 24
dernières heures, puis reprend au curseur journald : rien n'est perdu pendant un `make deploy`. Il parle à l'API en HTTPS local avec la CA du projet
(relancer `make ssh-log-install` après `make tls-init`). `make ssh-log-logs` suit ses logs ; `systemctl --user disable --now sentinel-ssh-log` le retire.

## Images

Les images de production (`api`, `web`, `webcam`) sont construites pour `linux/arm64` par GitHub
Actions (`.github/workflows/publish.yml`) à chaque push sur `main`, et poussées sur Docker Hub sous
`<compte>/sentinel-x-api`, `-web`, `-webcam`, avec les tags `latest`, `main` et `sha-<commit>`. Le
Pi ne construit plus rien : `make deploy` fait `git pull`, `docker compose pull` puis `up -d`.

Une fois : dans le dépôt GitHub, *Settings → Secrets and variables → Actions*, ajouter les secrets
`DOCKERHUB_USERNAME` et `DOCKERHUB_TOKEN` (token Docker Hub « Read & Write »), et la variable
`DOCKERHUB_NAMESPACE` si les images vivent ailleurs que sous le compte. Sur le Pi, un fichier
`.env` à la racine du dépôt avec `IMAGE_NAMESPACE=<compte>` (et `IMAGE_TAG=latest`, ou un
`sha-…` pour épingler une version) ; `docker login` seulement si les dépôts Docker Hub sont privés.
Sans `IMAGE_NAMESPACE`, `make deploy` refuse et `make deploy-build` construit sur le Pi comme avant.
En développement, `make dev` construit toujours en local (images `local/sentinel-x-*`).

## HTTPS

Le dashboard n'est servi qu'en HTTPS sur **8443** (le port 8080 n'est plus publié) ; nginx n'ouvre le
443 que lorsqu'un certificat existe, donc `make tls-init` est la première chose à faire sur le Pi.
Le certificat est signé par une petite autorité (CA) propre au projet, à installer une fois sur
chaque navigateur de l'équipe : ensuite plus d'avertissement, renouvellements compris.

```sh
make tls-init                                    # sur le Pi : certs/ca.crt, certs/server.crt + server.key
docker compose up -d --force-recreate web        # nginx voit le certificat et ouvre le 443
sudo ufw allow from 192.168.0.0/24 to any port 8443 proto tcp comment "sentinel-x https"
```

`TLS_IP` (défaut `192.168.0.70`) et `TLS_HOSTNAMES` (défaut `sentinel-x sentinel-x.local`) fixent les
noms du certificat ; le relancer renouvelle le certificat serveur (825 jours) en gardant la CA.
`certs/` est ignoré par git : `ca.key` ne quitte jamais le Pi. Sur les postes, installer
`certs/ca.crt` (macOS : trousseau Système, « Toujours faire confiance » ; Windows : « Autorités de
certification racines de confiance » ; Android et iOS : profil de configuration), puis ouvrir
`https://192.168.0.70:8443/`. Le front construit `wss://` et `/api` à partir de la page, rien à
régler. Le certificat couvre aussi `127.0.0.1` : l'agent SSH (`make ssh-log-install`, à relancer
après `make tls-init`) parle à l'API en `https://127.0.0.1:8443/api` avec la CA
(`SSL_CERT_FILE` dans `~/.config/sentinel-x/ssh-log.env`). La règle ufw du 8080 peut être retirée
(`sudo ufw status numbered` puis `sudo ufw delete <n>`).

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
encode alors lui-même), `WEBCAM_RESOLUTION` (`960x720`), `WEBCAM_FPS` (vide par défaut : certaines
C270 répondent « Inappropriate ioctl » à la demande de débit et µStreamer ne capture plus jamais ;
le navigateur saute de toute façon les images en trop), `WEBCAM_CONTROLS`
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

Les ESP32 publient leurs mesures sur le broker MQTT du stack (service `mosquitto`, port 1883 et
8883 en MQTTS, config dans `.docker/mosquitto/`, voir « MQTT sécurisé » plus bas). L'API s'abonne à
`sentinel/+` (réglages `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC`, `MQTT_USERNAME`, `MQTT_PASSWORD` ;
sans `MQTT_HOST`, pas d'abonné) : le dernier segment du
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

**MQTT sécurisé.** Le broker refuse les clients anonymes. Chaque compte est créé sur le Pi avec
`make mqtt-user NAME=<nom>` (hash dans `.docker/mosquitto-auth/passwd`, ignoré par git, broker
rechargé) ; `make mqtt-users` les liste. Le nom d'un appareil est son identifiant, donc le dernier
segment de son topic (`sentinel/esp1` → compte `esp1`) ; l'API utilise `sentinel-api`. ACL
(`.docker/mosquitto/acl`) : un appareil lit `sentinel/cmd/buzzer` et n'écrit que sur
`sentinel/<son nom>` ; l'API lit `sentinel/+` et écrit `sentinel/cmd/#`. Dès que `make tls-init` a
créé le certificat, le broker ouvre aussi **8883 en MQTTS** (même CA que le HTTPS) ; sans certificat
il reste en 1883 seul, ce qui suffit en développement. L'API parle au broker en clair mais dans le
réseau Docker : rien ne circule sur le LAN sans chiffrement une fois les ESP en 8883.

Mise en place sur le Pi, dans l'ordre :

```sh
make deploy                                   # nouveau broker : plus personne ne peut se connecter
make mqtt-user NAME=sentinel-api              # mot de passe à coller dans backend/.env (MQTT_PASSWORD)
docker compose up -d api                      # l'API se reconnecte avec son compte
make mqtt-user NAME=esp1                      # un compte par ESP (nom = dernier segment du topic)
sudo ufw allow from 192.168.0.0/24 to any port 8883 proto tcp comment "sentinel-x mqtts"
```

Côté firmware (équipe ESP) : `WiFiClientSecure` avec `setCACert(certs/ca.crt)`, serveur
`192.168.0.70:8883`, `mqtt.connect(clientId, "esp1", "<mot de passe>")` ; snippet complet et cas du
`BADCERT_CN_MISMATCH` dans `docs/superpowers/specs/2026-10-08-mqtt-secure-design.md`. Tant que les
firmwares ne sont pas migrés, le 1883 reste joignable sur le LAN avec mot de passe (`mqtt.connect`
avec identifiants suffit) ; ensuite, retirer sa règle ufw (`sudo ufw status numbered`, `sudo ufw
delete <n>`) : l'API continue de passer par le réseau Docker. Test à la main depuis le Pi :
`docker compose exec mosquitto mosquitto_sub -u sentinel-api -P '<mdp>' -t 'sentinel/+' -v`.

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
suivent la liste en direct. La métrique `ssh` (connexions SSH refusées, voir « Accès SSH au Pi »)
suit le même cycle ; quand son compteur de tentatives monte, l'API émet `alert.updated`. Elle peut
aussi être clôturée à la main : bouton « Clôturer » sur `/alertes`, soit `POST /api/alerts/{id}/resolve`
(404 inconnue, 409 déjà résolue ou alerte capteur).

**Sirène.** L'API publie l'état du buzzer sur le topic MQTT **retenu** `sentinel/cmd/buzzer`
(QoS 1) : `{"on": true, "reason": "gas", "open": 2, "muted_until": null, "at": "…"}`. `on` est vrai
quand une alerte ouverte correspond à `BUZZER_TRIGGERS` (`gas,temperature:high` par défaut ;
`metric` ou `metric:low|high`) et qu'aucune coupure n'est en cours. `GET /api/alerts/siren`,
`POST /api/alerts/siren/mute` (coupe `BUZZER_MUTE_MINUTES`, 15 par défaut),
`DELETE /api/alerts/siren/mute` ; événement WebSocket `siren.state`. L'ESP32 n'a qu'à s'abonner et
lire `on` : exemple Arduino dans `docs/superpowers/specs/2026-10-07-siren-mqtt-design.md`.
Le payload est publié compact (`{"on":true,…}`). Test à la main :
`docker compose exec mosquitto mosquitto_sub -u esp1 -P '<mdp>' -t sentinel/cmd/buzzer -v`. Sans matériel : `uv run simulate-sensors --spike
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
