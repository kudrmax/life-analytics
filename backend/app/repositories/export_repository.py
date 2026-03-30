"""Repository for export SQL operations."""

from collections import defaultdict

import asyncpg

from app.repositories.base import BaseRepository


class ExportRepository(BaseRepository):
    """Data access for export operations."""

    async def get_metrics_for_export(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step, sc.labels AS scale_labels,
                      ic.provider, ic.metric_key, ic.value_type,
                      ifc.filter_name, iqc.filter_query,
                      ec.multi_select
               FROM metric_definitions md
               LEFT JOIN scale_config sc ON sc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
               LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
               LEFT JOIN enum_config ec ON ec.metric_id = md.id
               WHERE md.user_id = $1 ORDER BY md.sort_order, md.id""",
            self.user_id,
        )

    async def get_checkpoints_for_export(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT mc.metric_id, cp.label, cp.sort_order, mc.category_id
               FROM metric_checkpoints mc
               JOIN checkpoints cp ON cp.id = mc.checkpoint_id
               WHERE mc.metric_id = ANY($1) AND mc.enabled = TRUE AND cp.deleted = FALSE
               ORDER BY mc.metric_id, cp.sort_order""",
            metric_ids,
        )

    async def get_intervals_for_export(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT mi.metric_id, iv.id AS interval_id,
                      cp_start.label AS start_label, cp_end.label AS end_label,
                      cp_start.sort_order, mi.category_id
               FROM metric_intervals mi
               JOIN intervals iv ON iv.id = mi.interval_id
               JOIN checkpoints cp_start ON cp_start.id = iv.start_checkpoint_id
               JOIN checkpoints cp_end ON cp_end.id = iv.end_checkpoint_id
               WHERE mi.metric_id = ANY($1) AND mi.enabled = TRUE
               ORDER BY mi.metric_id, cp_start.sort_order""",
            metric_ids,
        )

    async def get_computed_configs(self, metric_ids: list[int]) -> dict[int, asyncpg.Record]:
        if not metric_ids:
            return {}
        rows = await self.conn.fetch(
            "SELECT metric_id, formula, result_type FROM computed_config WHERE metric_id = ANY($1)",
            metric_ids,
        )
        return {r["metric_id"]: r for r in rows}

    async def get_enum_options_for_export(self, metric_ids: list[int]) -> dict[int, list[str]]:
        if not metric_ids:
            return defaultdict(list)
        rows = await self.conn.fetch(
            """SELECT metric_id, label FROM enum_options
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            metric_ids,
        )
        result: dict[int, list[str]] = defaultdict(list)
        for r in rows:
            result[r["metric_id"]].append(r["label"])
        return result

    async def get_conditions_for_export(self, metric_ids: list[int]) -> dict[int, asyncpg.Record]:
        if not metric_ids:
            return {}
        rows = await self.conn.fetch(
            """SELECT mc.metric_id, md.slug AS depends_on_slug, mc.condition_type, mc.condition_value
               FROM metric_condition mc
               JOIN metric_definitions md ON md.id = mc.depends_on_metric_id
               WHERE mc.metric_id = ANY($1)""",
            metric_ids,
        )
        return {r["metric_id"]: r for r in rows}

    async def get_all_enum_options_by_id(self, metric_ids: list[int]) -> dict[int, dict[int, str]]:
        if not metric_ids:
            return defaultdict(dict)
        rows = await self.conn.fetch(
            "SELECT id, metric_id, label FROM enum_options WHERE metric_id = ANY($1)",
            metric_ids,
        )
        result: dict[int, dict[int, str]] = defaultdict(dict)
        for r in rows:
            result[r["metric_id"]][r["id"]] = r["label"]
        return result

    async def get_categories(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT id, name, parent_id FROM categories WHERE user_id = $1",
            self.user_id,
        )

    async def get_entries_for_export(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT e.*,
                      e.checkpoint_id, cp.label AS checkpoint_label,
                      e.interval_id, iv_start.label AS interval_start_label,
                      iv_end.label AS interval_end_label
               FROM entries e
               LEFT JOIN checkpoints cp ON cp.id = e.checkpoint_id
               LEFT JOIN intervals iv ON iv.id = e.interval_id
               LEFT JOIN checkpoints iv_start ON iv_start.id = iv.start_checkpoint_id
               LEFT JOIN checkpoints iv_end ON iv_end.id = iv.end_checkpoint_id
               WHERE e.user_id = $1 ORDER BY e.date DESC, e.metric_id""",
            self.user_id,
        )

    async def get_aw_daily(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT date, total_seconds, active_seconds FROM activitywatch_daily_summary WHERE user_id = $1 ORDER BY date",
            self.user_id,
        )

    async def get_aw_apps(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT date, app_name, source, duration_seconds FROM activitywatch_app_usage WHERE user_id = $1 ORDER BY date, duration_seconds DESC",
            self.user_id,
        )

    async def get_notes_for_export(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT n.date, md.slug AS metric_slug, n.text, n.created_at
               FROM notes n
               JOIN metric_definitions md ON md.id = n.metric_id
               WHERE n.user_id = $1
               ORDER BY n.date, n.created_at""",
            self.user_id,
        )
