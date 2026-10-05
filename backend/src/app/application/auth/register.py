from app.application.auth.dtos import RegisterInput, UserOutput
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import EmailAlreadyUsed
from app.domain.user import User, normalise_email


class RegisterUser:
    def __init__(self, uow: UnitOfWork, hasher: PasswordHasher) -> None:
        self._uow = uow
        self._hasher = hasher

    async def execute(self, data: RegisterInput) -> UserOutput:
        email = normalise_email(data.email)
        async with self._uow as uow:
            if await uow.users.get_by_email(email) is not None:
                raise EmailAlreadyUsed(email)
            user = User.create(email=email, password_hash=self._hasher.hash(data.password))
            await uow.users.add(user)
            await uow.commit()
        return UserOutput.from_user(user)
