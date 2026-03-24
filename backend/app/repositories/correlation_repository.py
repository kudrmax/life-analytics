"""Repository for correlation engine SQL operations."""

from collections import defaultdict
from dataclasses import astuple
from datetime import date as date_type

import asyncpg

from app.repositories.base import BaseRepository


class CorrelationRepository(BaseRepository):
    """Data access for correlation engine (analytics/correlation_engine.py)."""

    async def load_enabled_metrics(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT md.id, md.name, md.type, md.is_checkpoint, ic.value_type AS ic_value_type
               FROM metric_definitions md
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               WHERE md.user_id = $1 AND md.enabled = TRUE ORDER BY md.sort_order""",
            self.user_id,
        )

    async def load_slots_for_metrics(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT ms.id, msl.metric_id, ms.label, ms.sort_order
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = ANY($1) AND msl.enabled = TRUE AND ms.deleted = FALSE
               ORDER BY msl.metric_id, ms.sort_order""",
            metric_ids,
        )

    async def load_computed_configs(self, metric_ids: list[int]) -> dict[int, asyncpg.Record]:
        if not metric_ids:
            return {}
        rows = await self.conn.fetch(
            "SELECT metric_id, formula, result_type FROM computed_config WHERE metric_id = ANY($1)",
            metric_ids,
        )
        return {r["metric_id"]: r for r in rows}

    async def load_enum_options(self, metric_ids: list[int]) -> dict[int, list]:
        if not metric_ids:
            return defaultdict(list)
        rows = await self.conn.fetch(
            """SELECT id, metric_id, label FROM enum_options
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            metric_ids,
        )
        result: dict[int, list] = defaultdict(list)
        for r in rows:
            result[r["metric_id"]].append(r)
        return result

    async def load_enum_configs(self, metric_ids: list[int]) -> dict[int, bool]:
        if not metric_ids:
            return {}
        rows = await self.conn.fetch(
            "SELECT metric_id, multi_select FROM enum_config WHERE metric_id = ANY($1)",
            metric_ids,
        )
        return {r["metric_id"]: r["multi_select"] for r in rows}

    async def insert_pairs(self, pairs: list) -> None:
        """Insert CorrelationPairResult list into correlation_pairs."""
        if pairs:
            await self.conn.executemany(
                """INSERT INTO correlation_pairs
                   (report_id, metric_a_id, metric_b_id, slot_a_id, slot_b_id,
                    source_key_a, source_key_b, type_a, type_b, correlation, data_points, lag_days, p_value, quality_issue)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                [astuple(p) for p in pairs],
            )

    async def finalize_report(self, report_id: int) -> None:
        await self.conn.execute(
            "UPDATE correlation_reports SET status = 'done', finished_at = now() WHERE id = $1",
            report_id,
        )
        await self.conn.execute(
            "DELETE FROM correlation_reports WHERE user_id = $1 AND id != $2",
            self.user_id, report_id,
        )

    async def mark_report_error(self, report_id: int) -> None:
        await self.conn.execute(
            "UPDATE correlation_reports SET status = 'error', finished_at = now() WHERE id = $1",
            report_id,
        )
