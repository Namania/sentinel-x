# sentinel-x — development and deployment shortcuts.
#   make dev     start the stack with hot reload (API: uvicorn --reload, front: Vite HMR) on http://localhost:8080
#   make deploy  on the Raspberry Pi: git pull, rebuild the production images, restart the stack
#   make down    stop the stack (dev or prod)
#   make logs    follow the logs
COMPOSE      := docker compose
COMPOSE_DEV  := $(COMPOSE) -f compose.yml -f compose.dev.yml

.PHONY: dev deploy down logs

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
