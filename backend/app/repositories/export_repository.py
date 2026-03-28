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

    async def get_slots_for_export(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT msl.metric_id, ms.label, ms.sort_order, msl.category_id
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = ANY($1) AND ms.deleted = FALSE
               ORDER BY msl.metric_id, ms.sort_order""",
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
            """SELECT e.*, ms.sort_order AS slot_sort_order, ms.label AS slot_label
               FROM entries e
               LEFT JOIN measurement_slots ms ON ms.id = e.slot_id
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
