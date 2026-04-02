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

    async def load_checkpoints_for_metrics(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT c.id, mc.metric_id, c.label, c.sort_order
               FROM metric_checkpoints mc
               JOIN checkpoints c ON c.id = mc.checkpoint_id
               WHERE mc.metric_id = ANY($1) AND mc.enabled = TRUE AND c.deleted = FALSE
               ORDER BY mc.metric_id, c.sort_order""",
            metric_ids,
        )

    async def load_intervals_for_metrics(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT i.id, mi.metric_id, cs.label AS start_label, ce.label AS end_label, mi.sort_order
               FROM metric_intervals mi
               JOIN intervals i ON i.id = mi.interval_id
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE mi.metric_id = ANY($1) AND mi.enabled = TRUE
                 AND cs.deleted = FALSE AND ce.deleted = FALSE
               ORDER BY mi.metric_id, mi.sort_order""",
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
                   (report_id, metric_a_id, metric_b_id, checkpoint_a_id, checkpoint_b_id,
                    interval_a_id, interval_b_id,
                    source_key_a, source_key_b, type_a, type_b, correlation, data_points, lag_days, p_value, quality_issue,
                    adjusted_p_value)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""",
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
