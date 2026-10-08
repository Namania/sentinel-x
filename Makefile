# sentinel-x — development and deployment shortcuts.
#   make dev     start the stack with hot reload (API: uvicorn --reload, front: Vite HMR) on http://localhost:8080
#   make deploy        on the Raspberry Pi: git pull, pull the images from Docker Hub (IMAGE_NAMESPACE in .env), restart
#   make deploy-build  same, but building the images on the Pi (no Docker Hub)
#   make down    stop the stack (dev or prod)
#   make logs    follow the logs
#   make ssh-add     authorise someone's SSH public key on this account (asks for the key)
#   make ssh-remove  list the authorised keys and remove one
#   make ssh-log-install  on the Pi: relay the SSH connections (accepted / refused) to the dashboard
#   make ssh-log-logs     follow that agent's logs
#   make docker-size   what Docker takes on disk (images, containers, volumes, build cache)
#   make docker-clean  reclaim space: unused images, stopped containers, build cache; volumes are kept
#   make tls-init      on the Pi: create the CA and the certificate so nginx serves HTTPS on 8443
#   make mqtt-user     create or update an MQTT account (a device id, or sentinel-api for the API)
#   make mqtt-users    list the MQTT accounts
COMPOSE      := docker compose
COMPOSE_DEV  := $(COMPOSE) -f compose.yml -f compose.dev.yml

.PHONY: dev deploy deploy-build down logs ssh-add ssh-remove ssh-log-install ssh-log-logs docker-size docker-clean tls-init mqtt-user mqtt-users

dev:
	$(COMPOSE_DEV) up --build --renew-anon-volumes

deploy:
	git pull --ff-only
	@grep -q '^IMAGE_NAMESPACE=' .env 2>/dev/null || { echo 'IMAGE_NAMESPACE manquant dans .env (le compte Docker Hub) ; sinon : make deploy-build' >&2; exit 1; }
	$(COMPOSE) pull
	$(COMPOSE) up -d --remove-orphans

# Build on the Pi instead of pulling (no Docker Hub, or a change not yet published).
deploy-build:
	git pull --ff-only
	$(COMPOSE) up -d --build --remove-orphans

down:
	$(COMPOSE_DEV) down --remove-orphans

logs:
	$(COMPOSE) logs -f

fix-cam-permission:
	sudo chmod 666 /dev/video0 /dev/video1

ssh-add:
	@sh scripts/ssh-add-key.sh

ssh-remove:
	@sh scripts/ssh-remove-key.sh

ssh-log-install:
	@sh scripts/ssh-log-install.sh

ssh-log-logs:
	journalctl --user -u sentinel-ssh-log -f

docker-size:
	docker system df

# Run it with the stack up: images in use by a running container are kept, everything else goes.
# Never add --volumes here: the database lives in a volume.
docker-clean:
	docker system prune -a -f
	docker builder prune -a -f
	docker system df

tls-init:
	@sh scripts/tls-init.sh

mqtt-user:
	@sh scripts/mqtt-user.sh $(NAME)

mqtt-users:
	@cut -d: -f1 .docker/mosquitto-auth/passwd 2>/dev/null || echo "aucun compte (make mqtt-user)"
