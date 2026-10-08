# sentinel-x — development and deployment shortcuts.
#   make dev     start the stack with hot reload (API: uvicorn --reload, front: Vite HMR) on http://localhost:8080
#   make deploy  on the Raspberry Pi: git pull, rebuild the production images, restart the stack
#   make down    stop the stack (dev or prod)
#   make logs    follow the logs
#   make ssh-add     authorise someone's SSH public key on this account (asks for the key)
#   make ssh-remove  list the authorised keys and remove one
#   make ssh-log-install  on the Pi: relay the SSH connections (accepted / refused) to the dashboard
#   make ssh-log-logs     follow that agent's logs
#   make docker-size   what Docker takes on disk (images, containers, volumes, build cache)
#   make docker-clean  reclaim space: unused images, stopped containers, build cache; volumes are kept
#   make tls-init      on the Pi: create the CA and the certificate so nginx serves HTTPS on 8443
COMPOSE      := docker compose
COMPOSE_DEV  := $(COMPOSE) -f compose.yml -f compose.dev.yml

.PHONY: dev deploy down logs ssh-add ssh-remove ssh-log-install ssh-log-logs docker-size docker-clean tls-init

dev:
	$(COMPOSE_DEV) up --build --renew-anon-volumes

deploy:
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
