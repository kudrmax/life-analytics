"""Repository for metric conversion SQL operations."""

import json

import asyncpg

from app.repositories.base import BaseRepository


class MetricConversionRepository(BaseRepository):
    """Data access for metric type conversion operations."""

    # ── Preview queries ────────────────────────────────────────────────

    async def get_scale_value_distribution(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT vs.value, COUNT(*) as cnt
               FROM values_scale vs
               JOIN entries e ON e.id = vs.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY vs.value ORDER BY vs.value""",
            metric_id, self.user_id,
        )

    async def get_bool_value_distribution(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT vb.value, COUNT(*) as cnt
               FROM values_bool vb
               JOIN entries e ON e.id = vb.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY vb.value ORDER BY vb.value""",
            metric_id, self.user_id,
        )

    async def get_enum_multi_select(self, metric_id: int) -> bool:
        ec = await self.conn.fetchrow(
            "SELECT multi_select FROM enum_config WHERE metric_id = $1", metric_id,
        )
        return bool(ec and ec["multi_select"])

    async def get_all_enum_options(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT id, label FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
            metric_id,
        )

    async def get_enum_value_distribution(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT ve.selected_option_ids, COUNT(*) as cnt
               FROM values_enum ve
               JOIN entries e ON e.id = ve.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY ve.selected_option_ids""",
            metric_id, self.user_id,
        )

    # ── Scale → Scale ──────────────────────────────────────────────────

    async def get_distinct_scale_values(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT DISTINCT vs.value FROM values_scale vs
               JOIN entries e ON e.id = vs.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2""",
            metric_id, self.user_id,
        )

    async def delete_entries_by_scale_values(
        self, metric_id: int, values: list[int],
    ) -> int:
        return await self.conn.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_scale vs ON vs.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2
                    AND vs.value = ANY($3::int[])
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, self.user_id, values,
        )

    async def remap_scale_values(
        self, metric_id: int, mapping: dict[int, int],
        s_min: int, s_max: int, s_step: int,
    ) -> int:
        old_values = list(mapping.keys())
        case_clauses = " ".join(
            f"WHEN {old_val} THEN {new_val}" for old_val, new_val in mapping.items()
        )
        return await self.conn.fetchval(
            f"""WITH updated AS (
                UPDATE values_scale vs
                SET value = CASE vs.value {case_clauses} END,
                    scale_min = $2, scale_max = $3, scale_step = $4
                FROM entries e
                WHERE vs.entry_id = e.id AND e.metric_id = $1 AND e.user_id = $5
                AND vs.value = ANY($6::int[])
                RETURNING 1
            ) SELECT COUNT(*) FROM updated""",
            metric_id, s_min, s_max, s_step, self.user_id, old_values,
        )

    async def update_scale_config_values(
        self, metric_id: int, s_min: int, s_max: int, s_step: int,
    ) -> None:
        await self.conn.execute(
            "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3, labels = NULL WHERE metric_id = $4",
            s_min, s_max, s_step, metric_id,
        )

    # ── Bool → Enum ────────────────────────────────────────────────────

    async def get_distinct_bool_values(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT DISTINCT vb.value FROM values_bool vb
               JOIN entries e ON e.id = vb.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2""",
            metric_id, self.user_id,
        )

    async def delete_entries_by_bool_value(self, metric_id: int, bool_val: bool) -> int:
        return await self.conn.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_bool vb ON vb.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2 AND vb.value = $3
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, self.user_id, bool_val,
        )

    async def convert_bool_to_enum_values(
        self, metric_id: int, opt_id: int, bool_val: bool,
    ) -> int:
        return await self.conn.fetchval(
            """WITH inserted AS (
                INSERT INTO values_enum (entry_id, selected_option_ids)
                SELECT vb.entry_id, ARRAY[$3]::integer[]
                FROM values_bool vb
                JOIN entries e ON e.id = vb.entry_id
                WHERE e.metric_id = $1 AND e.user_id = $2 AND vb.value = $4
                RETURNING 1
            ) SELECT COUNT(*) FROM inserted""",
            metric_id, self.user_id, opt_id, bool_val,
        )

    async def delete_all_bool_values(self, metric_id: int) -> None:
        await self.conn.execute(
            """DELETE FROM values_bool WHERE entry_id IN (
                SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2
            )""",
            metric_id, self.user_id,
        )

    # ── Enum → Scale ───────────────────────────────────────────────────

    async def get_distinct_enum_option_ids(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT DISTINCT unnest(ve.selected_option_ids) as option_id
               FROM values_enum ve
               JOIN entries e ON e.id = ve.entry_id
               WHERE e.metric_id = $1 AND e.user_id = $2""",
            metric_id, self.user_id,
        )

    async def delete_entries_by_enum_option(self, metric_id: int, option_id: int) -> int:
        return await self.conn.fetchval(
            """WITH deleted AS (
                DELETE FROM entries WHERE id IN (
                    SELECT e.id FROM entries e
                    JOIN values_enum ve ON ve.entry_id = e.id
                    WHERE e.metric_id = $1 AND e.user_id = $2
                    AND ve.selected_option_ids = ARRAY[$3]::integer[]
                ) RETURNING 1
            ) SELECT COUNT(*) FROM deleted""",
            metric_id, self.user_id, option_id,
        )

    async def convert_enum_to_scale_values(
        self, metric_id: int, option_id: int, scale_val: int,
        s_min: int, s_max: int, s_step: int,
    ) -> int:
        return await self.conn.fetchval(
            """WITH inserted AS (
                INSERT INTO values_scale (entry_id, value, scale_min, scale_max, scale_step)
                SELECT ve.entry_id, $3, $4, $5, $6
                FROM values_enum ve
                JOIN entries e ON e.id = ve.entry_id
                WHERE e.metric_id = $1 AND e.user_id = $2
                AND ve.selected_option_ids = ARRAY[$7]::integer[]
                RETURNING 1
            ) SELECT COUNT(*) FROM inserted""",
            metric_id, self.user_id, scale_val, s_min, s_max, s_step, option_id,
        )

    async def delete_all_enum_values(self, metric_id: int) -> None:
        await self.conn.execute(
            """DELETE FROM values_enum WHERE entry_id IN (
                SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2
            )""",
            metric_id, self.user_id,
        )

    async def delete_enum_options(self, metric_id: int) -> None:
        await self.conn.execute("DELETE FROM enum_options WHERE metric_id = $1", metric_id)

    async def delete_enum_config(self, metric_id: int) -> None:
        await self.conn.execute("DELETE FROM enum_config WHERE metric_id = $1", metric_id)

    async def insert_scale_config_with_labels(
        self, metric_id: int, s_min: int, s_max: int, s_step: int,
        scale_labels: dict | None,
    ) -> None:
        labels_json = json.dumps(scale_labels) if scale_labels else None
        await self.conn.execute(
            """INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step, labels)
               VALUES ($1, $2, $3, $4, $5::jsonb)""",
            metric_id, s_min, s_max, s_step, labels_json,
        )
