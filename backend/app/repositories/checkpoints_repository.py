"""Repository for checkpoints and intervals CRUD operations."""

import asyncpg

from app.domain.exceptions import EntityNotFoundError, DuplicateEntityError
from app.repositories.base import BaseRepository


class CheckpointsRepository(BaseRepository):
    """Data access for checkpoints and intervals tables."""

    # ─── Checkpoints ────────────────────────────────────────────

    async def get_all_with_usage(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            """SELECT c.id, c.label, c.sort_order, c.description,
                      (SELECT count(*) FROM metric_checkpoints mc
                       WHERE mc.checkpoint_id = c.id AND mc.enabled = TRUE) AS usage_count,
                      ARRAY(SELECT md.name FROM metric_checkpoints mc
                            JOIN metric_definitions md ON md.id = mc.metric_id
                            WHERE mc.checkpoint_id = c.id AND mc.enabled = TRUE
                            ORDER BY md.name) AS usage_metric_names
               FROM checkpoints c
               WHERE c.user_id = $1 AND c.deleted = FALSE
               ORDER BY c.sort_order, c.id""",
            self.user_id,
        )

    async def get_enabled_usage_count(self, checkpoint_id: int) -> int:
        return await self.conn.fetchval(
            """SELECT count(*) FROM metric_checkpoints
               WHERE checkpoint_id = $1 AND enabled = TRUE""",
            checkpoint_id,
        )

    async def get_enabled_metric_names(self, checkpoint_id: int) -> list[str]:
        rows = await self.conn.fetch(
            """SELECT md.name FROM metric_checkpoints mc
               JOIN metric_definitions md ON md.id = mc.metric_id
               WHERE mc.checkpoint_id = $1 AND mc.enabled = TRUE
               ORDER BY md.name""",
            checkpoint_id,
        )
        return [r["name"] for r in rows]

    async def delete_disabled_metric_checkpoints(self, checkpoint_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM metric_checkpoints WHERE checkpoint_id = $1 AND enabled = FALSE",
            checkpoint_id,
        )

    async def get_by_id(self, checkpoint_id: int) -> asyncpg.Record:
        return await self._fetch_owned("checkpoints", checkpoint_id)

    async def get_next_sort_order(self) -> int:
        val = await self.conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) FROM checkpoints WHERE user_id = $1",
            self.user_id,
        )
        return val + 1

    async def create(self, label: str, sort_order: int, description: str | None = None) -> int:
        try:
            checkpoint_id = await self.conn.fetchval(
                """INSERT INTO checkpoints (user_id, label, sort_order, description)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                self.user_id, label, sort_order, description,
            )
        except Exception:
            raise DuplicateEntityError("checkpoints", "label", label)

        await self.recalculate_intervals()
        return checkpoint_id

    async def update_label(self, checkpoint_id: int, label: str) -> None:
        try:
            await self.conn.execute(
                "UPDATE checkpoints SET label = $1 WHERE id = $2 AND user_id = $3",
                label, checkpoint_id, self.user_id,
            )
        except Exception:
            raise DuplicateEntityError("checkpoints", "label", label)

    async def update_description(self, checkpoint_id: int, description: str | None) -> None:
        await self.conn.execute(
            "UPDATE checkpoints SET description = $1 WHERE id = $2 AND user_id = $3",
            description, checkpoint_id, self.user_id,
        )

    async def get_updated(self, checkpoint_id: int) -> asyncpg.Record:
        return await self.conn.fetchrow(
            "SELECT id, label, sort_order, description FROM checkpoints WHERE id = $1",
            checkpoint_id,
        )

    async def delete(self, checkpoint_id: int) -> None:
        await self.conn.execute(
            "UPDATE checkpoints SET deleted = TRUE WHERE id = $1 AND user_id = $2",
            checkpoint_id, self.user_id,
        )
        await self.recalculate_intervals()

    async def merge(self, source_id: int, target_id: int) -> dict:
        """Merge source checkpoint into target checkpoint. Returns stats dict."""
        async with self.conn.transaction():
            # 1. Redirect intervals referencing source checkpoint to target.
            #    An interval has start_checkpoint_id and end_checkpoint_id.
            #    If redirecting would create a duplicate (same start+end pair), delete instead.

            # Find intervals that would conflict after redirect
            conflicting_start = await self.conn.fetch(
                """SELECT i_src.id
                   FROM intervals i_src
                   JOIN intervals i_tgt
                        ON i_tgt.start_checkpoint_id = $2
                       AND i_tgt.end_checkpoint_id = i_src.end_checkpoint_id
                       AND i_tgt.user_id = $3
                   WHERE i_src.start_checkpoint_id = $1
                     AND i_src.user_id = $3""",
                source_id, target_id, self.user_id,
            )
            conflicting_end = await self.conn.fetch(
                """SELECT i_src.id
                   FROM intervals i_src
                   JOIN intervals i_tgt
                        ON i_tgt.end_checkpoint_id = $2
                       AND i_tgt.start_checkpoint_id = i_src.start_checkpoint_id
                       AND i_tgt.user_id = $3
                   WHERE i_src.end_checkpoint_id = $1
                     AND i_src.user_id = $3""",
                source_id, target_id, self.user_id,
            )
            # Also intervals where both start and end would become target (self-loops)
            self_loop = await self.conn.fetch(
                """SELECT id FROM intervals
                   WHERE user_id = $1
                     AND (
                         (start_checkpoint_id = $2 AND end_checkpoint_id = $3)
                         OR (start_checkpoint_id = $3 AND end_checkpoint_id = $2)
                         OR (start_checkpoint_id = $2 AND end_checkpoint_id = $2)
                     )""",
                self.user_id, source_id, target_id,
            )

            conflicting_ids = list({
                r["id"]
                for r in [*conflicting_start, *conflicting_end, *self_loop]
            })
            if conflicting_ids:
                await self.conn.execute(
                    "DELETE FROM intervals WHERE id = ANY($1::int[])",
                    conflicting_ids,
                )

            intervals_start_moved = await self.conn.execute(
                """UPDATE intervals SET start_checkpoint_id = $1
                   WHERE start_checkpoint_id = $2 AND user_id = $3""",
                target_id, source_id, self.user_id,
            )
            intervals_end_moved = await self.conn.execute(
                """UPDATE intervals SET end_checkpoint_id = $1
                   WHERE end_checkpoint_id = $2 AND user_id = $3""",
                target_id, source_id, self.user_id,
            )
            intervals_affected = (
                int(intervals_start_moved.split()[-1])
                + int(intervals_end_moved.split()[-1])
                + len(conflicting_ids)
            )

            # 2. Move metric_checkpoints: delete duplicate (same metric+target already exists), move rest
            await self.conn.execute(
                """DELETE FROM metric_checkpoints mc_src
                   USING metric_checkpoints mc_tgt
                   WHERE mc_src.checkpoint_id = $1
                     AND mc_tgt.checkpoint_id = $2
                     AND mc_tgt.metric_id = mc_src.metric_id""",
                source_id, target_id,
            )
            await self.conn.execute(
                "UPDATE metric_checkpoints SET checkpoint_id = $1 WHERE checkpoint_id = $2",
                target_id, source_id,
            )

            # 3. Move entries: delete conflicting (same metric_id, user_id, date), move rest
            entries_deleted_result = await self.conn.execute(
                """DELETE FROM entries e_src
                   USING entries e_tgt
                   WHERE e_src.checkpoint_id = $1
                     AND e_src.user_id = $2
                     AND e_tgt.checkpoint_id = $3
                     AND e_tgt.user_id = $2
                     AND e_tgt.metric_id = e_src.metric_id
                     AND e_tgt.date = e_src.date""",
                source_id, self.user_id, target_id,
            )
            entries_deleted = int(entries_deleted_result.split()[-1])

            entries_moved_result = await self.conn.execute(
                "UPDATE entries SET checkpoint_id = $1 WHERE checkpoint_id = $2 AND user_id = $3",
                target_id, source_id, self.user_id,
            )
            entries_moved = int(entries_moved_result.split()[-1])

            # 3. Delete source checkpoint
            await self.conn.execute(
                "DELETE FROM checkpoints WHERE id = $1 AND user_id = $2",
                source_id, self.user_id,
            )

        return {
            "intervals_affected": intervals_affected,
            "entries_moved": entries_moved,
            "entries_deleted": entries_deleted,
        }

    async def reorder(self, items: list[dict]) -> None:
        async with self.conn.transaction():
            for item in items:
                await self.conn.execute(
                    """UPDATE checkpoints
                       SET sort_order = $1
                       WHERE id = $2 AND user_id = $3""",
                    item["sort_order"], item["id"], self.user_id,
                )

    # ─── Intervals ──────────────────────────────────────────────

    async def get_user_intervals(self) -> list[asyncpg.Record]:
        """Get all intervals for the user with checkpoint labels."""
        return await self.conn.fetch(
            """SELECT i.id,
                      i.start_checkpoint_id,
                      i.end_checkpoint_id,
                      cs.label AS start_label,
                      ce.label AS end_label,
                      cs.sort_order AS start_sort_order,
                      ce.sort_order AS end_sort_order
               FROM intervals i
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE i.user_id = $1
               ORDER BY cs.sort_order, ce.sort_order""",
            self.user_id,
        )

    async def get_active_intervals(self) -> list[asyncpg.Record]:
        """Get intervals where both checkpoints are not deleted AND consecutive.

        Consecutive means there is no other non-deleted checkpoint
        with sort_order strictly between the start and end checkpoint sort_orders.
        """
        return await self.conn.fetch(
            """SELECT i.id,
                      i.start_checkpoint_id,
                      i.end_checkpoint_id,
                      cs.label AS start_label,
                      ce.label AS end_label,
                      cs.sort_order AS start_sort_order,
                      ce.sort_order AS end_sort_order
               FROM intervals i
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE i.user_id = $1
                 AND cs.deleted = FALSE
                 AND ce.deleted = FALSE
                 AND NOT EXISTS (
                     SELECT 1 FROM checkpoints cm
                     WHERE cm.user_id = $1
                       AND cm.deleted = FALSE
                       AND cm.sort_order > cs.sort_order
                       AND cm.sort_order < ce.sort_order
                 )
               ORDER BY cs.sort_order""",
            self.user_id,
        )

    async def recalculate_intervals(self) -> None:
        """Recalculate intervals for the user.

        Gets all non-deleted checkpoints ordered by sort_order,
        creates intervals for each consecutive pair.
        Uses INSERT ON CONFLICT DO NOTHING to preserve existing intervals.
        """
        checkpoints = await self.conn.fetch(
            """SELECT id, sort_order
               FROM checkpoints
               WHERE user_id = $1 AND deleted = FALSE
               ORDER BY sort_order, id""",
            self.user_id,
        )

        for i in range(len(checkpoints) - 1):
            start_checkpoint_id = checkpoints[i]["id"]
            end_checkpoint_id = checkpoints[i + 1]["id"]
            await self.conn.execute(
                """INSERT INTO intervals (user_id, start_checkpoint_id, end_checkpoint_id)
                   VALUES ($1, $2, $3)
                   ON CONFLICT DO NOTHING""",
                self.user_id, start_checkpoint_id, end_checkpoint_id,
            )
