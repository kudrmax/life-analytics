"""Repository for insights CRUD operations."""

import asyncpg

from app.domain.exceptions import EntityNotFoundError
from app.repositories.base import BaseRepository


_INSIGHTS_WITH_METRICS_SQL = """
    SELECT i.id, i.text, i.created_at, i.updated_at,
           im.id AS im_id, im.metric_id, im.custom_label,
           im.sort_order AS im_sort_order,
           md.name AS metric_name, md.icon AS metric_icon
    FROM insights i
    LEFT JOIN insight_metrics im ON im.insight_id = i.id
    LEFT JOIN metric_definitions md ON md.id = im.metric_id
"""


class InsightsRepository(BaseRepository):
    """Data access for insights and insight_metrics tables."""

    async def get_all_with_metrics(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            _INSIGHTS_WITH_METRICS_SQL + """
            WHERE i.user_id = $1
            ORDER BY i.updated_at DESC, im.sort_order""",
            self.user_id,
        )

    async def get_by_id(self, insight_id: int) -> asyncpg.Record:
        return await self._fetch_owned("insights", insight_id)

    async def get_one_with_metrics(self, insight_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            _INSIGHTS_WITH_METRICS_SQL + """
            WHERE i.id = $1
            ORDER BY im.sort_order""",
            insight_id,
        )

    async def create(self, text: str) -> asyncpg.Record:
        return await self.conn.fetchrow(
            """INSERT INTO insights (user_id, text)
               VALUES ($1, $2)
               RETURNING id, text, created_at, updated_at""",
            self.user_id, text,
        )

    async def insert_metric(
        self, insight_id: int, metric_id: int | None, custom_label: str | None, sort_order: int,
    ) -> int:
        row = await self.conn.fetchrow(
            """INSERT INTO insight_metrics (insight_id, metric_id, custom_label, sort_order)
               VALUES ($1, $2, $3, $4)
               RETURNING id""",
            insight_id, metric_id, custom_label, sort_order,
        )
        return row["id"]

    async def get_metric_name_icon(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT name, icon FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )

    async def update_text(self, insight_id: int, text: str) -> None:
        await self.conn.execute(
            "UPDATE insights SET text = $1, updated_at = now() WHERE id = $2",
            text, insight_id,
        )

    async def delete_all_metrics(self, insight_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM insight_metrics WHERE insight_id = $1",
            insight_id,
        )

    async def touch_updated_at(self, insight_id: int) -> None:
        await self.conn.execute(
            "UPDATE insights SET updated_at = now() WHERE id = $1",
            insight_id,
        )

    async def delete(self, insight_id: int) -> None:
        await self.conn.execute("DELETE FROM insights WHERE id = $1", insight_id)
