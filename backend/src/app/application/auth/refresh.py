from app.application.auth.dtos import TokenPair
from app.application.ports.token_service import InvalidToken, TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import InvalidCredentials


class RefreshTokens:
    def __init__(self, uow: UnitOfWork, tokens: TokenService) -> None:
        self._uow = uow
        self._tokens = tokens

    async def execute(self, refresh_token: str) -> TokenPair:
        try:
            payload = self._tokens.decode(refresh_token)
        except InvalidToken as exc:
            raise InvalidCredentials() from exc
        if payload.type != "refresh":
            raise InvalidCredentials()
        async with self._uow as uow:
            user = await uow.users.get_by_id(payload.user_id)
        if user is None:
            raise InvalidCredentials()
        return TokenPair(
            access_token=self._tokens.issue_access(user.id),
            refresh_token=self._tokens.issue_refresh(user.id),
        )
