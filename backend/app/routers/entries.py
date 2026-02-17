import json
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from app.database import get_db
from app.schemas import EntryCreate, EntryUpdate, EntryOut

router = APIRouter(prefix="/api/entries", tags=["entries"])


def row_to_entry(row: aiosqlite.Row) -> EntryOut:
    return EntryOut(
        id=row["id"],
        metric_id=row["metric_id"],
        date=row["date"],
        timestamp=row["timestamp"],
        value=json.loads(row["value_json"]),
    )


@router.get("", response_model=list[EntryOut])
async def list_entries(
    date: str = Query(..., description="YYYY-MM-DD"),
    metric_id: str | None = None,
    db=Depends(get_db),
):
    if metric_id:
        rows = await db.execute(
            "SELECT * FROM entries WHERE date = ? AND metric_id = ? ORDER BY timestamp",
            (date, metric_id),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM entries WHERE date = ? ORDER BY metric_id, timestamp",
            (date,),
        )
    return [row_to_entry(r) for r in await rows.fetchall()]


@router.post("", response_model=EntryOut, status_code=201)
async def create_entry(data: EntryCreate, db=Depends(get_db)):
    # Check metric exists
    metric = await db.execute(
        "SELECT * FROM metric_configs WHERE id = ?", (data.metric_id,)
    )
    metric = await metric.fetchone()
    if not metric:
        raise HTTPException(404, "Metric not found")

    # For daily metrics, check if entry already exists
    if metric["frequency"] == "daily":
        existing = await db.execute(
            "SELECT id FROM entries WHERE metric_id = ? AND date = ?",
            (data.metric_id, data.date),
        )
        if await existing.fetchone():
            raise HTTPException(
                409, "Daily metric already has an entry for this date. Use PUT to update."
            )

    ts = data.timestamp or datetime.now().isoformat()

    cursor = await db.execute(
        "INSERT INTO entries (metric_id, date, timestamp, value_json) VALUES (?, ?, ?, ?)",
        (data.metric_id, data.date, ts, json.dumps(data.value)),
    )
    await db.commit()

    row = await db.execute("SELECT * FROM entries WHERE id = ?", (cursor.lastrowid,))
    return row_to_entry(await row.fetchone())


@router.put("/{entry_id}", response_model=EntryOut)
async def update_entry(entry_id: int, data: EntryUpdate, db=Depends(get_db)):
    row = await db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
    row = await row.fetchone()
    if not row:
        raise HTTPException(404, "Entry not found")

    await db.execute(
        "UPDATE entries SET value_json = ? WHERE id = ?",
        (json.dumps(data.value), entry_id),
    )
    await db.commit()

    row = await db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
    return row_to_entry(await row.fetchone())


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, db=Depends(get_db)):
    row = await db.execute("SELECT id FROM entries WHERE id = ?", (entry_id,))
    if not await row.fetchone():
        raise HTTPException(404, "Entry not found")
    await db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    await db.commit()
