#!/bin/sh
# Runs at container start (nginx image's /docker-entrypoint.d). Serves HTTPS only when the
# certificate is mounted: a missing file in an `ssl_certificate` directive would stop nginx.
set -e

if [ -f /etc/nginx/certs/server.crt ] && [ -f /etc/nginx/certs/server.key ]; then
  cp /etc/nginx/tls.conf.available /etc/nginx/conf.d/tls.conf
  echo "enable-tls: certificate found, HTTPS enabled on 443"
else
  rm -f /etc/nginx/conf.d/tls.conf
  echo "enable-tls: no certificate in /etc/nginx/certs, HTTP only (make tls-init on the Pi)"
fi
