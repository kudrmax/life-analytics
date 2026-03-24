"""Repository for analytics SQL operations (router-facing)."""

from datetime import date as date_type

import asyncpg

from app.correlation_config import ThresholdsConfig
from app.repositories.base import BaseRepository


class AnalyticsRepository(BaseRepository):
    """Data access for analytics endpoints (routers/analytics.py)."""

    # ── Metric lookups ──────────────────────────────────────────────

    async def get_metric_with_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            """SELECT md.*, cc.formula, cc.result_type, ic.value_type AS ic_value_type
               FROM metric_definitions md
               LEFT JOIN computed_config cc ON cc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               WHERE md.id = $1 AND md.user_id = $2""",
            metric_id, self.user_id,
        )

    async def get_metric_with_computed_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            """SELECT md.*, cc.formula, cc.result_type
               FROM metric_definitions md LEFT JOIN computed_config cc ON cc.metric_id = md.id
               WHERE md.id = $1 AND md.user_id = $2""",
            metric_id, self.user_id,
        )

    # ── Trends / stats queries ───────────────────────────────────────

    async def get_notes_by_date(
        self, metric_id: int, start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT date, COUNT(*) AS cnt FROM notes
               WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
               GROUP BY date ORDER BY date""",
            metric_id, self.user_id, start, end,
        )

    async def get_enum_options_enabled(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT id, label, sort_order FROM enum_options WHERE metric_id = $1 AND enabled = TRUE ORDER BY sort_order",
            metric_id,
        )

    async def get_entries_with_values(
        self, metric_id: int, value_table: str, extra_cols: str,
        start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            f"""SELECT e.date, v.value{extra_cols}
                FROM entries e
                JOIN {value_table} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
                ORDER BY e.date""",
            metric_id, start, end, self.user_id,
        )

    async def has_enabled_slots(self, metric_id: int) -> bool:
        row = await self.conn.fetchrow(
            "SELECT 1 FROM metric_slots WHERE metric_id = $1 AND enabled = TRUE LIMIT 1",
            metric_id,
        )
        return row is not None

    async def get_enum_entries(
        self, metric_id: int, start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT e.date, ve.selected_option_ids
               FROM entries e
               JOIN values_enum ve ON ve.entry_id = e.id
               WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
               ORDER BY e.date""",
            metric_id, start, end, self.user_id,
        )

    async def get_bool_streak_rows(self, metric_id: int) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT e.date, bool_and(vb.value) AS day_value
               FROM entries e
               JOIN values_bool vb ON vb.entry_id = e.id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY e.date
               ORDER BY e.date DESC""",
            metric_id, self.user_id,
        )

    # ── Streaks ──────────────────────────────────────────────────────

    async def get_enabled_bool_metrics(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT * FROM metric_definitions
               WHERE enabled = TRUE AND user_id = $1 AND type = 'bool'
               ORDER BY sort_order""",
            self.user_id,
        )

    # ── Correlation reports ──────────────────────────────────────────

    async def create_report(self, start: date_type, end: date_type) -> int:
        return await self.conn.fetchval(
            """INSERT INTO correlation_reports (user_id, status, period_start, period_end)
               VALUES ($1, 'running', $2, $3) RETURNING id""",
            self.user_id, start, end,
        )

    async def get_all_reports(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT id, status, period_start, period_end, created_at
               FROM correlation_reports
               WHERE user_id = $1
               ORDER BY created_at DESC""",
            self.user_id,
        )

    async def get_report_pair_counts(
        self, report_id: int, thresholds: ThresholdsConfig | None = None,
    ) -> asyncpg.Record:
        strong = thresholds.strong_correlation if thresholds else 0.7
        moderate = thresholds.moderate_correlation if thresholds else 0.3
        return await self.conn.fetchrow(
            f"""SELECT
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) > {strong}) AS sig_strong,
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) > {moderate}
                                    AND ABS(correlation) <= {strong}) AS sig_medium,
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) <= {moderate}) AS sig_weak,
                   COUNT(*) FILTER (WHERE quality_issue IN ('wide_ci', 'fisher_exact_high_p')) AS maybe,
                   COUNT(*) FILTER (WHERE quality_issue IS NOT NULL
                                    AND quality_issue NOT IN ('wide_ci', 'fisher_exact_high_p')) AS insig
               FROM correlation_pairs WHERE report_id = $1""",
            report_id,
        )

    async def get_report_owned(self, report_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id FROM correlation_reports WHERE id = $1 AND user_id = $2",
            report_id, self.user_id,
        )

    async def count_pairs(
        self, report_id: int, cat_filter: str, metric_filter: str, args: list,
    ) -> int:
        row = await self.conn.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM correlation_pairs cp WHERE cp.report_id = $1 {cat_filter}{metric_filter}",
            *args,
        )
        return row["cnt"]

    async def fetch_pairs_page(
        self, report_id: int, cat_filter: str, metric_filter: str,
        args_base: list, limit: int, offset: int,
    ) -> list[asyncpg.Record]:
        limit_idx = len(args_base) + 1
        offset_idx = len(args_base) + 2
        return await self.conn.fetch(
            f"""SELECT cp.id AS pair_id,
                       cp.type_a, cp.type_b, cp.correlation, cp.data_points, cp.lag_days, cp.p_value, cp.quality_issue,
                       cp.metric_a_id, cp.metric_b_id, cp.slot_a_id, cp.slot_b_id,
                       cp.source_key_a, cp.source_key_b,
                       ma.name AS name_a, ma.icon AS icon_a, COALESCE(ma.private, FALSE) AS private_a, ma.description AS description_a,
                       mb.name AS name_b, mb.icon AS icon_b, COALESCE(mb.private, FALSE) AS private_b, mb.description AS description_b,
                       sa.label AS slot_label_a,
                       sb.label AS slot_label_b
                FROM correlation_pairs cp
                LEFT JOIN metric_definitions ma ON ma.id = cp.metric_a_id
                LEFT JOIN metric_definitions mb ON mb.id = cp.metric_b_id
                LEFT JOIN measurement_slots sa ON sa.id = cp.slot_a_id
                LEFT JOIN measurement_slots sb ON sb.id = cp.slot_b_id
                WHERE cp.report_id = $1 {cat_filter}{metric_filter}
                ORDER BY ABS(cp.correlation) DESC
                LIMIT ${limit_idx} OFFSET ${offset_idx}""",
            *args_base, limit, offset,
        )

    async def get_metric_names_icons(self, ids: list[int]) -> list[asyncpg.Record]:
        if not ids:
            return []
        return await self.conn.fetch(
            "SELECT id, name, icon FROM metric_definitions WHERE id = ANY($1)",
            ids,
        )

    async def get_enum_labels(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = await self.conn.fetch(
            "SELECT id, label FROM enum_options WHERE id = ANY($1)",
            ids,
        )
        return {r["id"]: r["label"] for r in rows}

    async def get_metrics_with_slots(self, metric_ids: list[int]) -> set[int]:
        if not metric_ids:
            return set()
        rows = await self.conn.fetch(
            "SELECT DISTINCT metric_id FROM metric_slots WHERE metric_id = ANY($1) AND enabled = TRUE",
            list(metric_ids),
        )
        return {r["metric_id"] for r in rows}

    # ── Source reconstructor support ─────────────────────────────────

    async def get_aw_active_seconds(
        self, start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT date, active_seconds FROM activitywatch_daily_summary
               WHERE user_id = $1 AND date >= $2 AND date <= $3""",
            self.user_id, start, end,
        )

    async def get_metric_type_by_id(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id, type FROM metric_definitions WHERE id = $1",
            metric_id,
        )

    async def get_enabled_slot_ids(self, metric_id: int) -> list[int]:
        rows = await self.conn.fetch(
            """SELECT ms.id FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = $1 AND msl.enabled = TRUE""",
            metric_id,
        )
        return [r["id"] for r in rows]

    async def get_computed_config(self, metric_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT formula, result_type FROM computed_config WHERE metric_id = $1",
            metric_id,
        )

    # ── Value fetcher support ────────────────────────────────────────

    async def fetch_entries_values_with_slot(
        self, metric_id: int, value_table: str, extra_cols: str,
        start: date_type, end: date_type, slot_id: int | None = None,
    ) -> list[asyncpg.Record]:
        slot_filter = ""
        params: list = [metric_id, start, end, self.user_id]
        if slot_id is not None:
            slot_filter = " AND e.slot_id = $5"
            params.append(slot_id)
        return await self.conn.fetch(
            f"""SELECT e.date, v.value{extra_cols}
                FROM entries e
                JOIN {value_table} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3
                  AND e.user_id = $4{slot_filter}
                ORDER BY e.date""",
            *params,
        )

    async def get_scale_config_bounds(self, metric_id: int) -> tuple[int | None, int | None]:
        cfg = await self.conn.fetchrow(
            "SELECT scale_min, scale_max FROM scale_config WHERE metric_id = $1",
            metric_id,
        )
        if cfg:
            return cfg["scale_min"], cfg["scale_max"]
        return None, None

    async def get_metric_types_by_ids(self, metric_ids: list[int]) -> dict[int, str]:
        rows = await self.conn.fetch(
            "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
            metric_ids, self.user_id,
        )
        return {r["id"]: r["type"] for r in rows}

    async def fetch_enum_entries_with_slot(
        self, metric_id: int, start: date_type, end: date_type,
        slot_id: int | None = None,
    ) -> list[asyncpg.Record]:
        slot_filter = ""
        params: list = [metric_id, start, end, self.user_id]
        if slot_id is not None:
            slot_filter = " AND e.slot_id = $5"
            params.append(slot_id)
        return await self.conn.fetch(
            f"""SELECT e.date, ve.selected_option_ids
                FROM entries e
                JOIN values_enum ve ON ve.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3
                  AND e.user_id = $4{slot_filter}
                ORDER BY e.date""",
            *params,
        )

    async def fetch_note_counts(
        self, metric_id: int, start: date_type, end: date_type,
    ) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT date, COUNT(*) as cnt FROM notes
               WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
               GROUP BY date""",
            metric_id, self.user_id, start, end,
        )

    # ── Pair chart ───────────────────────────────────────────────────

    async def get_pair_with_report(self, pair_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            """SELECT cp.*, cr.period_start, cr.period_end, cr.user_id
               FROM correlation_pairs cp
               JOIN correlation_reports cr ON cr.id = cp.report_id
               WHERE cp.id = $1""",
            pair_id,
        )

    async def get_metric_privacy(self, metric_id: int) -> bool:
        row = await self.conn.fetchrow(
            "SELECT private FROM metric_definitions WHERE id = $1", metric_id,
        )
        return row["private"] if row else False

    async def get_computed_result_type(self, metric_id: int) -> str | None:
        cfg = await self.conn.fetchrow(
            "SELECT result_type FROM computed_config WHERE metric_id = $1", metric_id,
        )
        return cfg["result_type"] if cfg else None

    async def get_metric_name(self, metric_id: int) -> str | None:
        row = await self.conn.fetchrow(
            "SELECT name FROM metric_definitions WHERE id = $1", metric_id,
        )
        return row["name"] if row else None
