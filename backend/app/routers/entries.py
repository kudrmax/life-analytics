from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.schemas import EntryCreate, EntryUpdate, EntryOut
from app.auth import get_current_user
from app.metric_helpers import (
    build_value_dict, insert_value, update_value,
    get_metric_type, VALUE_TABLE_MAP,
)

router = APIRouter(prefix="/api/entries", tags=["entries"])


async def _entry_to_out(conn, entry_row, metric_type: str) -> EntryOut:
    table = VALUE_TABLE_MAP[metric_type]
    val_row = await conn.fetchrow(f"SELECT * FROM {table} WHERE entry_id = $1", entry_row["id"])
    value = build_value_dict(metric_type, val_row)

    return EntryOut(
        id=entry_row["id"],
        metric_id=entry_row["metric_id"],
        date=str(entry_row["date"]),
        measurement_number=entry_row["measurement_number"],
        recorded_at=str(entry_row["recorded_at"]),
        value=value,
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
            "SELECT * FROM entries WHERE date = $1 AND metric_id = $2 AND user_id = $3 ORDER BY measurement_number",
            d, metric_id, current_user["id"],
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM entries WHERE date = $1 AND user_id = $2 ORDER BY metric_id, measurement_number",
            d, current_user["id"],
        )

    result = []
    # Cache metric types
    type_cache = {}
    for r in rows:
        mid = r["metric_id"]
        if mid not in type_cache:
            type_cache[mid] = await get_metric_type(db, mid, current_user["id"])
        mt = type_cache[mid]
        if mt:
            result.append(await _entry_to_out(db, r, mt))
    return result


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

    metric_type = metric["type"]

    # Check for existing entry (UNIQUE constraint handles this, but give better error)
    d = date_type.fromisoformat(data.date)
    existing = await db.fetchval(
        """SELECT id FROM entries
           WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND measurement_number = $4""",
        data.metric_id, current_user["id"], d, data.measurement_number,
    )
    if existing:
        raise HTTPException(
            409, "Entry already exists for this metric/date/measurement_number. Use PUT to update."
        )

    async with db.transaction():
        entry_id = await db.fetchval(
            """INSERT INTO entries (metric_id, user_id, date, measurement_number)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            data.metric_id, current_user["id"], d, data.measurement_number,
        )
        await insert_value(db, entry_id, metric_type, data.value)

    row = await db.fetchrow("SELECT * FROM entries WHERE id = $1", entry_id)
    return await _entry_to_out(db, row, metric_type)


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

    metric_type = await get_metric_type(db, row["metric_id"], current_user["id"])
    if not metric_type:
        raise HTTPException(404, "Metric not found")

    await update_value(db, entry_id, metric_type, data.value)

    return await _entry_to_out(db, row, metric_type)


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
