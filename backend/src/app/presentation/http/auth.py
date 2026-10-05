from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from app.application.auth.dtos import LoginInput, TokenPair, UserOutput
from app.application.auth.login import LoginUser
from app.application.auth.refresh import RefreshTokens
from app.presentation.dependencies import HasherDep, HubDep, TokenServiceDep, UowDep

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_output(cls, output: UserOutput) -> "UserResponse":
        return cls(id=output.id, email=output.email, created_at=output.created_at)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    @classmethod
    def from_pair(cls, pair: TokenPair) -> "TokenPairResponse":
        return cls(access_token=pair.access_token, refresh_token=pair.refresh_token)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest, uow: UowDep, hasher: HasherDep, tokens: TokenServiceDep, hub: HubDep
) -> TokenPairResponse:
    pair = await LoginUser(uow=uow, hasher=hasher, tokens=tokens, broadcaster=hub).execute(
        LoginInput(email=body.email, password=body.password)
    )
    return TokenPairResponse.from_pair(pair)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(body: RefreshRequest, uow: UowDep, tokens: TokenServiceDep) -> TokenPairResponse:
    pair = await RefreshTokens(uow=uow, tokens=tokens).execute(body.refresh_token)
    return TokenPairResponse.from_pair(pair)
