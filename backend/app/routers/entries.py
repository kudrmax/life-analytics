from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.schemas import EntryCreate, EntryUpdate, EntryOut
from app.auth import get_current_user
from app.metric_helpers import get_entry_value, insert_value, update_value

router = APIRouter(prefix="/api/entries", tags=["entries"])


async def _entry_to_out(conn, entry_row) -> EntryOut:
    value = await get_entry_value(conn, entry_row["id"])
    return EntryOut(
        id=entry_row["id"],
        metric_id=entry_row["metric_id"],
        date=str(entry_row["date"]),
        recorded_at=str(entry_row["recorded_at"]),
        value=value if value is not None else False,
    )


@router.get("", response_model=list[EntryOut])
async def list_entries(
    date: str = Query(..., description="YYYY-MM-DD"),
    metric_id: int | None = None,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    d = date_type.fromisoformat(date)
    if metric_id:
        rows = await db.fetch(
            "SELECT * FROM entries WHERE date = $1 AND metric_id = $2 AND user_id = $3",
            d, metric_id, current_user["id"],
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM entries WHERE date = $1 AND user_id = $2 ORDER BY metric_id",
            d, current_user["id"],
        )

    return [await _entry_to_out(db, r) for r in rows]


@router.post("", response_model=EntryOut, status_code=201)
async def create_entry(
    data: EntryCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    metric = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        data.metric_id, current_user["id"],
    )
    if not metric:
        raise HTTPException(404, "Metric not found")

    d = date_type.fromisoformat(data.date)
    existing = await db.fetchval(
        "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3",
        data.metric_id, current_user["id"], d,
    )
    if existing:
        raise HTTPException(409, "Entry already exists for this metric/date. Use PUT to update.")

    async with db.transaction():
        entry_id = await db.fetchval(
            "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
            data.metric_id, current_user["id"], d,
        )
        await insert_value(db, entry_id, data.value)

    row = await db.fetchrow("SELECT * FROM entries WHERE id = $1", entry_id)
    return await _entry_to_out(db, row)


@router.put("/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: int,
    data: EntryUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM entries WHERE id = $1 AND user_id = $2",
        entry_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Entry not found")

    await update_value(db, entry_id, data.value)

    return await _entry_to_out(db, row)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchval(
        "SELECT id FROM entries WHERE id = $1 AND user_id = $2",
        entry_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Entry not found")
    await db.execute(
        "DELETE FROM entries WHERE id = $1 AND user_id = $2",
        entry_id, current_user["id"],
    )
