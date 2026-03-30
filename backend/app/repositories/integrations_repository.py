"""Repository for integrations SQL operations."""

from datetime import date as date_type
from typing import Any

import asyncpg

from app.repositories.base import BaseRepository


class IntegrationsRepository(BaseRepository):
    """Data access for user_integrations and ActivityWatch tables."""

    # ── User integrations ──────────────────────────────────────────────

    async def get_user_integrations(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT provider, enabled, created_at FROM user_integrations WHERE user_id = $1",
            self.user_id,
        )

    async def get_aw_settings(self) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT enabled, aw_url FROM activitywatch_settings WHERE user_id = $1",
            self.user_id,
        )

    async def upsert_todoist_token(self, encrypted_token: str) -> None:
        await self.conn.execute(
            """INSERT INTO user_integrations (user_id, provider, encrypted_token)
               VALUES ($1, 'todoist', $2)
               ON CONFLICT (user_id, provider) DO UPDATE
               SET encrypted_token = EXCLUDED.encrypted_token, enabled = TRUE""",
            self.user_id, encrypted_token,
        )

    async def disconnect_provider(self, provider: str) -> str:
        await self.conn.execute(
            """UPDATE metric_definitions SET enabled = FALSE
               WHERE user_id = $1 AND id IN (
                   SELECT metric_id FROM integration_config WHERE provider = $2
               )""",
            self.user_id, provider,
        )
        return await self.conn.execute(
            "DELETE FROM user_integrations WHERE user_id = $1 AND provider = $2",
            self.user_id, provider,
        )

    # ── ActivityWatch settings ─────────────────────────────────────────

    async def aw_enable(self) -> None:
        await self.conn.execute(
            """INSERT INTO activitywatch_settings (user_id, enabled)
               VALUES ($1, TRUE)
               ON CONFLICT (user_id) DO UPDATE SET enabled = TRUE""",
            self.user_id,
        )

    async def aw_disable(self) -> None:
        await self.conn.execute(
            "UPDATE activitywatch_settings SET enabled = FALSE WHERE user_id = $1",
            self.user_id,
        )

    # ── ActivityWatch summary ──────────────────────────────────────────

    async def get_aw_daily_summary(self, d: date_type) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT total_seconds, active_seconds, synced_at FROM activitywatch_daily_summary WHERE user_id = $1 AND date = $2",
            self.user_id, d,
        )

    async def get_aw_app_usage(self, d: date_type) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT app_name, source, duration_seconds
               FROM activitywatch_app_usage
               WHERE user_id = $1 AND date = $2
               ORDER BY duration_seconds DESC""",
            self.user_id, d,
        )

    async def get_aw_trends(self, start: date_type, end: date_type) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT date, total_seconds, active_seconds
               FROM activitywatch_daily_summary
               WHERE user_id = $1 AND date >= $2 AND date <= $3
               ORDER BY date""",
            self.user_id, start, end,
        )

    # ── ActivityWatch categories ───────────────────────────────────────

    async def get_aw_categories(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT id, name, color, sort_order
               FROM activitywatch_categories
               WHERE user_id = $1
               ORDER BY sort_order, id""",
            self.user_id,
        )

    async def get_aw_next_cat_sort_order(self) -> int:
        val = await self.conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) FROM activitywatch_categories WHERE user_id = $1",
            self.user_id,
        )
        return val + 1

    async def create_aw_category(self, name: str, color: str, sort_order: int) -> int:
        try:
            return await self.conn.fetchval(
                """INSERT INTO activitywatch_categories (user_id, name, color, sort_order)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                self.user_id, name, color, sort_order,
            )
        except Exception:
            from app.domain.exceptions import DuplicateEntityError
            raise DuplicateEntityError("activitywatch_categories", "name", name)

    async def get_aw_category(self, cat_id: int) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        )

    async def update_aw_category(
        self, cat_id: int, updates: list[str], params: list[Any],
    ) -> None:
        idx = len(params) + 1
        params.extend([cat_id, self.user_id])
        await self.conn.execute(
            f"UPDATE activitywatch_categories SET {', '.join(updates)} WHERE id = ${idx} AND user_id = ${idx + 1}",
            *params,
        )

    async def delete_aw_category(self, cat_id: int) -> str:
        return await self.conn.execute(
            "DELETE FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
            cat_id, self.user_id,
        )

    # ── ActivityWatch app→category mapping ─────────────────────────────

    async def get_aw_apps_with_categories(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT DISTINCT au.app_name,
                      acm.activitywatch_category_id,
                      ac.name AS category_name,
                      ac.color AS category_color
               FROM activitywatch_app_usage au
               LEFT JOIN activitywatch_app_category_map acm
                   ON acm.user_id = au.user_id AND acm.app_name = au.app_name
               LEFT JOIN activitywatch_categories ac ON ac.id = acm.activitywatch_category_id
               WHERE au.user_id = $1 AND au.source = 'window'
               ORDER BY au.app_name""",
            self.user_id,
        )

    async def remove_app_category(self, app_name: str) -> None:
        await self.conn.execute(
            "DELETE FROM activitywatch_app_category_map WHERE user_id = $1 AND app_name = $2",
            self.user_id, app_name,
        )

    async def upsert_app_category(self, app_name: str, category_id: int) -> None:
        await self.conn.execute(
            """INSERT INTO activitywatch_app_category_map (user_id, app_name, activitywatch_category_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id, app_name) DO UPDATE SET activitywatch_category_id = EXCLUDED.activitywatch_category_id""",
            self.user_id, app_name, category_id,
        )

    # ── Todoist integration ─────────────────────────────────────────────

    async def get_todoist_token(self) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT encrypted_token FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
            self.user_id,
        )

    async def get_todoist_metrics(self, metric_id: int | None = None) -> list[asyncpg.Record]:
        query = """SELECT md.id, ic.metric_key, ic.value_type,
                      ifc.filter_name, iqc.filter_query
               FROM metric_definitions md
               JOIN integration_config ic ON ic.metric_id = md.id
               LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
               LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
               WHERE md.user_id = $1 AND ic.provider = 'todoist' AND md.enabled = TRUE"""
        params: list = [self.user_id]
        if metric_id is not None:
            query += " AND md.id = $2"
            params.append(metric_id)
        return await self.conn.fetch(query, *params)

    async def get_entry_by_metric_date(self, metric_id: int, for_date: date_type) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND checkpoint_id IS NULL AND interval_id IS NULL",
            metric_id, self.user_id, for_date,
        )

    async def create_entry(self, metric_id: int, for_date: date_type) -> int:
        return await self.conn.fetchval(
            "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
            metric_id, self.user_id, for_date,
        )

    # ── ActivityWatch sync ──────────────────────────────────────────────

    async def upsert_aw_daily_summary(
        self, for_date: date_type, total_seconds: int, active_seconds: int,
        first_activity, last_activity, afk_seconds: int,
        longest_session: int, ctx_switches: int, breaks: int,
    ) -> None:
        await self.conn.execute(
            """INSERT INTO activitywatch_daily_summary
                   (user_id, date, total_seconds, active_seconds, synced_at,
                    first_activity_time, last_activity_time, afk_seconds,
                    longest_session_seconds, context_switches, break_count)
               VALUES ($1, $2, $3, $4, now(), $5, $6, $7, $8, $9, $10)
               ON CONFLICT (user_id, date) DO UPDATE
               SET total_seconds = EXCLUDED.total_seconds,
                   active_seconds = EXCLUDED.active_seconds,
                   first_activity_time = EXCLUDED.first_activity_time,
                   last_activity_time = EXCLUDED.last_activity_time,
                   afk_seconds = EXCLUDED.afk_seconds,
                   longest_session_seconds = EXCLUDED.longest_session_seconds,
                   context_switches = EXCLUDED.context_switches,
                   break_count = EXCLUDED.break_count,
                   synced_at = now()""",
            self.user_id, for_date, total_seconds, active_seconds,
            first_activity, last_activity, afk_seconds,
            longest_session, ctx_switches, breaks,
        )

    async def delete_aw_app_usage_for_date(self, for_date: date_type) -> None:
        await self.conn.execute(
            "DELETE FROM activitywatch_app_usage WHERE user_id = $1 AND date = $2",
            self.user_id, for_date,
        )

    async def insert_aw_app_usage_batch(self, rows: list[tuple]) -> None:
        if rows:
            await self.conn.executemany(
                """INSERT INTO activitywatch_app_usage
                       (user_id, date, app_name, source, duration_seconds)
                   VALUES ($1, $2, $3, $4, $5)""",
                rows,
            )

    async def get_aw_integration_metrics(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT md.id AS metric_id, ic.metric_key, ic.value_type,
                      icc.activitywatch_category_id, iac.app_name AS config_app_name
               FROM metric_definitions md
               JOIN integration_config ic ON ic.metric_id = md.id
               LEFT JOIN integration_category_config icc ON icc.metric_id = md.id
               LEFT JOIN integration_app_config iac ON iac.metric_id = md.id
               WHERE md.user_id = $1 AND ic.provider = 'activitywatch' AND md.enabled = TRUE""",
            self.user_id,
        )

    async def get_aw_summary_full(self, for_date: date_type) -> asyncpg.Record | None:
        return await self.conn.fetchrow(
            """SELECT total_seconds, active_seconds,
                      first_activity_time, last_activity_time,
                      afk_seconds, longest_session_seconds,
                      context_switches, break_count
               FROM activitywatch_daily_summary
               WHERE user_id = $1 AND date = $2""",
            self.user_id, for_date,
        )

    async def get_unique_apps_count(self, for_date: date_type) -> int:
        val = await self.conn.fetchval(
            """SELECT COUNT(DISTINCT app_name) FROM activitywatch_app_usage
               WHERE user_id = $1 AND date = $2 AND source = 'window'""",
            self.user_id, for_date,
        )
        return val or 0

    async def get_category_time_seconds(self, for_date: date_type, cat_id: int) -> int:
        val = await self.conn.fetchval(
            """SELECT COALESCE(SUM(au.duration_seconds), 0)
               FROM activitywatch_app_usage au
               JOIN activitywatch_app_category_map acm
                   ON acm.app_name = au.app_name AND acm.user_id = au.user_id
               WHERE au.user_id = $1 AND au.date = $2 AND acm.activitywatch_category_id = $3
                     AND au.source = 'window'""",
            self.user_id, for_date, cat_id,
        )
        return val or 0

    async def get_app_time_seconds(self, for_date: date_type, app_name: str) -> int:
        val = await self.conn.fetchval(
            """SELECT COALESCE(duration_seconds, 0)
               FROM activitywatch_app_usage
               WHERE user_id = $1 AND date = $2 AND app_name = $3 AND source = 'window'""",
            self.user_id, for_date, app_name,
        )
        return val or 0
