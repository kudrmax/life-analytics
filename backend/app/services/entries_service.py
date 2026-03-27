"""Service layer for entries — business logic between router and repository."""

from datetime import date as date_type

from app.domain.enums import MetricType
from app.domain.exceptions import ConflictError, InvalidOperationError
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

        if await self.repo.check_duplicate(metric_id, d, checkpoint_id, interval_id):
            raise ConflictError("Entry already exists for this metric/date/checkpoint/interval. Use PUT to update.")

        mt = await self.repo.resolve_storage_type(metric_id, metric["type"])
        async with self.repo.transaction():
            entry_id = await self.repo.create(metric_id, d, checkpoint_id, interval_id)
            await self.repo.insert_value(entry_id, value, mt, entry_date=d, metric_id=metric_id)

        row = await self.repo.get_with_binding(entry_id)
        return await _entry_to_out(self.repo, row, mt)

    async def update(self, entry_id: int, value) -> EntryOut:
        row = await self.repo.get_owned_with_binding(entry_id)
        raw_mt = await self.repo.get_metric_type(row["metric_id"]) or MetricType.bool
        mt = await self.repo.resolve_storage_type(row["metric_id"], raw_mt)
        await self.repo.update_value(entry_id, value, mt, entry_date=row["date"], metric_id=row["metric_id"])
        return await _entry_to_out(self.repo, row, mt)

    async def delete(self, entry_id: int) -> None:
        await self.repo.delete(entry_id)
