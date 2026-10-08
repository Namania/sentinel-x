# sentinel-x — development and deployment shortcuts.
#   make dev     start the stack with hot reload (API: uvicorn --reload, front: Vite HMR) on http://localhost:8080
#   make deploy  on the Raspberry Pi: git pull, rebuild the production images, restart the stack
#   make down    stop the stack (dev or prod)
#   make logs    follow the logs
#   make ssh-add     authorise someone's SSH public key on this account (asks for the key)
#   make ssh-remove  list the authorised keys and remove one
#   make ssh-log-install  on the Pi: relay the SSH connections (accepted / refused) to the dashboard
#   make ssh-log-logs     follow that agent's logs
COMPOSE      := docker compose
COMPOSE_DEV  := $(COMPOSE) -f compose.yml -f compose.dev.yml

.PHONY: dev deploy down logs ssh-add ssh-remove ssh-log-install ssh-log-logs

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
