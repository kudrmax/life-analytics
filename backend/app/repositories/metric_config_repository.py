"""Repository for metric config tables — scale, enum, computed, integration, checkpoints, intervals, conditions."""

import json
from typing import Any

import asyncpg

from app.repositories.base import BaseRepository


class MetricConfigRepository(BaseRepository):
    """Data access for metric type-specific config, checkpoints, intervals, conditions, enum options."""

    # ── Inline category ────────────────────────────────────────────────

    async def create_inline_category(self, name: str, parent_id: int | None) -> int:
        return await self.conn.fetchval(
            """INSERT INTO categories (user_id, name, parent_id, sort_order)
               VALUES ($1, $2, $3, COALESCE((SELECT MAX(sort_order) + 1 FROM categories WHERE user_id = $1), 0))
               RETURNING id""",
            self.user_id, name, parent_id,
        )

    # ── Integration config inserts ─────────────────────────────────────

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

    # ── Scale config ───────────────────────────────────────────────────

    async def insert_scale_config(
        self, metric_id: int, s_min: int, s_max: int, s_step: int,
        labels_json: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels) VALUES ($1, $2, $3, $4, $5::jsonb)",
            metric_id, s_min, s_max, s_step, labels_json,
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

    # ── Enum config ────────────────────────────────────────────────────

    async def insert_enum_config(self, metric_id: int, multi_select: bool) -> None:
        await self.conn.execute(
            "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
            metric_id, multi_select,
        )

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

    # ── Enum options ───────────────────────────────────────────────────

    async def insert_enum_option(self, metric_id: int, sort_order: int, label: str) -> int:
        return await self.conn.fetchval(
            "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3) RETURNING id",
            metric_id, sort_order, label,
        )

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

    # ── Computed config ────────────────────────────────────────────────

    async def insert_computed_config(self, metric_id: int, formula: list, result_type: str) -> None:
        await self.conn.execute(
            "INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1, $2::jsonb, $3)",
            metric_id, json.dumps(formula), result_type,
        )

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

    # ── Checkpoint / interval ownership ────────────────────────────────

    async def check_checkpoint_ownership(self, checkpoint_id: int) -> bool:
        return bool(await self.conn.fetchval(
            "SELECT 1 FROM checkpoints WHERE id = $1 AND user_id = $2 AND deleted = FALSE",
            checkpoint_id, self.user_id,
        ))

    async def check_interval_ownership(self, interval_id: int) -> bool:
        return bool(await self.conn.fetchval(
            "SELECT 1 FROM intervals WHERE id = $1 AND user_id = $2",
            interval_id, self.user_id,
        ))

    async def check_interval_active(self, interval_id: int) -> bool:
        """Check that both checkpoints of the interval are not deleted."""
        return bool(await self.conn.fetchval(
            """SELECT 1 FROM intervals i
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE i.id = $1 AND cs.deleted = FALSE AND ce.deleted = FALSE""",
            interval_id,
        ))

    async def check_category_ownership(self, cat_id: int) -> bool:
        return bool(await self.conn.fetchval(
            "SELECT 1 FROM categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        ))

    # ── Metric checkpoints ─────────────────────────────────────────────

    async def insert_metric_checkpoint(
        self, metric_id: int, checkpoint_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order, enabled)
               VALUES ($1, $2, $3, TRUE)
               ON CONFLICT (metric_id, checkpoint_id)
               DO UPDATE SET sort_order = $3, enabled = TRUE""",
            metric_id, checkpoint_id, sort_order,
        )

    async def get_metric_checkpoints(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT mc.*, c.label, c.description
               FROM metric_checkpoints mc
               JOIN checkpoints c ON c.id = mc.checkpoint_id
               WHERE mc.metric_id = $1
               ORDER BY mc.sort_order""",
            metric_id,
        )

    async def disable_metric_checkpoint(self, metric_id: int, checkpoint_id: int) -> None:
        await self.conn.execute(
            "UPDATE metric_checkpoints SET enabled = FALSE WHERE metric_id = $1 AND checkpoint_id = $2",
            metric_id, checkpoint_id,
        )

    async def upsert_metric_checkpoint(
        self, metric_id: int, checkpoint_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order, enabled)
               VALUES ($1, $2, $3, TRUE)
               ON CONFLICT (metric_id, checkpoint_id)
               DO UPDATE SET sort_order = $3, enabled = TRUE""",
            metric_id, checkpoint_id, sort_order,
        )

    async def migrate_null_checkpoint_entries(self, metric_id: int, target_checkpoint_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE entries SET checkpoint_id = $1
            WHERE metric_id = $2 AND checkpoint_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM entries e2
                WHERE e2.metric_id = entries.metric_id
                  AND e2.user_id = entries.user_id
                  AND e2.date = entries.date
                  AND e2.checkpoint_id = $1
              )
            """,
            target_checkpoint_id, metric_id,
        )

    # ── Metric intervals ───────────────────────────────────────────────

    async def insert_metric_interval(
        self, metric_id: int, interval_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_intervals (metric_id, interval_id, sort_order, enabled)
               VALUES ($1, $2, $3, TRUE)
               ON CONFLICT (metric_id, interval_id)
               DO UPDATE SET sort_order = $3, enabled = TRUE""",
            metric_id, interval_id, sort_order,
        )

    async def get_metric_intervals(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT mi.*, i.start_checkpoint_id, i.end_checkpoint_id,
                      cs.description AS start_label, ce.description AS end_label
               FROM metric_intervals mi
               JOIN intervals i ON i.id = mi.interval_id
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE mi.metric_id = $1
               ORDER BY mi.sort_order""",
            metric_id,
        )

    async def disable_metric_interval(self, metric_id: int, interval_id: int) -> None:
        await self.conn.execute(
            "UPDATE metric_intervals SET enabled = FALSE WHERE metric_id = $1 AND interval_id = $2",
            metric_id, interval_id,
        )

    async def upsert_metric_interval(
        self, metric_id: int, interval_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_intervals (metric_id, interval_id, sort_order, enabled)
               VALUES ($1, $2, $3, TRUE)
               ON CONFLICT (metric_id, interval_id)
               DO UPDATE SET sort_order = $3, enabled = TRUE""",
            metric_id, interval_id, sort_order,
        )

    async def migrate_null_interval_entries(self, metric_id: int, target_interval_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE entries SET interval_id = $1
            WHERE metric_id = $2 AND interval_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM entries e2
                WHERE e2.metric_id = entries.metric_id
                  AND e2.user_id = entries.user_id
                  AND e2.date = entries.date
                  AND e2.interval_id = $1
              )
            """,
            target_interval_id, metric_id,
        )

    # ── Misc ───────────────────────────────────────────────────────────

    async def clear_metric_category(self, metric_id: int) -> None:
        await self.conn.execute(
            "UPDATE metric_definitions SET category_id = NULL WHERE id = $1", metric_id,
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

    # ── Metric type update ─────────────────────────────────────────────

    async def update_metric_type(self, metric_id: int, new_type: str) -> None:
        await self.conn.execute(
            "UPDATE metric_definitions SET type = $1 WHERE id = $2",
            new_type, metric_id,
        )
