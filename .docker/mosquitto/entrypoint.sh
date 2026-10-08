#!/bin/sh
# Starts the broker (compose `entrypoint`). Without an account file nobody can connect (create
# accounts with `make mqtt-user`); without a certificate the TLS listener stays off, so the stack
# still starts on a dev machine.
set -e

AUTH=/mosquitto/auth/passwd
mkdir -p /mosquitto/auth /mosquitto/conf.d
if [ ! -f "$AUTH" ]; then
  : > "$AUTH"
  echo "mosquitto: no account yet ($AUTH is empty): run make mqtt-user"
fi
chmod 600 "$AUTH"
# Mosquitto wants its ACL file private too; the tracked copy is world-readable in the checkout.
cp /mosquitto/config/acl /mosquitto/acl && chmod 600 /mosquitto/acl

if [ -f /mosquitto/certs/server.crt ] && [ -f /mosquitto/certs/server.key ]; then
  cp /mosquitto/config/tls-listener.conf /mosquitto/conf.d/tls-listener.conf
  echo "mosquitto: certificate found, MQTTS enabled on 8883"
else
  rm -f /mosquitto/conf.d/tls-listener.conf
  echo "mosquitto: no certificate in /mosquitto/certs, plain 1883 only (make tls-init on the Pi)"
fi

exec mosquitto -c /mosquitto/config/mosquitto.conf
