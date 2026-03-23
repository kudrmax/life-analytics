"""Repository for metric definitions — core CRUD operations."""

from typing import Any

import asyncpg

from app.domain.exceptions import EntityNotFoundError
from app.repositories.base import BaseRepository


# The big LEFT JOIN query for metrics with all config tables
_METRIC_WITH_CONFIG_SQL = """
    SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step, sc.labels AS scale_labels,
           cc.formula, cc.result_type,
           ic.provider, ic.metric_key, ic.value_type,
           ifc.filter_name, iqc.filter_query,
           icatc.activitywatch_category_id, iapc.app_name AS config_app_name,
           ec.multi_select,
           mcond.depends_on_metric_id AS condition_metric_id,
           mcond.condition_type, mcond.condition_value
    FROM metric_definitions md
    LEFT JOIN scale_config sc ON sc.metric_id = md.id
    LEFT JOIN computed_config cc ON cc.metric_id = md.id
    LEFT JOIN integration_config ic ON ic.metric_id = md.id
    LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
    LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
    LEFT JOIN integration_category_config icatc ON icatc.metric_id = md.id
    LEFT JOIN integration_app_config iapc ON iapc.metric_id = md.id
    LEFT JOIN enum_config ec ON ec.metric_id = md.id
    LEFT JOIN metric_condition mcond ON mcond.metric_id = md.id
"""


class MetricRepository(BaseRepository):
    """Data access for metric_definitions — queries, create, update, delete, reorder."""

    # ── Queries ────────────────────────────────────────────────────────

    async def get_all_with_config(self, enabled_only: bool = False) -> list[asyncpg.Record]:
        query = _METRIC_WITH_CONFIG_SQL + " WHERE md.user_id = $1"
        if enabled_only:
            query += " AND md.enabled = TRUE"
        query += " ORDER BY md.sort_order, md.id"
        return await self.conn.fetch(query, self.user_id)

    async def get_one_with_config(self, metric_id: int) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            _METRIC_WITH_CONFIG_SQL + " WHERE md.id = $1 AND md.user_id = $2",
            metric_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("metric_definitions", metric_id)
        return row

    async def get_by_id(self, metric_id: int) -> asyncpg.Record:
        return await self._fetch_owned("metric_definitions", metric_id)

    async def get_by_id_for_update(self, metric_id: int) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2 FOR UPDATE",
            metric_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("metric_definitions", metric_id)
        return row

    async def get_by_id_columns(self, metric_id: int, columns: str) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            f"SELECT {columns} FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("metric_definitions", metric_id)
        return row

    async def get_types_by_ids(self, ids: list[int]) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
            ids, self.user_id,
        )

    # ── Slug ───────────────────────────────────────────────────────────

    async def slug_exists(self, slug: str) -> bool:
        val = await self.conn.fetchval(
            "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
            slug, self.user_id,
        )
        return val is not None

    async def unique_slug(self, base_slug: str) -> str:
        slug = base_slug
        suffix = 1
        while True:
            if not await self.slug_exists(slug):
                return slug
            suffix += 1
            slug = f"{base_slug}_{suffix}"

    # ── Create ─────────────────────────────────────────────────────────

    async def create_metric(
        self, slug: str, name: str, category_id: int | None,
        icon: str | None, metric_type: str, enabled: bool,
        sort_order: int, private: bool, description: str | None,
        hide_in_cards: bool,
    ) -> int:
        return await self.conn.fetchval(
            """INSERT INTO metric_definitions
               (user_id, slug, name, category_id, icon, type, enabled, sort_order, private, description, hide_in_cards)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               RETURNING id""",
            self.user_id, slug, name, category_id, icon, metric_type,
            enabled, sort_order, private, description, hide_in_cards,
        )

    # ── Update ─────────────────────────────────────────────────────────

    async def update_fields(self, metric_id: int, updates: dict[str, Any]) -> None:
        if not updates:
            return
        set_parts = []
        values: list[Any] = []
        for i, (k, v) in enumerate(updates.items(), start=1):
            set_parts.append(f"{k} = ${i}")
            values.append(v)
        values.append(metric_id)
        values.append(self.user_id)
        await self.conn.execute(
            f"UPDATE metric_definitions SET {', '.join(set_parts)} WHERE id = ${len(values) - 1} AND user_id = ${len(values)}",
            *values,
        )

    # ── Delete ─────────────────────────────────────────────────────────

    async def delete_metric(self, metric_id: int) -> None:
        result = await self.conn.execute(
            "DELETE FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )
        if result == "DELETE 0":
            raise EntityNotFoundError("metric_definitions", metric_id)

    # ── Reorder ────────────────────────────────────────────────────────

    async def reorder(self, items: list[dict]) -> None:
        async with self.conn.transaction():
            seen_metrics: set[int] = set()
            for item in items:
                metric_id: int = item["id"]
                slot_id: int | None = item.get("slot_id")
                cat_id: int | None = item.get("category_id")

                if slot_id:
                    await self.conn.execute(
                        "UPDATE metric_slots SET category_id = $1 WHERE slot_id = $2 AND metric_id = $3",
                        cat_id, slot_id, metric_id,
                    )

                if metric_id not in seen_metrics:
                    seen_metrics.add(metric_id)
                    if slot_id:
                        await self.conn.execute(
                            """UPDATE metric_definitions
                               SET sort_order = $1, category_id = NULL
                               WHERE id = $2 AND user_id = $3""",
                            item["sort_order"], metric_id, self.user_id,
                        )
                    else:
                        await self.conn.execute(
                            """UPDATE metric_definitions
                               SET sort_order = $1, category_id = $2
                               WHERE id = $3 AND user_id = $4""",
                            item["sort_order"], cat_id, metric_id, self.user_id,
                        )
                        await self.conn.execute(
                            "UPDATE metric_slots SET category_id = $1 WHERE metric_id = $2 AND enabled = TRUE",
                            cat_id, metric_id,
                        )

    # ── Integration checks ─────────────────────────────────────────────

    async def check_todoist_connected(self) -> bool:
        val = await self.conn.fetchval(
            "SELECT id FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
            self.user_id,
        )
        return val is not None

    async def check_aw_enabled(self) -> bool:
        val = await self.conn.fetchval(
            "SELECT enabled FROM activitywatch_settings WHERE user_id = $1",
            self.user_id,
        )
        return bool(val)

    async def check_aw_category(self, cat_id: int) -> bool:
        row = await self.conn.fetchrow(
            "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        )
        return row is not None

    # ── Categories (for markdown export) ───────────────────────────────

    async def get_all_categories(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT id, name, parent_id, sort_order
               FROM categories WHERE user_id = $1
               ORDER BY sort_order, id""",
            self.user_id,
        )
