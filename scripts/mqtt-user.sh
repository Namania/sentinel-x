#!/usr/bin/env sh
# Create or update an MQTT account (make mqtt-user [NAME]). A device's account name is its id,
# i.e. the last segment of its topic (sentinel/esp1 → esp1); the API's account is sentinel-api.
# The hash goes to .docker/mosquitto-auth/passwd (ignored by git); a running broker is reloaded.
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$REPO"
AUTH_DIR=".docker/mosquitto-auth"
mkdir -p "$AUTH_DIR"
touch "$AUTH_DIR/passwd"
chmod 600 "$AUTH_DIR/passwd"

NAME="${1:-}"
if [ -z "$NAME" ]; then
  printf 'Nom du compte (identifiant de l'"'"'appareil, ou sentinel-api) : '
  read -r NAME
fi
case "$NAME" in
  *[!A-Za-z0-9_-]*|"") echo "Nom invalide (lettres, chiffres, - et _ seulement)." >&2; exit 1 ;;
esac

stty -echo 2>/dev/null || true
printf 'Mot de passe : '; read -r PASS; echo
printf 'Confirmer    : '; read -r PASS2; echo
stty echo 2>/dev/null || true
[ "$PASS" = "$PASS2" ] || { echo "Les deux saisies diffèrent." >&2; exit 1; }
[ ${#PASS} -ge 12 ] || { echo "12 caractères minimum." >&2; exit 1; }

docker compose run --rm --no-deps -T --entrypoint mosquitto_passwd mosquitto \
  -b /mosquitto/auth/passwd "$NAME" "$PASS" >/dev/null
echo "Compte « $NAME » enregistré dans $AUTH_DIR/passwd."

if docker compose ps --status running mosquitto 2>/dev/null | grep -q mosquitto; then
  docker kill -s HUP mosquitto >/dev/null && echo "Broker rechargé."
else
  echo "Broker arrêté : les comptes seront lus au prochain démarrage."
fi
case "$NAME" in
  sentinel-api) echo "Mettre le même mot de passe dans backend/.env (MQTT_PASSWORD) puis : docker compose up -d api" ;;
  *) echo "Topic de cet appareil : sentinel/$NAME (le firmware se connecte avec ce nom et ce mot de passe)." ;;
esac
