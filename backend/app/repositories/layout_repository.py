"""Repository for daily layout — top-level block ordering."""

from app.repositories.base import BaseRepository


class LayoutRepository(BaseRepository):
    """CRUD for daily_layout table."""

    async def get_layout(self) -> list:
        """Get all layout entries for user, ordered by sort_order."""
        return await self.conn.fetch(
            "SELECT id, block_type, block_id, sort_order FROM daily_layout "
            "WHERE user_id = $1 ORDER BY sort_order, id",
            self.user_id,
        )

    async def save_layout(self, items: list[dict]) -> None:
        """Replace all layout entries for user with new ordering."""
        async with self.conn.transaction():
            await self.conn.execute(
                "DELETE FROM daily_layout WHERE user_id = $1",
                self.user_id,
            )
            for item in items:
                await self.conn.execute(
                    "INSERT INTO daily_layout (user_id, block_type, block_id, sort_order) "
                    "VALUES ($1, $2, $3, $4)",
                    self.user_id, item["block_type"], item["block_id"], item["sort_order"],
                )

    async def get_active_checkpoints(self) -> list:
        """Active (non-deleted) checkpoints ordered by sort_order."""
        return await self.conn.fetch(
            "SELECT id, label, sort_order, description FROM checkpoints "
            "WHERE user_id = $1 AND deleted = FALSE ORDER BY sort_order",
            self.user_id,
        )

    async def get_active_intervals(self) -> list:
        """Active intervals (both checkpoints non-deleted and consecutive)."""
        return await self.conn.fetch(
            """SELECT i.id, i.start_checkpoint_id, i.end_checkpoint_id,
                      cs.label || ' → ' || ce.label AS label
               FROM intervals i
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE i.user_id = $1
                 AND cs.deleted = FALSE AND ce.deleted = FALSE
                 AND NOT EXISTS (
                     SELECT 1 FROM checkpoints cm
                     WHERE cm.user_id = $1 AND cm.deleted = FALSE
                       AND cm.sort_order > cs.sort_order AND cm.sort_order < ce.sort_order
                 )
               ORDER BY cs.sort_order""",
            self.user_id,
        )

    async def get_enabled_metrics(self) -> list:
        """Enabled metrics with checkpoint/interval bindings."""
        return await self.conn.fetch(
            """SELECT md.id, md.name, md.icon, md.type, md.sort_order,
                      md.category_id, md.is_checkpoint, md.interval_binding
               FROM metric_definitions md
               WHERE md.user_id = $1 AND md.enabled = TRUE
               ORDER BY md.sort_order, md.id""",
            self.user_id,
        )

    async def get_metric_checkpoints(self, metric_ids: list[int]) -> list:
        """Get enabled checkpoint bindings for given metrics."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT mc.metric_id, mc.checkpoint_id, mc.sort_order, mc.category_id,
                      c.label AS checkpoint_label
               FROM metric_checkpoints mc
               JOIN checkpoints c ON c.id = mc.checkpoint_id
               WHERE mc.metric_id = ANY($1) AND mc.enabled = TRUE AND c.deleted = FALSE
               ORDER BY mc.metric_id, mc.sort_order""",
            metric_ids,
        )

    async def get_metric_intervals(self, metric_ids: list[int]) -> list:
        """Get enabled interval bindings for given metrics."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT mi.metric_id, mi.interval_id, mi.sort_order, mi.category_id,
                      cs.label || ' → ' || ce.label AS interval_label
               FROM metric_intervals mi
               JOIN intervals i ON i.id = mi.interval_id
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE mi.metric_id = ANY($1) AND mi.enabled = TRUE
                 AND cs.deleted = FALSE AND ce.deleted = FALSE
               ORDER BY mi.metric_id, mi.sort_order""",
            metric_ids,
        )

    async def get_categories(self) -> list:
        """User categories."""
        return await self.conn.fetch(
            "SELECT id, name, parent_id, sort_order FROM categories "
            "WHERE user_id = $1 ORDER BY sort_order, id",
            self.user_id,
        )

    async def save_inner_checkpoint(self, checkpoint_id: int, items: list[dict]) -> None:
        """Save metric ordering within a checkpoint block."""
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    "UPDATE metric_checkpoints SET sort_order = $1, category_id = $2 "
                    "WHERE metric_id = $3 AND checkpoint_id = $4",
                    item["sort_order"], item.get("category_id"), item["metric_id"], checkpoint_id,
                )

    async def save_inner_interval(self, interval_id: int, items: list[dict]) -> None:
        """Save metric ordering within an interval block."""
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    "UPDATE metric_intervals SET sort_order = $1, category_id = $2 "
                    "WHERE metric_id = $3 AND interval_id = $4",
                    item["sort_order"], item.get("category_id"), item["metric_id"], interval_id,
                )

    async def save_inner_standalone(self, items: list[dict]) -> None:
        """Save metric ordering for standalone metrics (category or uncategorized)."""
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    "UPDATE metric_definitions SET sort_order = $1, category_id = $2 "
                    "WHERE id = $3 AND user_id = $4",
                    item["sort_order"], item.get("category_id"), item["metric_id"], self.user_id,
                )
