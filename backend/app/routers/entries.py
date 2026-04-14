from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.schemas import EntryCreate, EntryTimeUpdate, EntryTimeRangeUpdate, EntryUpdate, EntryOut
from app.auth import get_current_user
from app.repositories.entry_repository import EntryRepository
from app.services.entries_service import EntriesService

router = APIRouter(prefix="/api/entries", tags=["entries"])


def _service(db, user) -> EntriesService:
    return EntriesService(EntryRepository(db, user["id"]))


@router.get("", response_model=list[EntryOut])
async def list_entries(
    date: str = Query(..., description="YYYY-MM-DD"),
    metric_id: int | None = None,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _service(db, current_user).list_by_date(date, metric_id)


@router.post("", response_model=EntryOut, status_code=201)
async def create_entry(data: EntryCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(
        data.metric_id, data.date, data.value,
        data.checkpoint_id, data.interval_id,
        data.time_start, data.time_end,
    )


@router.put("/{entry_id}", response_model=EntryOut)
async def update_entry(entry_id: int, data: EntryUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(entry_id, data.value)


@router.patch("/{entry_id}/time", response_model=EntryOut)
async def update_entry_time(
    entry_id: int, data: EntryTimeUpdate,
    db=Depends(get_db), current_user: dict = Depends(get_current_user),
):
    return await _service(db, current_user).update_time(entry_id, data.recorded_at)


@router.patch("/{entry_id}/time-range", response_model=EntryOut)
async def update_entry_time_range(
    entry_id: int, data: EntryTimeRangeUpdate,
    db=Depends(get_db), current_user: dict = Depends(get_current_user),
):
    return await _service(db, current_user).update_time_range(entry_id, data.time_start, data.time_end)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(entry_id)
