"""Service layer for entries — business logic between router and repository."""

from datetime import date as date_type, datetime, time as time_type, timezone

from app.domain.constants import FREE_CHECKPOINTS_SUPPORTED_TYPES, FREE_INTERVALS_SUPPORTED_TYPES
from app.domain.enums import IntervalBinding, MetricType
from app.domain.exceptions import ConflictError, EntityNotFoundError, InvalidOperationError
from app.repositories.entry_repository import EntryRepository
from app.schemas import EntryOut


def _format_time(t: time_type | None) -> str | None:
    if t is None:
        return None
    return f"{t.hour:02d}:{t.minute:02d}"


def _parse_time_str(s: str) -> time_type:
    parts = s.split(":")
    return time_type(int(parts[0]), int(parts[1]))


async def _entry_to_out(repo: EntryRepository, entry_row, metric_type: str = MetricType.bool) -> EntryOut:
    value = await repo.get_entry_value(entry_row["id"], metric_type)
    default = False if metric_type == MetricType.bool else None
    return EntryOut(
        id=entry_row["id"],
        metric_id=entry_row["metric_id"],
        date=str(entry_row["date"]),
        recorded_at=str(entry_row["recorded_at"]),
        value=value if value is not None else default,
        checkpoint_id=entry_row.get("checkpoint_id"),
        checkpoint_label=entry_row.get("checkpoint_label") or "",
        interval_id=entry_row.get("interval_id"),
        interval_label=entry_row.get("interval_label") or "",
        is_free_checkpoint=bool(entry_row.get("is_free_checkpoint", False)),
        is_free_interval=bool(entry_row.get("is_free_interval", False)),
        time_start=_format_time(entry_row.get("time_start")),
        time_end=_format_time(entry_row.get("time_end")),
    )


class EntriesService:
    def __init__(self, repo: EntryRepository) -> None:
        self.repo = repo

    async def list_by_date(self, date_str: str, metric_id: int | None) -> list[EntryOut]:
        d = date_type.fromisoformat(date_str)
        rows = await self.repo.list_by_date(d, metric_id)

        metric_ids = list({r["metric_id"] for r in rows})
        type_lookup: dict[int, str] = {}
        if metric_ids:
            raw_types = await self.repo.get_metric_types(metric_ids)
            for mid, mtype in raw_types.items():
                type_lookup[mid] = await self.repo.resolve_storage_type(mid, mtype)

        return [await _entry_to_out(self.repo, r, type_lookup.get(r["metric_id"], MetricType.bool)) for r in rows]

    async def create(
        self, metric_id: int, date_str: str, value,
        checkpoint_id: int | None = None, interval_id: int | None = None,
        time_start: str | None = None, time_end: str | None = None,
    ) -> EntryOut:
        if checkpoint_id is not None and interval_id is not None:
            raise InvalidOperationError("Entry cannot have both checkpoint_id and interval_id")

        metric = await self.repo.get_metric(metric_id)
        d = date_type.fromisoformat(date_str)

        is_free_cp = metric.get("interval_binding") == IntervalBinding.FREE_CHECKPOINTS
        is_free_iv = metric.get("interval_binding") == IntervalBinding.FREE_INTERVALS

        if is_free_cp:
            if metric["type"] not in FREE_CHECKPOINTS_SUPPORTED_TYPES:
                raise InvalidOperationError(f"Metric type '{metric['type']}' does not support free checkpoints")
            if checkpoint_id is not None or interval_id is not None:
                raise InvalidOperationError("Free checkpoint entries cannot have checkpoint_id or interval_id")

        ts_start: time_type | None = None
        ts_end: time_type | None = None

        if is_free_iv:
            if metric["type"] not in FREE_INTERVALS_SUPPORTED_TYPES:
                raise InvalidOperationError(f"Metric type '{metric['type']}' does not support free intervals")
            if checkpoint_id is not None or interval_id is not None:
                raise InvalidOperationError("Free interval entries cannot have checkpoint_id or interval_id")
            if time_start is None or time_end is None:
                raise InvalidOperationError("Free interval entries require both time_start and time_end")
            ts_start = _parse_time_str(time_start)
            ts_end = _parse_time_str(time_end)
            if ts_end <= ts_start:
                raise InvalidOperationError("time_end must be after time_start")
            if await self.repo.check_time_overlap(metric_id, d, ts_start, ts_end):
                raise ConflictError("Time range overlaps with an existing entry")

        if await self.repo.check_duplicate(
            metric_id, d, checkpoint_id, interval_id,
            is_free_checkpoint=is_free_cp,
            is_free_interval=is_free_iv,
            time_start=ts_start, time_end=ts_end,
        ):
            raise ConflictError("Entry already exists for this metric/date/time range. Use PUT to update.")

        mt = await self.repo.resolve_storage_type(metric_id, metric["type"])
        async with self.repo.transaction():
            entry_id = await self.repo.create(
                metric_id, d, checkpoint_id, interval_id,
                is_free_checkpoint=is_free_cp,
                is_free_interval=is_free_iv,
                time_start=ts_start, time_end=ts_end,
            )
            await self.repo.insert_value(entry_id, value, mt, entry_date=d, metric_id=metric_id)

        row = await self.repo.get_with_binding(entry_id)
        return await _entry_to_out(self.repo, row, mt)

    async def update(self, entry_id: int, value) -> EntryOut:
        row = await self.repo.get_owned_with_binding(entry_id)
        raw_mt = await self.repo.get_metric_type(row["metric_id"]) or MetricType.bool
        mt = await self.repo.resolve_storage_type(row["metric_id"], raw_mt)
        await self.repo.update_value(entry_id, value, mt, entry_date=row["date"], metric_id=row["metric_id"])
        return await _entry_to_out(self.repo, row, mt)

    async def update_time(self, entry_id: int, time_str: str, date_str: str | None = None) -> EntryOut:
        """Update recorded_at for a free_checkpoint entry."""
        row = await self.repo.get_owned_with_binding(entry_id)
        if not row.get("is_free_checkpoint"):
            raise InvalidOperationError("Can only update time for free checkpoint entries")

        d = date_type.fromisoformat(date_str) if date_str else row["date"]
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        new_time = datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)

        await self.repo.update_recorded_at(entry_id, new_time)
        updated_row = await self.repo.get_with_binding(entry_id)
        raw_mt = await self.repo.get_metric_type(row["metric_id"]) or MetricType.bool
        mt = await self.repo.resolve_storage_type(row["metric_id"], raw_mt)
        return await _entry_to_out(self.repo, updated_row, mt)

    async def update_time_range(self, entry_id: int, time_start: str, time_end: str) -> EntryOut:
        """Update time_start/time_end for a free_interval entry."""
        row = await self.repo.get_owned_with_binding(entry_id)
        if not row.get("is_free_interval"):
            raise InvalidOperationError("Can only update time range for free interval entries")

        ts_start = _parse_time_str(time_start)
        ts_end = _parse_time_str(time_end)
        if ts_end <= ts_start:
            raise InvalidOperationError("time_end must be after time_start")

        d = row["date"]
        metric_id = row["metric_id"]
        if await self.repo.check_time_overlap(metric_id, d, ts_start, ts_end, exclude_entry_id=entry_id):
            raise ConflictError("Time range overlaps with an existing entry")

        await self.repo.conn.execute(
            "UPDATE entries SET time_start = $1, time_end = $2 WHERE id = $3 AND user_id = $4",
            ts_start, ts_end, entry_id, self.repo.user_id,
        )
        updated_row = await self.repo.get_with_binding(entry_id)
        raw_mt = await self.repo.get_metric_type(metric_id) or MetricType.bool
        mt = await self.repo.resolve_storage_type(metric_id, raw_mt)
        return await _entry_to_out(self.repo, updated_row, mt)

    async def delete(self, entry_id: int) -> None:
        await self.repo.delete(entry_id)
