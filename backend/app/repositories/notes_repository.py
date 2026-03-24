"""Repository for notes CRUD operations."""

from datetime import date as date_type

import asyncpg

from app.domain.exceptions import EntityNotFoundError
from app.repositories.base import BaseRepository


class NotesRepository(BaseRepository):
    """Data access for notes table."""

    async def get_metric_type(self, metric_id: int) -> asyncpg.Record:
        """Fetch metric and verify ownership. Returns row with id, type."""
        row = await self.conn.fetchrow(
            "SELECT id, type FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("metric_definitions", metric_id)
        return row

    async def create(self, metric_id: int, d: date_type, text: str) -> asyncpg.Record:
        return await self.conn.fetchrow(
            """INSERT INTO notes (metric_id, user_id, date, text)
               VALUES ($1, $2, $3, $4)
               RETURNING id, metric_id, date, text, created_at""",
            metric_id, self.user_id, d, text,
        )

    async def get_by_id(self, note_id: int) -> asyncpg.Record:
        return await self._fetch_owned("notes", note_id)

    async def update_text(self, note_id: int, text: str) -> asyncpg.Record:
        return await self.conn.fetchrow(
            "UPDATE notes SET text = $1 WHERE id = $2 RETURNING id, metric_id, date, text, created_at",
            text, note_id,
        )

    async def delete(self, note_id: int) -> None:
        await self.conn.execute("DELETE FROM notes WHERE id = $1", note_id)

    async def list_by_metric_and_period(
        self, metric_id: int, start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT id, metric_id, date, text, created_at
               FROM notes
               WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
               ORDER BY date DESC, created_at DESC""",
            metric_id, self.user_id, start, end,
        )
