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

    async def get_all_user_slots(self) -> list[asyncpg.Record]:
        """Return all user's measurement_slots sorted by sort_order."""
        return await self.conn.fetch(
            "SELECT id, label, sort_order FROM measurement_slots WHERE user_id = $1 AND deleted = FALSE ORDER BY sort_order",
            self.user_id,
        )

    async def get_enabled_slots(self, metric_ids: list[int]) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT ms.id, msl.metric_id, ms.label, ms.sort_order, msl.category_id
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = ANY($1) AND msl.enabled = TRUE AND ms.deleted = FALSE
               ORDER BY msl.metric_id, ms.sort_order""",
            metric_ids,
        )

    async def get_disabled_slots_with_entries(
        self, metric_ids: list[int], d: date_type,
    ) -> list[asyncpg.Record]:
        if not metric_ids:
            return []
        return await self.conn.fetch(
            """SELECT DISTINCT ms.id, msl.metric_id, ms.label, ms.sort_order, msl.category_id
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               JOIN entries e ON e.slot_id = ms.id AND e.date = $1 AND e.user_id = $2
               WHERE msl.metric_id = ANY($3) AND msl.enabled = FALSE
               ORDER BY msl.metric_id, ms.sort_order""",
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
