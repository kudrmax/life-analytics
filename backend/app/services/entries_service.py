"""Service layer for entries — business logic between router and repository."""

from datetime import date as date_type, datetime, timezone

from app.domain.constants import FREE_CHECKPOINTS_SUPPORTED_TYPES
from app.domain.enums import IntervalBinding, MetricType
from app.domain.exceptions import ConflictError, EntityNotFoundError, InvalidOperationError
from app.repositories.entry_repository import EntryRepository
from app.schemas import EntryOut


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
    ) -> EntryOut:
        if checkpoint_id is not None and interval_id is not None:
            raise InvalidOperationError("Entry cannot have both checkpoint_id and interval_id")

        metric = await self.repo.get_metric(metric_id)
        d = date_type.fromisoformat(date_str)

        is_free_cp = metric.get("interval_binding") == IntervalBinding.FREE_CHECKPOINTS

        if is_free_cp:
            if metric["type"] not in FREE_CHECKPOINTS_SUPPORTED_TYPES:
                raise InvalidOperationError(f"Metric type '{metric['type']}' does not support free checkpoints")
            if checkpoint_id is not None or interval_id is not None:
                raise InvalidOperationError("Free checkpoint entries cannot have checkpoint_id or interval_id")

        if await self.repo.check_duplicate(metric_id, d, checkpoint_id, interval_id, is_free_checkpoint=is_free_cp):
            raise ConflictError("Entry already exists for this metric/date/checkpoint/interval. Use PUT to update.")

        mt = await self.repo.resolve_storage_type(metric_id, metric["type"])
        async with self.repo.transaction():
            entry_id = await self.repo.create(metric_id, d, checkpoint_id, interval_id, is_free_checkpoint=is_free_cp)
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

    async def delete(self, entry_id: int) -> None:
        await self.repo.delete(entry_id)
