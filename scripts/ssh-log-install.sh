#!/usr/bin/env sh
# Install the SSH access log agent on the Pi (make ssh-log-install): a systemd *user* service that
# relays sshd's journal lines to the API (scripts/ssh-log-agent.py). Needs backend/.env with
# DEVICE_API_KEY. Idempotent: run it again after pulling a new version of the agent.
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$REPO/backend/.env"
CONF_DIR="$HOME/.config/sentinel-x"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="sentinel-ssh-log"
# The web container only publishes HTTPS (8443): the agent uses it with the project CA. Without a
# certificate yet (make tls-init), fall back to plain HTTP on 8080 if that port is published.
if [ -f "$REPO/certs/ca.crt" ]; then
  API_URL="${SENTINEL_API_URL:-https://127.0.0.1:8443/api}"
  CA_LINE="SSL_CERT_FILE=$REPO/certs/ca.crt"
else
  API_URL="${SENTINEL_API_URL:-http://127.0.0.1:8080/api}"
  CA_LINE=""
  echo "Avertissement : pas de certs/ca.crt ; l'agent utilisera $API_URL (relancer make ssh-log-install après make tls-init)." >&2
fi

[ -f "$ENV_FILE" ] || { echo "Introuvable : $ENV_FILE (copier backend/.env.example)." >&2; exit 1; }
KEY=$(sed -n 's/^DEVICE_API_KEY=//p' "$ENV_FILE" | head -1 | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//')
[ -n "$KEY" ] || { echo "DEVICE_API_KEY est vide dans $ENV_FILE." >&2; exit 1; }
command -v journalctl >/dev/null || { echo "journalctl introuvable : cet agent lit journald." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 introuvable." >&2; exit 1; }

mkdir -p "$CONF_DIR" "$UNIT_DIR"
umask 077
printf 'DEVICE_API_KEY=%s\nSENTINEL_API_URL=%s\n%s\n' "$KEY" "$API_URL" "$CA_LINE" > "$CONF_DIR/ssh-log.env"
umask 022

cat > "$UNIT_DIR/$UNIT.service" <<EOF
[Unit]
Description=SENTINEL-X: journal des connexions SSH vers l'API
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 $REPO/scripts/ssh-log-agent.py
EnvironmentFile=%h/.config/sentinel-x/ssh-log.env
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT.service"
systemctl --user restart "$UNIT.service"
# Without linger the user services (this one, and the rootless Docker) stop at the last logout.
loginctl enable-linger "$(id -un)" 2>/dev/null \
  || echo "Avertissement : loginctl enable-linger a échoué ; lancer : sudo loginctl enable-linger $(id -un)" >&2

echo "Service $UNIT installé pour $(id -un)@$(hostname)."
systemctl --user --no-pager --lines=0 status "$UNIT.service" || true
echo "Logs : make ssh-log-logs    Retirer : systemctl --user disable --now $UNIT"
