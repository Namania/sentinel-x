from fastapi import APIRouter

from app.application.users.get_me import GetCurrentUser
from app.presentation.dependencies import CurrentUserIdDep, UowDep
from app.presentation.http.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(user_id: CurrentUserIdDep, uow: UowDep) -> UserResponse:
    output = await GetCurrentUser(uow=uow).execute(user_id)
    return UserResponse.from_output(output)
