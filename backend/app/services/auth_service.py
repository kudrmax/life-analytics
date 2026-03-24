"""Service layer for authentication — business logic between router and repository."""

from app.domain.exceptions import (
    InvalidOperationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from app.repositories.auth_repository import AuthRepository
from app.auth import hash_password, verify_password, create_access_token
from app.schemas import TokenResponse, UserOut


class AuthenticationError(Exception):
    """Invalid credentials (maps to 401 in router)."""

    def __init__(self, detail: str = "Invalid username or password") -> None:
        self.detail = detail
        super().__init__(detail)


class AuthService:
    def __init__(self, repo: AuthRepository) -> None:
        self.repo = repo

    async def register(self, username: str, password: str) -> TokenResponse:
        if len(password) < 8:
            raise InvalidOperationError("Password must be at least 8 characters")
        if not username or len(username) < 3 or len(username) > 30:
            raise InvalidOperationError("Username must be 3-30 characters")
        if await self.repo.username_exists(username):
            raise DuplicateEntityError("User", "username", username)

        password_hash = hash_password(password)
        user_id = await self.repo.create_user(username, password_hash)
        access_token = create_access_token(user_id, username)
        return TokenResponse(access_token=access_token, username=username)

    async def login(self, username: str, password: str) -> TokenResponse:
        user = await self.repo.find_by_username(username)
        if not user or not verify_password(password, user["password_hash"]):
            raise AuthenticationError()
        access_token = create_access_token(user["id"], user["username"])
        return TokenResponse(access_token=access_token, username=user["username"])

    async def get_user_info(self, user_id: int) -> UserOut:
        user = await self.repo.get_user_info(user_id)
        if not user:
            raise EntityNotFoundError("User", user_id)
        return UserOut(
            id=user["id"],
            username=user["username"],
            created_at=str(user["created_at"]),
        )

    async def get_privacy_mode(self, user_id: int) -> bool:
        return await self.repo.get_privacy_mode(user_id)

    async def set_privacy_mode(self, user_id: int, enabled: bool) -> bool:
        await self.repo.set_privacy_mode(user_id, enabled)
        return enabled

    async def delete_account(self, user_id: int) -> None:
        await self.repo.delete_user(user_id)
