"""Repository for user authentication operations."""

import asyncpg

from app.repositories.base import BaseRepository


class AuthRepository:
    """Data access for users table. No user_id binding — used before auth."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def find_by_username(self, username: str) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id, username, password_hash FROM users WHERE username = $1",
            username,
        )

    async def username_exists(self, username: str) -> bool:
        val = await self.conn.fetchval(
            "SELECT id FROM users WHERE username = $1", username,
        )
        return val is not None

    async def create_user(self, username: str, password_hash: str) -> int:
        return await self.conn.fetchval(
            "INSERT INTO users (username, password_hash) VALUES ($1, $2) RETURNING id",
            username, password_hash,
        )

    async def get_user_info(self, user_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id, username, created_at FROM users WHERE id = $1",
            user_id,
        )

    async def get_privacy_mode(self, user_id: int) -> bool:
        row = await self.conn.fetchrow(
            "SELECT privacy_mode FROM users WHERE id = $1", user_id,
        )
        return row["privacy_mode"] if row else False

    async def set_privacy_mode(self, user_id: int, enabled: bool) -> None:
        await self.conn.execute(
            "UPDATE users SET privacy_mode = $1 WHERE id = $2",
            enabled, user_id,
        )

    async def delete_user(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM users WHERE id = $1", user_id)
