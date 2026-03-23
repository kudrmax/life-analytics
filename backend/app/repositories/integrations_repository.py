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
