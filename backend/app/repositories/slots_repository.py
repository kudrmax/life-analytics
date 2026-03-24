"""Repository for measurement slots CRUD operations."""

import asyncpg

from app.domain.exceptions import EntityNotFoundError, DuplicateEntityError
from app.repositories.base import BaseRepository


class SlotsRepository(BaseRepository):
    """Data access for measurement_slots and metric_slots tables."""

    async def get_all_with_usage(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT ms.id, ms.label, ms.sort_order, ms.description,
                      COALESCE(cnt.c, 0) AS usage_count,
                      COALESCE(cnt.names, ARRAY[]::text[]) AS usage_metric_names
               FROM measurement_slots ms
               LEFT JOIN (
                   SELECT msl.slot_id, COUNT(*) c,
                          array_agg(DISTINCT md.name ORDER BY md.name) AS names
                   FROM metric_slots msl
                   JOIN metric_definitions md ON md.id = msl.metric_id
                   WHERE msl.enabled = TRUE
                   GROUP BY msl.slot_id
               ) cnt ON cnt.slot_id = ms.id
               WHERE ms.user_id = $1
               ORDER BY ms.sort_order, ms.id""",
            self.user_id,
        )

    async def get_by_id(self, slot_id: int) -> asyncpg.Record:
        return await self._fetch_owned("measurement_slots", slot_id)

    async def get_next_sort_order(self) -> int:
        val = await self.conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) FROM measurement_slots WHERE user_id = $1",
            self.user_id,
        )
        return val + 1

    async def create(self, label: str, sort_order: int, description: str | None = None) -> int:
        try:
            return await self.conn.fetchval(
                """INSERT INTO measurement_slots (user_id, label, sort_order, description)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                self.user_id, label, sort_order, description,
            )
        except Exception:
            raise DuplicateEntityError("measurement_slots", "label", label)

    async def update_label(self, slot_id: int, label: str) -> None:
        try:
            await self.conn.execute(
                "UPDATE measurement_slots SET label = $1 WHERE id = $2 AND user_id = $3",
                label, slot_id, self.user_id,
            )
        except Exception:
            raise DuplicateEntityError("measurement_slots", "label", label)

    async def update_description(self, slot_id: int, description: str | None) -> None:
        await self.conn.execute(
            "UPDATE measurement_slots SET description = $1 WHERE id = $2 AND user_id = $3",
            description, slot_id, self.user_id,
        )

    async def get_updated(self, slot_id: int) -> asyncpg.Record:
        return await self.conn.fetchrow(
            "SELECT id, label, sort_order, description FROM measurement_slots WHERE id = $1",
            slot_id,
        )

    async def get_enabled_usage_count(self, slot_id: int) -> int:
        return await self.conn.fetchval(
            "SELECT COUNT(*) FROM metric_slots WHERE slot_id = $1 AND enabled = TRUE",
            slot_id,
        )

    async def get_enabled_metric_names(self, slot_id: int) -> list[str]:
        rows = await self.conn.fetch(
            """SELECT DISTINCT md.name FROM metric_slots msl
               JOIN metric_definitions md ON md.id = msl.metric_id
               WHERE msl.slot_id = $1 AND msl.enabled = TRUE""",
            slot_id,
        )
        return [r["name"] for r in rows]

    async def delete_disabled_metric_slots(self, slot_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM metric_slots WHERE slot_id = $1 AND enabled = FALSE",
            slot_id,
        )

    async def delete(self, slot_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM measurement_slots WHERE id = $1 AND user_id = $2",
            slot_id, self.user_id,
        )

    async def merge(self, source_id: int, target_id: int) -> dict:
        """Merge source slot into target slot. Returns stats dict."""
        async with self.conn.transaction():
            # 1. Move metric_slots: if (metric_id, target) already exists, delete source row
            conflicting_ms = await self.conn.fetch(
                """SELECT ms_src.id
                   FROM metric_slots ms_src
                   JOIN metric_slots ms_tgt ON ms_tgt.metric_id = ms_src.metric_id
                        AND ms_tgt.slot_id = $2
                   WHERE ms_src.slot_id = $1""",
                source_id, target_id,
            )
            conflicting_ms_ids = [r["id"] for r in conflicting_ms]
            if conflicting_ms_ids:
                await self.conn.execute(
                    "DELETE FROM metric_slots WHERE id = ANY($1::int[])",
                    conflicting_ms_ids,
                )

            metrics_moved = await self.conn.execute(
                "UPDATE metric_slots SET slot_id = $1 WHERE slot_id = $2",
                target_id, source_id,
            )
            metrics_affected = int(metrics_moved.split()[-1])

            # 2. Move entries: delete conflicting (same metric_id, user_id, date), move rest
            entries_deleted_result = await self.conn.execute(
                """DELETE FROM entries e_src
                   USING entries e_tgt
                   WHERE e_src.slot_id = $1
                     AND e_src.user_id = $2
                     AND e_tgt.slot_id = $3
                     AND e_tgt.user_id = $2
                     AND e_tgt.metric_id = e_src.metric_id
                     AND e_tgt.date = e_src.date""",
                source_id, self.user_id, target_id,
            )
            entries_deleted = int(entries_deleted_result.split()[-1])

            entries_moved_result = await self.conn.execute(
                "UPDATE entries SET slot_id = $1 WHERE slot_id = $2 AND user_id = $3",
                target_id, source_id, self.user_id,
            )
            entries_moved = int(entries_moved_result.split()[-1])

            # 3. Delete source slot
            await self.conn.execute(
                "DELETE FROM measurement_slots WHERE id = $1 AND user_id = $2",
                source_id, self.user_id,
            )

        return {
            "metrics_affected": metrics_affected + len(conflicting_ms_ids),
            "entries_moved": entries_moved,
            "entries_deleted": entries_deleted,
        }

    async def reorder(self, items: list[dict]) -> None:
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    """UPDATE measurement_slots
                       SET sort_order = $1
                       WHERE id = $2 AND user_id = $3""",
                    item["sort_order"], item["id"], self.user_id,
                )
