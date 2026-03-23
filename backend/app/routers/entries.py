from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.schemas import EntryCreate, EntryUpdate, EntryOut
from app.auth import get_current_user
from app.repositories.entry_repository import EntryRepository

router = APIRouter(prefix="/api/entries", tags=["entries"])


async def _entry_to_out(repo: EntryRepository, entry_row, metric_type: str = "bool") -> EntryOut:
    value = await repo.get_entry_value(entry_row["id"], metric_type)
    default = False if metric_type == "bool" else None
    return EntryOut(
        id=entry_row["id"],
        metric_id=entry_row["metric_id"],
        date=str(entry_row["date"]),
        recorded_at=str(entry_row["recorded_at"]),
        value=value if value is not None else default,
        slot_id=entry_row["slot_id"],
        slot_label=entry_row.get("slot_label") or "",
    )


@router.get("", response_model=list[EntryOut])
async def list_entries(
    date: str = Query(..., description="YYYY-MM-DD"),
    metric_id: int | None = None,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = EntryRepository(db, current_user["id"])
    d = date_type.fromisoformat(date)
    rows = await repo.list_by_date(d, metric_id)

    # Build metric_id -> type lookup (resolve integration to actual storage type)
    metric_ids = list({r["metric_id"] for r in rows})
    type_lookup: dict[int, str] = {}
    if metric_ids:
        raw_types = await repo.get_metric_types(metric_ids)
        for mid, mtype in raw_types.items():
            type_lookup[mid] = await repo.resolve_storage_type(mid, mtype)

    return [await _entry_to_out(repo, r, type_lookup.get(r["metric_id"], "bool")) for r in rows]


@router.post("", response_model=EntryOut, status_code=201)
async def create_entry(
    data: EntryCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = EntryRepository(db, current_user["id"])
    metric = await repo.get_metric(data.metric_id)

    d = date_type.fromisoformat(data.date)

    if await repo.check_duplicate(data.metric_id, d, data.slot_id):
        raise HTTPException(409, "Entry already exists for this metric/date/slot. Use PUT to update.")

    mt = await repo.resolve_storage_type(data.metric_id, metric["type"])
    async with db.transaction():
        entry_id = await repo.create(data.metric_id, d, data.slot_id)
        await repo.insert_value(entry_id, data.value, mt, entry_date=d, metric_id=data.metric_id)

    row = await repo.get_with_slot(entry_id)
    return await _entry_to_out(repo, row, mt)


@router.put("/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: int,
    data: EntryUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = EntryRepository(db, current_user["id"])
    row = await repo.get_owned_with_slot(entry_id)

    raw_mt = await repo.get_metric_type(row["metric_id"]) or "bool"
    mt = await repo.resolve_storage_type(row["metric_id"], raw_mt)
    await repo.update_value(entry_id, data.value, mt, entry_date=row["date"], metric_id=row["metric_id"])

    return await _entry_to_out(repo, row, mt)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = EntryRepository(db, current_user["id"])
    await repo.delete(entry_id)
