"""Service layer for measurement slots — business logic between router and repository."""

from app.domain.exceptions import InvalidOperationError, ConflictError
from app.repositories.slots_repository import SlotsRepository
from app.schemas import SlotOut


class SlotsService:
    def __init__(self, repo: SlotsRepository) -> None:
        self.repo = repo

    async def list_all(self) -> list[SlotOut]:
        rows = await self.repo.get_all_with_usage()
        return [SlotOut(**dict(r)) for r in rows]

    async def create(self, label: str) -> SlotOut:
        label = label.strip()
        if not label:
            raise InvalidOperationError("label is required")
        sort_order = await self.repo.get_next_sort_order()
        slot_id = await self.repo.create(label, sort_order)
        return SlotOut(id=slot_id, label=label, sort_order=sort_order)

    async def update(self, slot_id: int, label: str | None) -> SlotOut:
        await self.repo.get_by_id(slot_id)
        if label is not None:
            label = label.strip()
            if not label:
                raise InvalidOperationError("label is required")
            await self.repo.update_label(slot_id, label)
        updated = await self.repo.get_updated(slot_id)
        return SlotOut(**dict(updated))

    async def delete(self, slot_id: int) -> None:
        await self.repo.get_by_id(slot_id)
        usage_count = await self.repo.get_enabled_usage_count(slot_id)
        if usage_count > 0:
            names = await self.repo.get_enabled_metric_names(slot_id)
            raise ConflictError(
                f"Время замера используется в метриках: {', '.join(names)}. Сначала отвяжите его.",
            )
        await self.repo.delete_disabled_metric_slots(slot_id)
        await self.repo.delete(slot_id)

    async def merge(self, source_id: int, target_id: int) -> dict:
        if source_id == target_id:
            raise InvalidOperationError("Нельзя объединить слот сам с собой")
        await self.repo.get_by_id(source_id)
        await self.repo.get_by_id(target_id)
        stats = await self.repo.merge(source_id, target_id)
        return {"ok": True, **stats}

    async def reorder(self, items: list[dict]) -> None:
        await self.repo.reorder(items)
