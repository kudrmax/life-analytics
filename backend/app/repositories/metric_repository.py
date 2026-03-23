"""Repository for metric definitions and config CRUD."""

import json
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
    """Data access for metric_definitions and related config tables."""

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

    async def create_inline_category(self, name: str, parent_id: int | None) -> int:
        return await self.conn.fetchval(
            """INSERT INTO categories (user_id, name, parent_id, sort_order)
               VALUES ($1, $2, $3, COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE user_id = $1), 0))
               RETURNING id""",
            self.user_id, name, parent_id,
        )

    # ── Config inserts ─────────────────────────────────────────────────

    async def insert_integration_config(
        self, metric_id: int, provider: str, metric_key: str, value_type: str,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO integration_config (metric_id, provider, metric_key, value_type) VALUES ($1, $2, $3, $4)",
            metric_id, provider, metric_key, value_type,
        )

    async def insert_integration_filter_config(self, metric_id: int, filter_name: str) -> None:
        await self.conn.execute(
            "INSERT INTO integration_filter_config (metric_id, filter_name) VALUES ($1, $2)",
            metric_id, filter_name,
        )

    async def insert_integration_query_config(self, metric_id: int, filter_query: str) -> None:
        await self.conn.execute(
            "INSERT INTO integration_query_config (metric_id, filter_query) VALUES ($1, $2)",
            metric_id, filter_query,
        )

    async def insert_integration_category_config(self, metric_id: int, category_id: int) -> None:
        await self.conn.execute(
            "INSERT INTO integration_category_config (metric_id, activitywatch_category_id) VALUES ($1, $2)",
            metric_id, category_id,
        )

    async def insert_integration_app_config(self, metric_id: int, app_name: str) -> None:
        await self.conn.execute(
            "INSERT INTO integration_app_config (metric_id, app_name) VALUES ($1, $2)",
            metric_id, app_name,
        )

    async def insert_scale_config(
        self, metric_id: int, s_min: int, s_max: int, s_step: int,
        labels_json: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels) VALUES ($1, $2, $3, $4, $5::jsonb)",
            metric_id, s_min, s_max, s_step, labels_json,
        )

    async def insert_enum_config(self, metric_id: int, multi_select: bool) -> None:
        await self.conn.execute(
            "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
            metric_id, multi_select,
        )

    async def insert_enum_option(self, metric_id: int, sort_order: int, label: str) -> int:
        return await self.conn.fetchval(
            "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3) RETURNING id",
            metric_id, sort_order, label,
        )

    async def insert_computed_config(self, metric_id: int, formula: list, result_type: str) -> None:
        await self.conn.execute(
            "INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1, $2::jsonb, $3)",
            metric_id, json.dumps(formula), result_type,
        )

    # ── Slot junction ──────────────────────────────────────────────────

    async def check_slot_ownership(self, slot_id: int) -> bool:
        return bool(await self.conn.fetchval(
            "SELECT 1 FROM measurement_slots WHERE id = $1 AND user_id = $2",
            slot_id, self.user_id,
        ))

    async def check_category_ownership(self, cat_id: int) -> bool:
        return bool(await self.conn.fetchval(
            "SELECT 1 FROM categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        ))

    async def insert_metric_slot(
        self, metric_id: int, slot_id: int, sort_order: int, category_id: int | None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4)",
            metric_id, slot_id, sort_order, category_id,
        )

    async def clear_metric_category(self, metric_id: int) -> None:
        await self.conn.execute(
            "UPDATE metric_definitions SET category_id = NULL WHERE id = $1", metric_id,
        )

    async def get_metric_slots(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM metric_slots WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )

    async def update_metric_slot(
        self, metric_id: int, slot_id: int, category_id: int | None, sort_order: int,
    ) -> None:
        await self.conn.execute(
            "UPDATE metric_slots SET enabled = TRUE, category_id = $1, sort_order = $2 WHERE metric_id = $3 AND slot_id = $4",
            category_id, sort_order, metric_id, slot_id,
        )

    async def disable_metric_slot(self, metric_id: int, slot_id: int) -> None:
        await self.conn.execute(
            "UPDATE metric_slots SET enabled = FALSE WHERE metric_id = $1 AND slot_id = $2",
            metric_id, slot_id,
        )

    async def migrate_null_slot_entries(self, metric_id: int, target_slot_id: int) -> None:
        await self.conn.execute(
            "UPDATE entries SET slot_id = $1 WHERE metric_id = $2 AND slot_id IS NULL",
            target_slot_id, metric_id,
        )

    # ── Condition ──────────────────────────────────────────────────────

    async def insert_or_update_condition(
        self, metric_id: int, depends_on: int, cond_type: str, cond_value: Any,
    ) -> None:
        cond_val = json.dumps(cond_value) if cond_value is not None else None
        await self.conn.execute(
            """INSERT INTO metric_condition (metric_id, depends_on_metric_id, condition_type, condition_value)
               VALUES ($1, $2, $3, $4::jsonb)
               ON CONFLICT (metric_id) DO UPDATE
               SET depends_on_metric_id = EXCLUDED.depends_on_metric_id,
                   condition_type = EXCLUDED.condition_type,
                   condition_value = EXCLUDED.condition_value""",
            metric_id, depends_on, cond_type, cond_val,
        )

    async def delete_condition(self, metric_id: int) -> None:
        await self.conn.execute("DELETE FROM metric_condition WHERE metric_id = $1", metric_id)

    async def get_condition_dependency(self, metric_id: int) -> int | None:
        return await self.conn.fetchval(
            "SELECT depends_on_metric_id FROM metric_condition WHERE metric_id = $1",
            metric_id,
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

    async def get_scale_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT scale_min, scale_max, scale_step, labels FROM scale_config WHERE metric_id = $1",
            metric_id,
        )

    async def upsert_scale_config(
        self, metric_id: int, s_min: int, s_max: int, s_step: int,
        labels_json: str | None, exists: bool,
    ) -> None:
        if exists:
            await self.conn.execute(
                "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3, labels = $4::jsonb WHERE metric_id = $5",
                s_min, s_max, s_step, labels_json, metric_id,
            )
        else:
            await self.insert_scale_config(metric_id, s_min, s_max, s_step, labels_json)

    async def get_computed_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT formula, result_type FROM computed_config WHERE metric_id = $1",
            metric_id,
        )

    async def upsert_computed_config(
        self, metric_id: int, formula: list, result_type: str, exists: bool,
    ) -> None:
        if exists:
            await self.conn.execute(
                "UPDATE computed_config SET formula = $1::jsonb, result_type = $2 WHERE metric_id = $3",
                json.dumps(formula), result_type, metric_id,
            )
        else:
            await self.insert_computed_config(metric_id, formula, result_type)

    async def get_enum_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT metric_id, multi_select FROM enum_config WHERE metric_id = $1", metric_id,
        )

    async def upsert_enum_config_multi_select(self, metric_id: int, multi_select: bool, exists: bool) -> None:
        if exists:
            await self.conn.execute(
                "UPDATE enum_config SET multi_select = $1 WHERE metric_id = $2",
                multi_select, metric_id,
            )
        else:
            await self.insert_enum_config(metric_id, multi_select)

    async def get_enum_options(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )

    async def update_enum_option(self, opt_id: int, label: str, sort_order: int) -> None:
        await self.conn.execute(
            "UPDATE enum_options SET label = $1, sort_order = $2, enabled = TRUE WHERE id = $3",
            label, sort_order, opt_id,
        )

    async def disable_enum_option(self, opt_id: int) -> None:
        await self.conn.execute(
            "UPDATE enum_options SET enabled = FALSE WHERE id = $1", opt_id,
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

    async def update_metric_type(self, metric_id: int, new_type: str) -> None:
        await self.conn.execute(
            "UPDATE metric_definitions SET type = $1 WHERE id = $2",
            new_type, metric_id,
        )
