"""Service layer for checkpoints — business logic between router and repository."""

from app.domain.exceptions import InvalidOperationError, ConflictError
from app.repositories.checkpoints_repository import CheckpointsRepository
from app.repositories.layout_repository import LayoutRepository
from app.schemas import CheckpointOut, CheckpointSettingsOut


class CheckpointsService:
    def __init__(self, repo: CheckpointsRepository) -> None:
        self.repo = repo
        self._layout = LayoutRepository(repo.conn, repo.user_id)

    async def list_all(self) -> list[CheckpointSettingsOut]:
        rows = await self.repo.get_all_with_usage()
        return [CheckpointSettingsOut(**dict(r)) for r in rows]

    async def create(self, label: str, description: str | None = None) -> CheckpointOut:
        label = label.strip()
        if not label:
            raise InvalidOperationError("label is required")
        description = description.strip() if description else None
        sort_order = await self.repo.get_next_sort_order()
        checkpoint_id = await self.repo.create(label, sort_order, description)
        await self.repo.recalculate_intervals()
        # Add checkpoint block + new interval blocks to layout
        await self._layout.add_block("checkpoint", checkpoint_id)
        for iv in await self.repo.get_active_intervals():
            await self._layout.add_block("interval", iv["id"])
        return CheckpointSettingsOut(id=checkpoint_id, label=label, sort_order=sort_order, description=description, usage_count=0, usage_metric_names=[])

    async def update(self, checkpoint_id: int, label: str | None, description: str | None = None) -> CheckpointSettingsOut:
        await self.repo.get_by_id(checkpoint_id)
        if label is not None:
            label = label.strip()
            if not label:
                raise InvalidOperationError("label is required")
            await self.repo.update_label(checkpoint_id, label)
        if description is not None:
            await self.repo.update_description(checkpoint_id, description.strip() or None)
        updated = await self.repo.get_updated(checkpoint_id)
        usage = await self.repo.get_enabled_usage_count(checkpoint_id)
        names = await self.repo.get_enabled_metric_names(checkpoint_id) if usage > 0 else []
        return CheckpointSettingsOut(**dict(updated), usage_count=usage, usage_metric_names=names)

    async def delete(self, checkpoint_id: int) -> None:
        await self.repo.get_by_id(checkpoint_id)
        usage_count = await self.repo.get_enabled_usage_count(checkpoint_id)
        if usage_count > 0:
            names = await self.repo.get_enabled_metric_names(checkpoint_id)
            raise ConflictError(
                f"Чекпоинт используется в метриках: {', '.join(names)}. Сначала отвяжите его.",
            )
        # Remove checkpoint block + stale interval blocks from layout
        await self._layout.remove_block("checkpoint", checkpoint_id)
        # Get intervals before delete to know which to remove
        old_intervals = {iv["id"] for iv in await self.repo.get_active_intervals()}
        await self.repo.delete_disabled_metric_checkpoints(checkpoint_id)
        await self.repo.delete(checkpoint_id)
        await self.repo.recalculate_intervals()
        # Remove interval blocks that no longer exist
        new_intervals = {iv["id"] for iv in await self.repo.get_active_intervals()}
        for removed_iv_id in old_intervals - new_intervals:
            await self._layout.remove_block("interval", removed_iv_id)
        # Add new intervals that appeared
        for new_iv_id in new_intervals - old_intervals:
            await self._layout.add_block("interval", new_iv_id)

    async def merge(self, source_id: int, target_id: int) -> dict:
        if source_id == target_id:
            raise InvalidOperationError("Нельзя объединить чекпоинт сам с собой")
        await self.repo.get_by_id(source_id)
        await self.repo.get_by_id(target_id)
        stats = await self.repo.merge(source_id, target_id)
        return {"ok": True, **stats}

    async def get_intervals(self) -> list[dict]:
        rows = await self.repo.get_active_intervals()
        return [dict(r) for r in rows]

    async def reorder(self, items: list[dict]) -> None:
        await self.repo.reorder(items)
