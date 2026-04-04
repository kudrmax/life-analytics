"""Repository for import SQL operations."""

from collections import defaultdict
from datetime import date as date_type

import asyncpg

from app.repositories.base import BaseRepository


class ImportRepository(BaseRepository):
    """Data access for import operations."""

    async def resolve_category_path(self, path_str: str) -> int | None:
        path_str = (path_str or '').strip()
        if not path_str:
            return None
        parts = [p.strip() for p in path_str.split('>')]
        parent_id = None
        cat_id = None
        for part in parts:
            if not part:
                continue
            existing = await self.conn.fetchrow(
                "SELECT id FROM categories WHERE user_id = $1 AND name = $2 AND parent_id IS NOT DISTINCT FROM $3",
                self.user_id, part, parent_id,
            )
            if existing:
                cat_id = existing["id"]
            else:
                cat_id = await self.conn.fetchval(
                    """INSERT INTO categories (user_id, name, parent_id, sort_order)
                       VALUES ($1, $2, $3, COALESCE((SELECT MAX(sort_order)+1 FROM categories WHERE user_id=$1), 0))
                       RETURNING id""",
                    self.user_id, part, parent_id,
                )
            parent_id = cat_id
        return cat_id

    async def find_metric_by_slug(self, slug: str) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2", slug, self.user_id)

    async def update_metric_on_import(
        self, metric_id: int, name: str, category_id: int | None,
        enabled: bool, sort_order: int, icon: str, is_private: bool,
        description: str | None, hide_in_cards: bool, is_checkpoint: bool = False,
        interval_binding: str = "all_day",
    ) -> None:
        await self.conn.execute(
            """UPDATE metric_definitions
               SET name=$1, category_id=$2, enabled=$3, sort_order=$4, icon=$5, private=$6, description=$7,
                   hide_in_cards=$8, is_checkpoint=$9, interval_binding=$10
               WHERE id=$11 AND user_id=$12""",
            name, category_id, enabled, sort_order, icon, is_private, description, hide_in_cards,
            is_checkpoint, interval_binding, metric_id, self.user_id,
        )

    async def create_metric_on_import(
        self, slug: str, name: str, category_id: int | None, icon: str,
        metric_type: str, enabled: bool, sort_order: int, is_private: bool,
        description: str | None, hide_in_cards: bool, is_checkpoint: bool = False,
        interval_binding: str = "all_day",
    ) -> int:
        return await self.conn.fetchval(
            """INSERT INTO metric_definitions
               (user_id, slug, name, category_id, icon, type, enabled, sort_order, private, description,
                hide_in_cards, is_checkpoint, interval_binding)
               VALUES ($1,$2,$3,$4,$5,$6::metric_type,$7,$8,$9,$10,$11,$12,$13) RETURNING id""",
            self.user_id, slug, name, category_id, icon,
            metric_type, enabled, sort_order, is_private, description, hide_in_cards, is_checkpoint,
            interval_binding,
        )

    async def get_scale_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow("SELECT metric_id FROM scale_config WHERE metric_id = $1", metric_id)

    async def upsert_scale_config(
        self, metric_id: int, s_min: int, s_max: int, s_step: int, labels: str | None, exists: bool,
    ) -> None:
        if exists:
            await self.conn.execute(
                "UPDATE scale_config SET scale_min=$1, scale_max=$2, scale_step=$3, labels=$4::jsonb WHERE metric_id=$5",
                s_min, s_max, s_step, labels, metric_id)
        else:
            await self.conn.execute(
                "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels) VALUES ($1,$2,$3,$4,$5::jsonb)",
                metric_id, s_min, s_max, s_step, labels)

    async def upsert_integration_config(
        self, metric_id: int, provider: str, metric_key: str, value_type: str,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO integration_config (metric_id, provider, metric_key, value_type) VALUES ($1,$2,$3,$4)
               ON CONFLICT (metric_id) DO UPDATE
               SET provider=EXCLUDED.provider, metric_key=EXCLUDED.metric_key, value_type=EXCLUDED.value_type""",
            metric_id, provider, metric_key, value_type)

    async def upsert_integration_filter_config(self, metric_id: int, filter_name: str) -> None:
        await self.conn.execute(
            """INSERT INTO integration_filter_config (metric_id, filter_name) VALUES ($1,$2)
               ON CONFLICT (metric_id) DO UPDATE SET filter_name=EXCLUDED.filter_name""",
            metric_id, filter_name)

    async def upsert_integration_query_config(self, metric_id: int, filter_query: str) -> None:
        await self.conn.execute(
            """INSERT INTO integration_query_config (metric_id, filter_query) VALUES ($1,$2)
               ON CONFLICT (metric_id) DO UPDATE SET filter_query=EXCLUDED.filter_query""",
            metric_id, filter_query)

    async def upsert_enum_config(self, metric_id: int, multi_select: bool) -> None:
        await self.conn.execute(
            """INSERT INTO enum_config (metric_id, multi_select) VALUES ($1,$2)
               ON CONFLICT (metric_id) DO UPDATE SET multi_select=EXCLUDED.multi_select""",
            metric_id, multi_select)

    async def get_enum_options_ordered(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM enum_options WHERE metric_id = $1 ORDER BY sort_order", metric_id)

    async def update_enum_option(self, opt_id: int, label: str) -> None:
        await self.conn.execute("UPDATE enum_options SET label=$1, enabled=TRUE WHERE id=$2", label, opt_id)

    async def insert_enum_option(self, metric_id: int, sort_order: int, label: str) -> None:
        await self.conn.execute(
            "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1,$2,$3)", metric_id, sort_order, label)

    async def disable_enum_option(self, opt_id: int) -> None:
        await self.conn.execute("UPDATE enum_options SET enabled=FALSE WHERE id=$1", opt_id)

    async def find_or_create_checkpoint(self, label: str, deleted: bool = False) -> int:
        # Find existing (active or deleted) — reuse for old entries
        existing = await self.conn.fetchrow(
            "SELECT id FROM checkpoints WHERE user_id=$1 AND LOWER(label)=LOWER($2)",
            self.user_id, label.strip())
        if existing:
            return existing["id"]
        max_order = await self.conn.fetchval(
            "SELECT COALESCE(MAX(sort_order),-1) FROM checkpoints WHERE user_id=$1", self.user_id)
        return await self.conn.fetchval(
            "INSERT INTO checkpoints (user_id, label, sort_order, deleted) VALUES ($1,$2,$3,$4) RETURNING id",
            self.user_id, label.strip(), max_order + 1, deleted)

    async def find_or_create_interval(self, start_checkpoint_id: int, end_checkpoint_id: int) -> int:
        existing = await self.conn.fetchrow(
            """SELECT id FROM intervals
               WHERE user_id=$1 AND start_checkpoint_id=$2 AND end_checkpoint_id=$3""",
            self.user_id, start_checkpoint_id, end_checkpoint_id)
        if existing:
            return existing["id"]
        return await self.conn.fetchval(
            """INSERT INTO intervals (user_id, start_checkpoint_id, end_checkpoint_id)
               VALUES ($1,$2,$3) RETURNING id""",
            self.user_id, start_checkpoint_id, end_checkpoint_id)

    async def insert_metric_checkpoint(
        self, metric_id: int, checkpoint_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order) VALUES ($1,$2,$3)",
            metric_id, checkpoint_id, sort_order)

    async def insert_metric_interval(
        self, metric_id: int, interval_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO metric_intervals (metric_id, interval_id, sort_order) VALUES ($1,$2,$3)",
            metric_id, interval_id, sort_order)

    async def get_metric_checkpoints(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM metric_checkpoints WHERE metric_id=$1 ORDER BY sort_order", metric_id)

    async def get_metric_intervals(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM metric_intervals WHERE metric_id=$1 ORDER BY sort_order", metric_id)

    async def update_metric_checkpoint_on_import(
        self, row_id: int, checkpoint_id: int,
    ) -> None:
        await self.conn.execute(
            "UPDATE metric_checkpoints SET checkpoint_id=$1, enabled=TRUE WHERE id=$2",
            checkpoint_id, row_id)

    async def update_metric_interval_on_import(
        self, row_id: int, interval_id: int,
    ) -> None:
        await self.conn.execute(
            "UPDATE metric_intervals SET interval_id=$1, enabled=TRUE WHERE id=$2",
            interval_id, row_id)

    async def upsert_metric_checkpoint(
        self, metric_id: int, checkpoint_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order) VALUES ($1,$2,$3)
               ON CONFLICT (metric_id, checkpoint_id) DO UPDATE
               SET enabled=TRUE, sort_order=EXCLUDED.sort_order""",
            metric_id, checkpoint_id, sort_order)

    async def upsert_metric_interval(
        self, metric_id: int, interval_id: int, sort_order: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_intervals (metric_id, interval_id, sort_order) VALUES ($1,$2,$3)
               ON CONFLICT (metric_id, interval_id) DO UPDATE
               SET enabled=TRUE, sort_order=EXCLUDED.sort_order""",
            metric_id, interval_id, sort_order)

    async def disable_metric_checkpoint(self, row_id: int) -> None:
        await self.conn.execute("UPDATE metric_checkpoints SET enabled=FALSE WHERE id=$1", row_id)

    async def disable_metric_interval(self, row_id: int) -> None:
        await self.conn.execute("UPDATE metric_intervals SET enabled=FALSE WHERE id=$1", row_id)

    async def clear_metric_category(self, metric_id: int) -> None:
        await self.conn.execute("UPDATE metric_definitions SET category_id=NULL WHERE id=$1", metric_id)

    async def get_metrics_with_types(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT md.id, md.slug, md.type, ic.value_type AS ic_value_type
               FROM metric_definitions md
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               WHERE md.user_id = $1""",
            self.user_id)

    async def upsert_computed_config(self, metric_id: int, formula_json: str, result_type: str) -> None:
        await self.conn.execute(
            """INSERT INTO computed_config (metric_id, formula, result_type) VALUES ($1,$2::jsonb,$3)
               ON CONFLICT (metric_id) DO UPDATE SET formula=EXCLUDED.formula, result_type=EXCLUDED.result_type""",
            metric_id, formula_json, result_type)

    async def upsert_condition(
        self, metric_id: int, dep_id: int, cond_type: str, cond_val: str | None,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO metric_condition (metric_id, depends_on_metric_id, condition_type, condition_value)
               VALUES ($1,$2,$3,$4::jsonb)
               ON CONFLICT (metric_id) DO UPDATE
               SET depends_on_metric_id=EXCLUDED.depends_on_metric_id,
                   condition_type=EXCLUDED.condition_type, condition_value=EXCLUDED.condition_value""",
            metric_id, dep_id, cond_type, cond_val)

    async def get_checkpoint_lookup(self, metric_ids: list[int]) -> dict[int, dict[int, int]]:
        if not metric_ids:
            return defaultdict(dict)
        rows = await self.conn.fetch(
            """SELECT mc.metric_id, mc.sort_order, cp.id, cp.label
               FROM metric_checkpoints mc JOIN checkpoints cp ON cp.id = mc.checkpoint_id
               WHERE mc.metric_id = ANY($1) AND mc.enabled = TRUE""",
            metric_ids)
        result: dict[int, dict[int, int]] = defaultdict(dict)
        for sr in rows:
            result[sr["metric_id"]][sr["sort_order"]] = sr["id"]
        return result

    async def get_global_checkpoint_label_lookup(self) -> dict[str, int]:
        """Lookup: label → checkpoint_id for ALL user's checkpoints (including deleted)."""
        rows = await self.conn.fetch(
            "SELECT id, label FROM checkpoints WHERE user_id = $1",
            self.user_id)
        return {r["label"]: r["id"] for r in rows}

    async def check_entry_duplicate(
        self, metric_id: int, d: date_type,
        checkpoint_id: int | None = None, interval_id: int | None = None,
        is_free_checkpoint: bool = False,
    ) -> bool:
        if is_free_checkpoint:
            return False
        if checkpoint_id is not None:
            val = await self.conn.fetchval(
                "SELECT id FROM entries WHERE metric_id=$1 AND user_id=$2 AND date=$3 AND checkpoint_id=$4",
                metric_id, self.user_id, d, checkpoint_id)
        elif interval_id is not None:
            val = await self.conn.fetchval(
                "SELECT id FROM entries WHERE metric_id=$1 AND user_id=$2 AND date=$3 AND interval_id=$4",
                metric_id, self.user_id, d, interval_id)
        else:
            val = await self.conn.fetchval(
                "SELECT id FROM entries WHERE metric_id=$1 AND user_id=$2 AND date=$3 AND checkpoint_id IS NULL AND interval_id IS NULL",
                metric_id, self.user_id, d)
        return val is not None

    async def create_entry(
        self, metric_id: int, d: date_type,
        checkpoint_id: int | None = None, interval_id: int | None = None,
        is_free_checkpoint: bool = False,
        recorded_at: str | None = None,
    ) -> int:
        if is_free_checkpoint and recorded_at:
            return await self.conn.fetchval(
                "INSERT INTO entries (metric_id, user_id, date, checkpoint_id, interval_id, is_free_checkpoint, recorded_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
                metric_id, self.user_id, d, checkpoint_id, interval_id, True, recorded_at)
        return await self.conn.fetchval(
            "INSERT INTO entries (metric_id, user_id, date, checkpoint_id, interval_id, is_free_checkpoint) "
            "VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
            metric_id, self.user_id, d, checkpoint_id, interval_id, is_free_checkpoint)

    async def get_enum_option_labels(self, metric_id: int) -> dict[str, int]:
        rows = await self.conn.fetch("SELECT id, label FROM enum_options WHERE metric_id=$1", metric_id)
        return {r["label"]: r["id"] for r in rows}

    async def insert_metric_checkpoint_on_fly(self, metric_id: int, checkpoint_id: int, sort_order: int) -> None:
        await self.conn.execute(
            "INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
            metric_id, checkpoint_id, sort_order)

    async def insert_metric_interval_on_fly(self, metric_id: int, interval_id: int, sort_order: int) -> None:
        await self.conn.execute(
            "INSERT INTO metric_intervals (metric_id, interval_id, sort_order) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
            metric_id, interval_id, sort_order)

    async def upsert_aw_daily(self, d: date_type, total_seconds: int, active_seconds: int) -> None:
        await self.conn.execute(
            """INSERT INTO activitywatch_daily_summary (user_id, date, total_seconds, active_seconds)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (user_id, date) DO UPDATE
               SET total_seconds=EXCLUDED.total_seconds, active_seconds=EXCLUDED.active_seconds""",
            self.user_id, d, total_seconds, active_seconds)

    async def upsert_aw_app(
        self, d: date_type, app_name: str, source: str, duration_seconds: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO activitywatch_app_usage (user_id, date, app_name, source, duration_seconds)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (user_id, date, app_name, source) DO UPDATE
               SET duration_seconds=EXCLUDED.duration_seconds""",
            self.user_id, d, app_name, source, duration_seconds)

    async def check_note_exists(self, metric_id: int, d: date_type, text: str) -> bool:
        val = await self.conn.fetchval(
            "SELECT id FROM notes WHERE metric_id=$1 AND user_id=$2 AND date=$3 AND text=$4",
            metric_id, self.user_id, d, text)
        return val is not None

    async def insert_note(self, metric_id: int, d: date_type, text: str) -> None:
        await self.conn.execute(
            "INSERT INTO notes (metric_id, user_id, date, text) VALUES ($1,$2,$3,$4)",
            metric_id, self.user_id, d, text)
