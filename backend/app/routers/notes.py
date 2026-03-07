from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.auth import get_current_user
from app.schemas import NoteCreate, NoteUpdate, NoteOut

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(
    data: NoteCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    metric = await db.fetchrow(
        "SELECT id, type FROM metric_definitions WHERE id = $1 AND user_id = $2",
        data.metric_id, current_user["id"],
    )
    if not metric:
        raise HTTPException(404, "Metric not found")
    if metric["type"] != "text":
        raise HTTPException(400, "Only text metrics support notes")

    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Note text cannot be empty")

    d = date_type.fromisoformat(data.date)
    row = await db.fetchrow(
        """INSERT INTO notes (metric_id, user_id, date, text)
           VALUES ($1, $2, $3, $4)
           RETURNING id, metric_id, date, text, created_at""",
        data.metric_id, current_user["id"], d, text,
    )
    return NoteOut(
        id=row["id"],
        metric_id=row["metric_id"],
        date=str(row["date"]),
        text=row["text"],
        created_at=str(row["created_at"]),
    )


@router.put("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: int,
    data: NoteUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM notes WHERE id = $1 AND user_id = $2",
        note_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Note not found")

    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Note text cannot be empty")

    updated = await db.fetchrow(
        "UPDATE notes SET text = $1 WHERE id = $2 RETURNING id, metric_id, date, text, created_at",
        text, note_id,
    )
    return NoteOut(
        id=updated["id"],
        metric_id=updated["metric_id"],
        date=str(updated["date"]),
        text=updated["text"],
        created_at=str(updated["created_at"]),
    )


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM notes WHERE id = $1 AND user_id = $2",
        note_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Note not found")
    await db.execute("DELETE FROM notes WHERE id = $1", note_id)


@router.get("", response_model=list[NoteOut])
async def list_notes(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    rows = await db.fetch(
        """SELECT id, metric_id, date, text, created_at
           FROM notes
           WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
           ORDER BY date DESC, created_at DESC""",
        metric_id, current_user["id"], start_d, end_d,
    )
    return [
        NoteOut(
            id=r["id"],
            metric_id=r["metric_id"],
            date=str(r["date"]),
            text=r["text"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]
