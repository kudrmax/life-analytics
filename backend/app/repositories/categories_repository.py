"""Repository for categories CRUD operations."""

from typing import Any

import asyncpg

from app.domain.exceptions import EntityNotFoundError, DuplicateEntityError, InvalidOperationError
from app.repositories.base import BaseRepository


class CategoriesRepository(BaseRepository):
    """Data access for categories table."""

    async def get_all(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT id, name, parent_id, sort_order
               FROM categories
               WHERE user_id = $1
               ORDER BY sort_order, id""",
            self.user_id,
        )

    async def get_by_id(self, cat_id: int) -> asyncpg.Record:
        return await self._fetch_owned("categories", cat_id)

    async def get_parent(self, parent_id: int) -> asyncpg.Record:
        """Fetch parent category; raises EntityNotFoundError if not found."""
        row = await self.conn.fetchrow(
            "SELECT id, parent_id FROM categories WHERE id = $1 AND user_id = $2",
            parent_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("Parent category", parent_id)
        return row

    async def get_next_sort_order(self) -> int:
        val = await self.conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE user_id = $1",
            self.user_id,
        )
        return val + 1

    async def create(self, name: str, parent_id: int | None, sort_order: int) -> int:
        try:
            return await self.conn.fetchval(
                """INSERT INTO categories (user_id, name, parent_id, sort_order)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                self.user_id, name, parent_id, sort_order,
            )
        except Exception:
            raise DuplicateEntityError("Category", "name", name)

    async def update(self, cat_id: int, updates: list[str], params: list[Any]) -> asyncpg.Record:
        idx = len(params) + 1
        params.extend([cat_id, self.user_id])
        await self.conn.execute(
            f"UPDATE categories SET {', '.join(updates)} WHERE id = ${idx} AND user_id = ${idx + 1}",
            *params,
        )
        return await self.conn.fetchrow(
            "SELECT id, name, parent_id, sort_order FROM categories WHERE id = $1",
            cat_id,
        )

    async def delete(self, cat_id: int) -> None:
        result = await self.conn.execute(
            "DELETE FROM categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        )
        if result == "DELETE 0":
            raise EntityNotFoundError("categories", cat_id)

    async def reorder(self, items: list[dict]) -> None:
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    """UPDATE categories
                       SET sort_order = $1, parent_id = $2
                       WHERE id = $3 AND user_id = $4""",
                    item["sort_order"], item.get("parent_id"),
                    item["id"], self.user_id,
                )
