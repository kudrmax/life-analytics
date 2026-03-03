from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.schemas import EntryCreate, EntryUpdate, EntryOut
from app.auth import get_current_user
from app.metric_helpers import get_entry_value, insert_value, update_value, get_metric_type

router = APIRouter(prefix="/api/entries", tags=["entries"])


async def _entry_to_out(conn, entry_row, metric_type: str = "bool") -> EntryOut:
    value = await get_entry_value(conn, entry_row["id"], metric_type)
    default = False if metric_type == "bool" else None
    return EntryOut(
        id=entry_row["id"],
        metric_id=entry_row["metric_id"],
        date=str(entry_row["date"]),
        recorded_at=str(entry_row["recorded_at"]),
        value=value if value is not None else default,
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

    # Build metric_id → type lookup
    metric_ids = list({r["metric_id"] for r in rows})
    type_lookup = {}
    if metric_ids:
        type_rows = await db.fetch(
            "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
            metric_ids, current_user["id"],
        )
        type_lookup = {r["id"]: r["type"] for r in type_rows}

    return [await _entry_to_out(db, r, type_lookup.get(r["metric_id"], "bool")) for r in rows]


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

    mt = metric["type"]
    async with db.transaction():
        entry_id = await db.fetchval(
            "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
            data.metric_id, current_user["id"], d,
        )
        await insert_value(db, entry_id, data.value, mt, entry_date=d, metric_id=data.metric_id)

    row = await db.fetchrow("SELECT * FROM entries WHERE id = $1", entry_id)
    return await _entry_to_out(db, row, mt)


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

    mt = await get_metric_type(db, row["metric_id"], current_user["id"]) or "bool"
    await update_value(db, entry_id, data.value, mt, entry_date=row["date"], metric_id=row["metric_id"])

    return await _entry_to_out(db, row, mt)


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
