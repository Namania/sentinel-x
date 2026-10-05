from uuid import UUID

from app.application.auth.dtos import UserOutput
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.errors import UserNotFound


class GetCurrentUser:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> UserOutput:
        async with self._uow as uow:
            user = await uow.users.get_by_id(user_id)
        if user is None:
            raise UserNotFound(str(user_id))
        return UserOutput.from_user(user)
