"""Repository for entries CRUD operations."""

from datetime import date as date_type, datetime, time as time_type, timezone

import asyncpg

from app.domain.enums import MetricType
from app.domain.exceptions import EntityNotFoundError
from app.repositories.base import BaseRepository

# SQL fragment: JOIN checkpoints + intervals with labels
_BINDING_JOINS = """
    LEFT JOIN checkpoints cp ON cp.id = e.checkpoint_id
    LEFT JOIN intervals iv ON iv.id = e.interval_id
    LEFT JOIN checkpoints iv_start ON iv_start.id = iv.start_checkpoint_id
    LEFT JOIN checkpoints iv_end ON iv_end.id = iv.end_checkpoint_id
"""

# SQL fragment: binding columns
_BINDING_COLUMNS = (
    "cp.label AS checkpoint_label, "
    "iv_start.label || ' → ' || iv_end.label AS interval_label"
)


class EntryRepository(BaseRepository):
    """Data access for entries and values_* tables."""

    async def list_by_date(
        self, d: date_type, metric_id: int | None = None,
    ) -> list[asyncpg.Record]:
        if metric_id:
            return await self.conn.fetch(
                f"""SELECT e.*, {_BINDING_COLUMNS}
                   FROM entries e
                   {_BINDING_JOINS}
                   WHERE e.date = $1 AND e.metric_id = $2 AND e.user_id = $3""",
                d, metric_id, self.user_id,
            )
        return await self.conn.fetch(
            f"""SELECT e.*, {_BINDING_COLUMNS}
               FROM entries e
               {_BINDING_JOINS}
               WHERE e.date = $1 AND e.user_id = $2
               ORDER BY e.metric_id""",
            d, self.user_id,
        )

    async def get_metric_types(self, metric_ids: list[int]) -> dict[int, str]:
        """Return {metric_id: type} for given IDs."""
        rows = await self.conn.fetch(
            "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
            metric_ids, self.user_id,
        )
        return {r["id"]: r["type"] for r in rows}

    async def get_metric(self, metric_id: int) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("metric_definitions", metric_id)
        return row

    async def check_duplicate(
        self,
        metric_id: int,
        d: date_type,
        checkpoint_id: int | None = None,
        interval_id: int | None = None,
        is_free_checkpoint: bool = False,
        is_free_interval: bool = False,
        time_start: time_type | None = None,
        time_end: time_type | None = None,
    ) -> bool:
        if is_free_checkpoint:
            return False
        if is_free_interval:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 "
                "AND time_start = $4 AND time_end = $5",
                metric_id, self.user_id, d, time_start, time_end,
            )
            return existing is not None
        if checkpoint_id is not None:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND checkpoint_id = $4",
                metric_id, self.user_id, d, checkpoint_id,
            )
        elif interval_id is not None:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND interval_id = $4",
                metric_id, self.user_id, d, interval_id,
            )
        else:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 "
                "AND checkpoint_id IS NULL AND interval_id IS NULL",
                metric_id, self.user_id, d,
            )
        return existing is not None

    async def check_time_overlap(
        self,
        metric_id: int,
        d: date_type,
        time_start: time_type,
        time_end: time_type,
        exclude_entry_id: int | None = None,
    ) -> bool:
        """Check if a new time range overlaps with existing free interval entries."""
        if exclude_entry_id is not None:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 "
                "AND is_free_interval AND time_start < $5 AND time_end > $4 "
                "AND id != $6 LIMIT 1",
                metric_id, self.user_id, d, time_start, time_end, exclude_entry_id,
            )
        else:
            existing = await self.conn.fetchval(
                "SELECT id FROM entries "
                "WHERE metric_id = $1 AND user_id = $2 AND date = $3 "
                "AND is_free_interval AND time_start < $5 AND time_end > $4 LIMIT 1",
                metric_id, self.user_id, d, time_start, time_end,
            )
        return existing is not None

    async def create(
        self,
        metric_id: int,
        d: date_type,
        checkpoint_id: int | None = None,
        interval_id: int | None = None,
        is_free_checkpoint: bool = False,
        is_free_interval: bool = False,
        time_start: time_type | None = None,
        time_end: time_type | None = None,
    ) -> int:
        return await self.conn.fetchval(
            "INSERT INTO entries "
            "(metric_id, user_id, date, checkpoint_id, interval_id, "
            "is_free_checkpoint, is_free_interval, time_start, time_end) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id",
            metric_id, self.user_id, d, checkpoint_id, interval_id,
            is_free_checkpoint, is_free_interval, time_start, time_end,
        )

    async def get_with_binding(self, entry_id: int) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            f"""SELECT e.*, {_BINDING_COLUMNS}
               FROM entries e
               {_BINDING_JOINS}
               WHERE e.id = $1""",
            entry_id,
        )
        if not row:
            raise EntityNotFoundError("entries", entry_id)
        return row

    async def get_owned_with_binding(self, entry_id: int) -> asyncpg.Record:
        row = await self.conn.fetchrow(
            f"""SELECT e.*, {_BINDING_COLUMNS}
               FROM entries e
               {_BINDING_JOINS}
               WHERE e.id = $1 AND e.user_id = $2""",
            entry_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("entries", entry_id)
        return row

    async def update_recorded_at(self, entry_id: int, new_time: datetime) -> None:
        """Update recorded_at for a free_checkpoint entry."""
        result = await self.conn.execute(
            "UPDATE entries SET recorded_at = $1 WHERE id = $2 AND user_id = $3 AND is_free_checkpoint = TRUE",
            new_time, entry_id, self.user_id,
        )
        if result == "UPDATE 0":
            raise EntityNotFoundError("entries", entry_id)

    async def delete(self, entry_id: int) -> None:
        row = await self.conn.fetchval(
            "SELECT id FROM entries WHERE id = $1 AND user_id = $2",
            entry_id, self.user_id,
        )
        if not row:
            raise EntityNotFoundError("entries", entry_id)
        await self.conn.execute(
            "DELETE FROM entries WHERE id = $1 AND user_id = $2",
            entry_id, self.user_id,
        )

    # --- Value operations ---

    async def get_entry_value(
        self, entry_id: int, metric_type: str,
    ) -> bool | str | int | list[int] | None:
        if metric_type == MetricType.time:
            row = await self.conn.fetchrow(
                "SELECT value FROM values_time WHERE entry_id = $1", entry_id,
            )
            if not row:
                return None
            ts = row["value"]
            return f"{ts.hour:02d}:{ts.minute:02d}"
        elif metric_type == MetricType.number:
            row = await self.conn.fetchrow(
                "SELECT value FROM values_number WHERE entry_id = $1", entry_id,
            )
            return row["value"] if row else None
        elif metric_type == MetricType.scale:
            row = await self.conn.fetchrow(
                "SELECT value FROM values_scale WHERE entry_id = $1", entry_id,
            )
            return row["value"] if row else None
        elif metric_type == MetricType.duration:
            row = await self.conn.fetchrow(
                "SELECT value FROM values_duration WHERE entry_id = $1", entry_id,
            )
            return row["value"] if row else None
        elif metric_type == MetricType.enum:
            row = await self.conn.fetchrow(
                "SELECT selected_option_ids FROM values_enum WHERE entry_id = $1", entry_id,
            )
            return list(row["selected_option_ids"]) if row else None
        else:
            row = await self.conn.fetchrow(
                "SELECT value FROM values_bool WHERE entry_id = $1", entry_id,
            )
            return row["value"] if row else None

    async def insert_value(
        self,
        entry_id: int,
        value: bool | str | int | list[int],
        metric_type: str,
        entry_date: date_type | None = None,
        metric_id: int | None = None,
    ) -> None:
        if metric_type == MetricType.time:
            ts = self._parse_time(value, entry_date)
            await self.conn.execute(
                "INSERT INTO values_time (entry_id, value) VALUES ($1, $2)",
                entry_id, ts,
            )
        elif metric_type == MetricType.number:
            await self.conn.execute(
                "INSERT INTO values_number (entry_id, value) VALUES ($1, $2)",
                entry_id, int(value),
            )
        elif metric_type == MetricType.scale:
            cfg = await self.conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
                metric_id,
            )
            s_min = cfg["scale_min"] if cfg else 1
            s_max = cfg["scale_max"] if cfg else 5
            s_step = cfg["scale_step"] if cfg else 1
            await self.conn.execute(
                "INSERT INTO values_scale (entry_id, value, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4, $5)",
                entry_id, int(value), s_min, s_max, s_step,
            )
        elif metric_type == MetricType.duration:
            await self.conn.execute(
                "INSERT INTO values_duration (entry_id, value) VALUES ($1, $2)",
                entry_id, int(value),
            )
        elif metric_type == MetricType.enum:
            option_ids = value if isinstance(value, list) else [value]
            await self.conn.execute(
                "INSERT INTO values_enum (entry_id, selected_option_ids) VALUES ($1, $2)",
                entry_id, option_ids,
            )
        else:
            await self.conn.execute(
                "INSERT INTO values_bool (entry_id, value) VALUES ($1, $2)",
                entry_id, value,
            )

    async def update_value(
        self,
        entry_id: int,
        value: bool | str | int | list[int],
        metric_type: str,
        entry_date: date_type | None = None,
        metric_id: int | None = None,
    ) -> None:
        if metric_type == MetricType.time:
            ts = self._parse_time(value, entry_date)
            await self.conn.execute(
                "UPDATE values_time SET value = $1 WHERE entry_id = $2",
                ts, entry_id,
            )
        elif metric_type == MetricType.number:
            await self.conn.execute(
                "UPDATE values_number SET value = $1 WHERE entry_id = $2",
                int(value), entry_id,
            )
        elif metric_type == MetricType.scale:
            await self.conn.execute(
                "UPDATE values_scale SET value = $1 WHERE entry_id = $2",
                int(value), entry_id,
            )
        elif metric_type == MetricType.duration:
            await self.conn.execute(
                "UPDATE values_duration SET value = $1 WHERE entry_id = $2",
                int(value), entry_id,
            )
        elif metric_type == MetricType.enum:
            option_ids = value if isinstance(value, list) else [value]
            await self.conn.execute(
                "UPDATE values_enum SET selected_option_ids = $1 WHERE entry_id = $2",
                option_ids, entry_id,
            )
        else:
            await self.conn.execute(
                "UPDATE values_bool SET value = $1 WHERE entry_id = $2",
                value, entry_id,
            )

    async def get_metric_type(self, metric_id: int) -> str | None:
        row = await self.conn.fetchrow(
            "SELECT type FROM metric_definitions WHERE id = $1 AND user_id = $2",
            metric_id, self.user_id,
        )
        return row["type"] if row else None

    async def resolve_storage_type(self, metric_id: int, metric_type: str) -> str:
        """For integration metrics, resolve the actual storage type."""
        if metric_type != MetricType.integration:
            return metric_type
        row = await self.conn.fetchrow(
            "SELECT value_type FROM integration_config WHERE metric_id = $1", metric_id,
        )
        return row["value_type"] if row else "number"

    @staticmethod
    def _parse_time(value: str, entry_date: date_type | None) -> datetime:
        parts = value.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        d = entry_date or date_type.today()
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
