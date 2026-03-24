from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.auth import get_current_user
from app.schemas import NoteCreate, NoteUpdate, NoteOut
from app.repositories.notes_repository import NotesRepository
from app.services.notes_service import NotesService

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _service(db, user) -> NotesService:
    return NotesService(NotesRepository(db, user["id"]))


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(data: NoteCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(data.metric_id, data.date, data.text)


@router.put("/{note_id}", response_model=NoteOut)
async def update_note(note_id: int, data: NoteUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(note_id, data.text)


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(note_id)


@router.get("", response_model=list[NoteOut])
async def list_notes(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _service(db, current_user).list_by_period(metric_id, start, end)
