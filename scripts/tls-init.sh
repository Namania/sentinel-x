#!/usr/bin/env sh
# Create the TLS material for the dashboard (make tls-init): a private certificate authority
# (certs/ca.crt, to install once on every browser of the team) and the Pi's certificate signed by
# it (certs/server.crt + server.key, mounted into the web container). Re-run it to renew the
# server certificate: the CA is kept when it already exists.
#   TLS_IP        the Pi's address on the LAN (default: 192.168.0.70); 127.0.0.1 is always added
#                 so local clients (the SSH log agent) can use HTTPS too
#   TLS_HOSTNAMES extra names, space-separated (default: "sentinel-x sentinel-x.local")
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIR="$REPO/certs"
IP="${TLS_IP:-192.168.0.70}"
HOSTNAMES="${TLS_HOSTNAMES:-sentinel-x sentinel-x.local}"
CA_DAYS=3650
SERVER_DAYS=825   # Apple refuses to trust anything longer

command -v openssl >/dev/null || { echo "openssl introuvable." >&2; exit 1; }
mkdir -p "$DIR"
chmod 700 "$DIR"
cd "$DIR"
umask 077

if [ ! -f ca.key ]; then
  openssl req -x509 -newkey rsa:4096 -sha256 -days "$CA_DAYS" -nodes \
    -keyout ca.key -out ca.crt -subj "/CN=SENTINEL-X CA" 2>/dev/null
  echo "CA créée : $DIR/ca.crt (à installer sur chaque navigateur ; ca.key reste ici)"
else
  echo "CA existante réutilisée : $DIR/ca.crt"
fi

SAN="IP:$IP, IP:127.0.0.1"
for h in $HOSTNAMES; do SAN="$SAN, DNS:$h"; done
printf 'subjectAltName = %s\nextendedKeyUsage = serverAuth\nbasicConstraints = CA:FALSE\n' "$SAN" > server.ext
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=sentinel-x" 2>/dev/null
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days "$SERVER_DAYS" -sha256 -extfile server.ext -out server.crt 2>/dev/null
rm -f server.csr server.ext
chmod 644 ca.crt server.crt

echo "Certificat serveur : $DIR/server.crt (valide $SERVER_DAYS jours) pour $SAN"
echo "Puis : docker compose up -d --force-recreate web   (nginx active le 443 quand il voit le certificat)"
