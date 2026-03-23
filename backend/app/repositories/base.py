"""Base repository — общий паттерн доступа к данным с изоляцией по user_id."""

from typing import Any

import asyncpg

from app.domain.exceptions import EntityNotFoundError


class BaseRepository:
    """Базовый репозиторий с привязкой к соединению и пользователю."""

    def __init__(self, conn: asyncpg.Connection, user_id: int) -> None:
        self.conn = conn
        self.user_id = user_id

    async def _fetch_owned(
        self,
        table: str,
        entity_id: int,
        columns: str = "*",
    ) -> asyncpg.Record:
        """Получить запись по id с проверкой принадлежности пользователю.

        Raises:
            EntityNotFoundError: если запись не найдена или не принадлежит пользователю.
        """
        row = await self.conn.fetchrow(
            f"SELECT {columns} FROM {table} WHERE id=$1 AND user_id=$2",
            entity_id,
            self.user_id,
        )
        if not row:
            raise EntityNotFoundError(table, entity_id)
        return row

    async def _fetch_all_owned(
        self,
        table: str,
        columns: str = "*",
        order_by: str = "id",
        extra_where: str = "",
        args: list[Any] | None = None,
    ) -> list[asyncpg.Record]:
        """Получить все записи пользователя из таблицы."""
        query = f"SELECT {columns} FROM {table} WHERE user_id=$1 {extra_where} ORDER BY {order_by}"
        all_args: list[Any] = [self.user_id]
        if args:
            all_args.extend(args)
        return await self.conn.fetch(query, *all_args)
