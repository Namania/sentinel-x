FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# DeepFace pulls in the desktop opencv-python next to opencv-python-headless; it overwrites the
# shared cv2 package and needs X11/GL libraries that the slim image does not ship.
ARG VISION_IDENTIFY=false
RUN if [ "$VISION_IDENTIFY" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends libxcb1 libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

RUN useradd --create-home app && chown app:app /app
USER app

# Set to "true" to also install YOLO (person detection). Heavy (torch, opencv...): off by
# default so the ordinary API image stays small and fast to build.
ARG VISION=false
# Set to "true" (with VISION=true) to also install DeepFace (face whitelist identification).
# Extra heavy on top of VISION: pulls in TensorFlow. Off by default even when VISION=true.
ARG VISION_IDENTIFY=false

COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv,uid=1000,gid=1000 \
    if [ "$VISION_IDENTIFY" = "true" ]; then uv sync --frozen --no-dev --no-install-project --extra vision-identify; \
    elif [ "$VISION" = "true" ]; then uv sync --frozen --no-dev --no-install-project --extra vision; \
    else uv sync --frozen --no-dev --no-install-project; fi

COPY --chown=app:app src ./src
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv,uid=1000,gid=1000 \
    if [ "$VISION_IDENTIFY" = "true" ]; then uv sync --frozen --no-dev --extra vision-identify; \
    elif [ "$VISION" = "true" ]; then uv sync --frozen --no-dev --extra vision; \
    else uv sync --frozen --no-dev; fi

EXPOSE 8000

# Development: sources are bind-mounted over /app/src, uvicorn reloads on change.
FROM base AS dev
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory app.presentation.main:create_app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/src"]

# Production (last stage: the default when no --target is given).
FROM base AS prod
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --no-access-log --factory app.presentation.main:create_app --host 0.0.0.0 --port 8000"]
