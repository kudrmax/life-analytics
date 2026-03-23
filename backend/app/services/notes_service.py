"""Service layer for notes — business logic between router and repository."""

from datetime import date as date_type

from app.domain.exceptions import InvalidOperationError
from app.repositories.notes_repository import NotesRepository
from app.schemas import NoteOut


def _row_to_out(row) -> NoteOut:
    return NoteOut(
        id=row["id"],
        metric_id=row["metric_id"],
        date=str(row["date"]),
        text=row["text"],
        created_at=str(row["created_at"]),
    )


class NotesService:
    def __init__(self, repo: NotesRepository) -> None:
        self.repo = repo

    async def create(self, metric_id: int, date_str: str, text: str) -> NoteOut:
        """Create a note for a text metric."""
        metric = await self.repo.get_metric_type(metric_id)
        if metric["type"] != "text":
            raise InvalidOperationError("Only text metrics support notes")

        text = text.strip()
        if not text:
            raise InvalidOperationError("Note text cannot be empty")

        d = date_type.fromisoformat(date_str)
        row = await self.repo.create(metric_id, d, text)
        return _row_to_out(row)

    async def update(self, note_id: int, text: str) -> NoteOut:
        """Update note text."""
        await self.repo.get_by_id(note_id)
        text = text.strip()
        if not text:
            raise InvalidOperationError("Note text cannot be empty")
        updated = await self.repo.update_text(note_id, text)
        return _row_to_out(updated)

    async def delete(self, note_id: int) -> None:
        await self.repo.get_by_id(note_id)
        await self.repo.delete(note_id)

    async def list_by_period(
        self, metric_id: int, start: str, end: str,
    ) -> list[NoteOut]:
        start_d = date_type.fromisoformat(start)
        end_d = date_type.fromisoformat(end)
        rows = await self.repo.list_by_metric_and_period(metric_id, start_d, end_d)
        return [_row_to_out(r) for r in rows]
