from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import EmailAlreadyUsed, InvalidCredentials, InvalidReading, UserNotFound


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EmailAlreadyUsed)
    async def _email_already_used(_: Request, __: EmailAlreadyUsed) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "Email already used"}
        )

    @app.exception_handler(InvalidCredentials)
    async def _invalid_credentials(_: Request, __: InvalidCredentials) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(UserNotFound)
    async def _user_not_found(_: Request, __: UserNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "User not found"}
        )

    @app.exception_handler(InvalidReading)
    async def _invalid_reading(_: Request, exc: InvalidReading) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
        )
