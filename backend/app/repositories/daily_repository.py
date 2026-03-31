"""Repository for daily summary data loading."""

from collections import defaultdict
from datetime import date as date_type

import asyncpg

from app.repositories.base import BaseRepository
from app.repositories.metric_repository import _METRIC_WITH_CONFIG_SQL


class DailyRepository(BaseRepository):
    """Data access for daily summary endpoint."""

    async def get_enabled_metrics_with_config(self) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            _METRIC_WITH_CONFIG_SQL + """
            WHERE md.enabled = TRUE AND md.user_id = $1
            ORDER BY md.sort_order, md.id""",
            self.user_id,
        )

    async def get_entries_for_date(self, d: date_type) -> list[asyncpg.Record]:
        return await self.conn.fetch(
            "SELECT * FROM entries WHERE date = $1 AND user_id = $2",
            d, self.user_id,
        )

    async def get_daily_layout(self) -> list[asyncpg.Record]:
        """Get daily layout block ordering for user."""
        return await self.conn.fetch(
            "SELECT block_type, block_id, sort_order FROM daily_layout "
            "WHERE user_id = $1 ORDER BY sort_order, id",
            self.user_id,
        )

    async def get_all_user_checkpoints(self) -> list[asyncpg.Record]:
        """Return all user's checkpoints sorted by sort_order."""
        return await self.conn.fetch(
            "SELECT id, label, sort_order FROM checkpoints "
            "WHERE user_id = $1 AND deleted = FALSE ORDER BY sort_order",
            self.user_id,
        )

    async def get_active_intervals(self) -> list[asyncpg.Record]:
        """Get intervals where both checkpoints are not deleted AND consecutive.

        Consecutive means there is no other non-deleted checkpoint
        with sort_order strictly between the start and end checkpoint sort_orders.
        Returns id, start_checkpoint_id, end_checkpoint_id, label (start → end).
        """
        return await self.conn.fetch(
            """SELECT i.id,
                      i.start_checkpoint_id,
                      i.end_checkpoint_id,
                      cs.label || ' \u2192 ' || ce.label AS label,
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

    async def get_enabled_checkpoints(
        self, metric_ids: list[int],
    ) -> list[asyncpg.Record]:
        """Get enabled metric_checkpoints joined with checkpoints."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT c.id, mc.metric_id, c.label, c.sort_order
               FROM metric_checkpoints mc
               JOIN checkpoints c ON c.id = mc.checkpoint_id
               WHERE mc.metric_id = ANY($1) AND mc.enabled = TRUE AND c.deleted = FALSE
               ORDER BY mc.metric_id, c.sort_order""",
            metric_ids,
        )

    async def get_enabled_intervals(
        self, metric_ids: list[int],
    ) -> list[asyncpg.Record]:
        """Get enabled metric_intervals joined with intervals and checkpoints."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT i.id, mi.metric_id,
                      cs.label || ' \u2192 ' || ce.label AS label,
                      cs.sort_order AS start_sort_order
               FROM metric_intervals mi
               JOIN intervals i ON i.id = mi.interval_id
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               WHERE mi.metric_id = ANY($1) AND mi.enabled = TRUE
                 AND cs.deleted = FALSE AND ce.deleted = FALSE
               ORDER BY mi.metric_id, cs.sort_order""",
            metric_ids,
        )

    async def get_disabled_checkpoints_with_entries(
        self, metric_ids: list[int], d: date_type,
    ) -> list[asyncpg.Record]:
        """Disabled metric_checkpoints that have entries on the given date."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT DISTINCT c.id, mc.metric_id, c.label, c.sort_order
               FROM metric_checkpoints mc
               JOIN checkpoints c ON c.id = mc.checkpoint_id
               JOIN entries e ON e.checkpoint_id = c.id AND e.metric_id = mc.metric_id AND e.date = $1 AND e.user_id = $2
               WHERE mc.metric_id = ANY($3) AND mc.enabled = FALSE
               ORDER BY mc.metric_id, c.sort_order""",
            d, self.user_id, metric_ids,
        )

    async def get_disabled_intervals_with_entries(
        self, metric_ids: list[int], d: date_type,
    ) -> list[asyncpg.Record]:
        """Disabled metric_intervals that have entries on the given date."""
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT DISTINCT i.id, mi.metric_id,
                      cs.label || ' \u2192 ' || ce.label AS label,
                      cs.sort_order AS start_sort_order
               FROM metric_intervals mi
               JOIN intervals i ON i.id = mi.interval_id
               JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
               JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
               JOIN entries e ON e.interval_id = i.id AND e.metric_id = mi.metric_id AND e.date = $1 AND e.user_id = $2
               WHERE mi.metric_id = ANY($3) AND mi.enabled = FALSE
               ORDER BY mi.metric_id, cs.sort_order""",
            d, self.user_id, metric_ids,
        )

    async def batch_load_values(
        self, entry_ids_by_type: dict[str, list[int]],
    ) -> tuple[dict[int, object], dict[int, dict]]:
        """Batch-load all entry values by type. Returns (values_map, scale_context_map)."""
        values_map: dict[int, object] = {}
        scale_context_map: dict[int, dict] = {}

        if entry_ids_by_type.get("bool"):
            rows = await self.conn.fetch(
                "SELECT entry_id, value FROM values_bool WHERE entry_id = ANY($1)",
                entry_ids_by_type["bool"],
            )
            for r in rows:
                values_map[r["entry_id"]] = r["value"]

        if entry_ids_by_type.get("number"):
            rows = await self.conn.fetch(
                "SELECT entry_id, value FROM values_number WHERE entry_id = ANY($1)",
                entry_ids_by_type["number"],
            )
            for r in rows:
                values_map[r["entry_id"]] = r["value"]

        if entry_ids_by_type.get("time"):
            rows = await self.conn.fetch(
                "SELECT entry_id, value FROM values_time WHERE entry_id = ANY($1)",
                entry_ids_by_type["time"],
            )
            for r in rows:
                ts = r["value"]
                values_map[r["entry_id"]] = f"{ts.hour:02d}:{ts.minute:02d}"

        if entry_ids_by_type.get("scale"):
            rows = await self.conn.fetch(
                "SELECT entry_id, value, scale_min, scale_max, scale_step FROM values_scale WHERE entry_id = ANY($1)",
                entry_ids_by_type["scale"],
            )
            for r in rows:
                values_map[r["entry_id"]] = r["value"]
                scale_context_map[r["entry_id"]] = {
                    "scale_min": r["scale_min"],
                    "scale_max": r["scale_max"],
                    "scale_step": r["scale_step"],
                }

        if entry_ids_by_type.get("duration"):
            rows = await self.conn.fetch(
                "SELECT entry_id, value FROM values_duration WHERE entry_id = ANY($1)",
                entry_ids_by_type["duration"],
            )
            for r in rows:
                values_map[r["entry_id"]] = r["value"]

        if entry_ids_by_type.get("enum"):
            rows = await self.conn.fetch(
                "SELECT entry_id, selected_option_ids FROM values_enum WHERE entry_id = ANY($1)",
                entry_ids_by_type["enum"],
            )
            for r in rows:
                values_map[r["entry_id"]] = list(r["selected_option_ids"])

        return values_map, scale_context_map

    async def get_enum_options_for_metrics(
        self, metric_ids: list[int],
    ) -> dict[int, list]:
        if not metric_ids:
            return {}
        rows = await self.conn.fetch(
            """SELECT id, metric_id, label, sort_order FROM enum_options
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            metric_ids,
        )
        result: dict[int, list] = defaultdict(list)
        for r in rows:
            result[r["metric_id"]].append({
                "id": r["id"], "label": r["label"], "sort_order": r["sort_order"],
            })
        return result

    async def get_notes_for_date(
        self, metric_ids: list[int], d: date_type,
    ) -> tuple[dict[int, int], dict[int, list]]:
        """Returns (notes_count_map, notes_by_metric)."""
        notes_count_map: dict[int, int] = {}
        notes_by_metric: dict[int, list] = defaultdict(list)
        if not metric_ids:
            return notes_count_map, notes_by_metric

        nc_rows = await self.conn.fetch(
            "SELECT metric_id, COUNT(*) AS cnt FROM notes WHERE metric_id = ANY($1) AND user_id = $2 AND date = $3 GROUP BY metric_id",
            metric_ids, self.user_id, d,
        )
        for r in nc_rows:
            notes_count_map[r["metric_id"]] = r["cnt"]

        n_rows = await self.conn.fetch(
            "SELECT id, metric_id, text, created_at FROM notes WHERE metric_id = ANY($1) AND user_id = $2 AND date = $3 ORDER BY created_at",
            metric_ids, self.user_id, d,
        )
        for r in n_rows:
            notes_by_metric[r["metric_id"]].append({
                "id": r["id"], "text": r["text"], "created_at": str(r["created_at"]),
            })
        return notes_count_map, notes_by_metric
