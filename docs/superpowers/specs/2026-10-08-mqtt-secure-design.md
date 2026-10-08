# MQTT sécurisé : authentification, ACL et MQTTS pour les ESP — design

Date : 2026-10-08
Statut : validé en discussion le 2026-10-08

## Objectif

Le broker Mosquitto du stack n'accepte plus d'anonyme. Chaque appareil a un compte dont le nom est
son identifiant (`esp1`, `esp-interieur`…) et ne peut publier que sur son propre topic ; l'API a
son compte. Les ESP parlent au broker en **MQTTS (8883)** avec le certificat du Pi signé par la CA
du projet (`make tls-init`). L'API, dans le même réseau Docker que le broker, reste en clair sur
1883 : rien ne circule sur le LAN sans chiffrement.

Décisions : pendant la migration des firmwares, le 1883 reste publié sur l'hôte **avec mot de
passe** ; il sera fermé au LAN par ufw quand les ESP seront en 8883.

## Hors scope

- Certificats clients (mTLS) : un mot de passe par appareil suffit ici.
- Rotation automatique des certificats (c'est `make tls-init`, 825 jours).
- Chiffrement API ↔ broker (réseau Docker interne, jamais sur le LAN).

## Broker (`.docker/mosquitto/`)

- `mosquitto.conf` :

```
listener 1883                      # l'API (réseau Docker) et, le temps de la migration, le LAN
allow_anonymous false
password_file /mosquitto/auth/passwd
acl_file /mosquitto/acl            # copie privée (600) de config/acl faite par entrypoint.sh
include_dir /mosquitto/conf.d      # tls-listener.conf copié ici au démarrage si le certificat existe
persistence true
persistence_location /mosquitto/data/
log_dest stdout
# Docker rootless : « root » dans le conteneur est l'utilisateur sentinel-x de l'hôte, sans
# privilège ; rester root permet de lire la clé privée (600) montée depuis certs/.
user root
```

- `tls-listener.conf` : `listener 8883`, `cafile /mosquitto/certs/ca.crt`, `certfile
  /mosquitto/certs/server.crt`, `keyfile /mosquitto/certs/server.key`, `tls_version tlsv1.2`.
- `acl` :

```
# Tout compte : lit l'état du buzzer, n'écrit que sur le topic qui porte son nom. Les lignes
# « pattern » s'appliquent à tous les comptes ; des lignes « topic » avant le premier « user »
# ne vaudraient que pour les anonymes (refusés ici).
pattern read sentinel/cmd/buzzer
pattern write sentinel/%u
user sentinel-api
topic read sentinel/+
topic write sentinel/cmd/#
```

- `entrypoint.sh` (lancé par compose à la place de l'entrypoint de l'image) : crée
  `/mosquitto/auth/passwd` vide s'il manque (personne ne peut se connecter tant que `make
  mqtt-user` n'a pas créé de compte), copie `tls-listener.conf` dans `/mosquitto/conf.d` si
  `/mosquitto/certs/server.crt` existe (sinon broker en 1883 seul, comme aujourd'hui pour le dev),
  puis `exec mosquitto -c /mosquitto/config/mosquitto.conf`.
- compose : `./.docker/mosquitto:/mosquitto/config:ro`, `./.docker/mosquitto-auth:/mosquitto/auth`
  (dossier ignoré par git, un `.gitkeep`), `./certs:/mosquitto/certs:ro`, ports `1883:1883` et
  `8883:8883`, `entrypoint: ["sh", "/mosquitto/config/entrypoint.sh"]`.

## Comptes — `make mqtt-user`

`scripts/mqtt-user.sh` demande le nom (l'identifiant de l'appareil, ou `sentinel-api`) et le mot
de passe (masqué, deux fois), écrit le hash avec `mosquitto_passwd` dans le conteneur
(`docker compose run --rm --no-deps --entrypoint mosquitto_passwd mosquitto -b
/mosquitto/auth/passwd <nom> <mdp>`), puis recharge le broker (`docker kill -s HUP mosquitto`) s'il
tourne. Relancer la commande pour le même nom remplace le mot de passe. `make mqtt-users` liste
les comptes.

## API

- `Settings` : `mqtt_username: str | None = None`, `mqtt_password: str | None = None`
  (`MQTT_USERNAME`, `MQTT_PASSWORD`) ; l'un sans l'autre est refusé.
- `connect_factory(host, port, identifier, username=None, password=None)` les passe à
  `aiomqtt.Client`. Le souscripteur et le publieur de la sirène les utilisent (`main.py`).
- `.env.example` : `MQTT_USERNAME=sentinel-api`, `MQTT_PASSWORD=` avec la marche à suivre.

## ESP (à intégrer par l'équipe)

```c
#include <WiFiClientSecure.h>
static const char CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
...contenu de certs/ca.crt...
-----END CERTIFICATE-----
)EOF";
WiFiClientSecure wifi;                  // remplace WiFiClient
PubSubClient mqtt(wifi);
// setup(): wifi.setCACert(CA); mqtt.setServer("192.168.0.70", 8883);
// connexion : mqtt.connect(clientId, "esp1", "le-mot-de-passe")   // nom = identifiant = topic
```

Si la poignée de main échoue avec `BADCERT_CN_MISMATCH` (vérification du nom contre une IP),
se connecter par `sentinel-x.local` (résolu par mDNS) ou, en dernier recours, `wifi.setInsecure()`
: la liaison reste chiffrée mais le serveur n'est plus authentifié.

## Tests

- `test_settings.py` : `MQTT_USERNAME` seul → `ValidationError` ; les deux → lus.
- `test_mqtt_client.py` : `connect_factory(..., username="u", password="p")` transmet les deux à
  `aiomqtt.Client` ; sans, rien n'est transmis.
- Vérification manuelle du broker (documentée dans le plan) : sans certificat, 1883 seul ;
  anonyme refusé ; `esp1` publie sur `sentinel/esp1` mais pas sur `sentinel/esp2` ni sur
  `sentinel/cmd/buzzer` ; `sentinel-api` lit `sentinel/+` ; avec certificat, `mosquitto_pub
  --cafile certs/ca.crt -p 8883` fonctionne.

## README

Section « Capteurs » : paragraphe « **MQTT sécurisé** » (comptes, ACL, 8883, ufw, migration des
firmwares, fermeture du 1883), snippet ESP renvoyé vers ce document.
