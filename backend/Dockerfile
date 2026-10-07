# syntax=docker/dockerfile:1.7

# Vision models, gathered at build time so the API never downloads anything when it starts.
# They are ONNX files: the same files run on a PC and on the Raspberry Pi, through OpenCV alone.
FROM scratch AS models
# YOLOv8n, already converted to ONNX at 320px and kept in the repository (12 MB): converting it
# needs PyTorch, far too big to install on the Pi just for that. See scripts/export-yolo-onnx.sh.
COPY models/yolov8n.onnx /models/
# Face detection (YuNet) and recognition (SFace) from the OpenCV model zoo, checked by hash.
ADD --checksum=sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4 \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    /models/face_detection_yunet_2023mar.onnx
ADD --checksum=sha256:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79 \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx \
    /models/face_recognition_sface_2021dec.onnx

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home app && chown app:app /app
USER app

COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app --from=models /models/*.onnx ./models/
COPY --chown=app:app src ./src
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev

EXPOSE 8000

# Development: sources are bind-mounted over /app/src, uvicorn reloads on change.
FROM base AS dev
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory app.presentation.main:create_app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/src"]

# Production (last stage: the default when no --target is given).
FROM base AS prod
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --no-access-log --factory app.presentation.main:create_app --host 0.0.0.0 --port 8000"]
