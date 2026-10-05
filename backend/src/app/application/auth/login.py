from app.application.auth.dtos import LoginInput, TokenPair
from app.application.ports.event_broadcaster import EventBroadcaster
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import TokenService
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import InvalidCredentials
from app.domain.user import normalise_email


class LoginUser:
    def __init__(
        self,
        uow: UnitOfWork,
        hasher: PasswordHasher,
        tokens: TokenService,
        broadcaster: EventBroadcaster,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._tokens = tokens
        self._broadcaster = broadcaster

    async def execute(self, data: LoginInput) -> TokenPair:
        email = normalise_email(data.email)
        async with self._uow as uow:
            user = await uow.users.get_by_email(email)
        if user is None or not self._hasher.verify(data.password, user.password_hash):
            raise InvalidCredentials()
        pair = TokenPair(
            access_token=self._tokens.issue_access(user.id),
            refresh_token=self._tokens.issue_refresh(user.id),
        )
        await self._broadcaster.broadcast({"type": "user.logged_in", "user_id": str(user.id)})
        return pair
