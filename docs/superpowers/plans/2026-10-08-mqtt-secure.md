# MQTT sécurisé Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mosquitto refuses anonymous clients, isolates each device on its own topic, and serves the ESPs over TLS on 8883 with the project CA.

**Architecture:** Broker-side only for the devices (password file + ACL with `%u` patterns + a TLS listener enabled at start when the certificate exists), plus credentials in the API's aiomqtt clients. Same "enable when the cert is there" pattern as the nginx HTTPS.

**Tech Stack:** eclipse-mosquitto 2.0.22, sh, compose, Python settings/aiomqtt.

**Spec:** `docs/superpowers/specs/2026-10-08-mqtt-secure-design.md`

## Global Constraints

- Branch `mqtt-secure` from `develop`; fast-forward into `develop` only. Commits end with the Co-Authored-By line.
- Backend checks: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest tests/unit -q` from `backend/`.
- No secret in git: `.docker/mosquitto-auth/passwd` ignored, `certs/` already ignored.

## Review Focus

1. The stack must still start on a dev Mac without `make mqtt-user` and without certs (empty passwd, 1883 only).
2. A device must not be able to publish on another device's topic or on `sentinel/cmd/buzzer`.
3. `make deploy` after this change must not break the running Pi: the API needs `MQTT_USERNAME`/`MQTT_PASSWORD` and the `sentinel-api` account before the broker reloads, documented order.

---

### Task 1: API credentials

- [ ] Tests: `test_settings.py` (`MQTT_USERNAME` alone refused; pair accepted, defaults None), `test_mqtt_client.py` (username/password forwarded; absent → not in kwargs). Run → RED.
- [ ] `config.py`: fields + `model_validator` ; `client.py`: optional `username`/`password` ; `main.py`: pass `settings.mqtt_username/password` to both factories ; `.env.example`.
- [ ] Run unit suite → GREEN, lint, commit `feat(mqtt): API authenticates to the broker`.

### Task 2: Broker configuration

- [ ] `.docker/mosquitto/{mosquitto.conf,tls-listener.conf,acl,entrypoint.sh}`, `.docker/mosquitto-auth/.gitkeep` (+ `.gitignore`), compose mosquitto service (mounts, ports, entrypoint), `scripts/mqtt-user.sh`, Makefile `mqtt-user`/`mqtt-users`.
- [ ] Manual check with Docker (Colima): start the broker alone without certs → log shows 1883 only, anonymous refused; create `esp1` and `sentinel-api` in a scratch auth dir; `esp1` can publish `sentinel/esp1`, cannot publish `sentinel/esp2` nor `sentinel/cmd/buzzer`; `sentinel-api` receives `sentinel/+`; with `certs/` from `tls-init` → `mosquitto_pub --cafile certs/ca.crt -p 8883` succeeds.
- [ ] Commit `feat(ops): mosquitto with accounts, ACL and MQTTS on 8883`.

### Task 3: README and install procedure

- [ ] README « Capteurs »: paragraph « MQTT sécurisé » with the ordered procedure (deploy, `make mqtt-user sentinel-api`, `.env`, restart api, `make mqtt-user esp1`, ufw 8883, firmware, ufw 1883 removal) and the ESP snippet pointer.
- [ ] Commit `docs(mqtt): secured broker procedure`, fast-forward develop, push.
