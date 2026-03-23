from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db
from app.auth import get_current_user
from app.schemas import NoteCreate, NoteUpdate, NoteOut
from app.repositories.notes_repository import NotesRepository

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _row_to_out(row) -> NoteOut:
    return NoteOut(
        id=row["id"],
        metric_id=row["metric_id"],
        date=str(row["date"]),
        text=row["text"],
        created_at=str(row["created_at"]),
    )


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(
    data: NoteCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = NotesRepository(db, current_user["id"])
    metric = await repo.get_metric_type(data.metric_id)
    if metric["type"] != "text":
        raise HTTPException(400, "Only text metrics support notes")

    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Note text cannot be empty")

    d = date_type.fromisoformat(data.date)
    row = await repo.create(data.metric_id, d, text)
    return _row_to_out(row)


@router.put("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: int,
    data: NoteUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = NotesRepository(db, current_user["id"])
    await repo.get_by_id(note_id)

    text = data.text.strip()
    if not text:
        raise HTTPException(400, "Note text cannot be empty")

    updated = await repo.update_text(note_id, text)
    return _row_to_out(updated)


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = NotesRepository(db, current_user["id"])
    await repo.get_by_id(note_id)
    await repo.delete(note_id)


@router.get("", response_model=list[NoteOut])
async def list_notes(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = NotesRepository(db, current_user["id"])
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    rows = await repo.list_by_metric_and_period(metric_id, start_d, end_d)
    return [_row_to_out(r) for r in rows]
