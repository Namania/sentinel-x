from fastapi import FastAPI

from app.presentation.http import health


def create_app() -> FastAPI:
    app = FastAPI(title="sentinel-x")
    app.include_router(health.router)
    return app


app = create_app()
