"""Service layer for categories — business logic between router and repository."""

from app.domain.exceptions import InvalidOperationError
from app.repositories.categories_repository import CategoriesRepository
from app.schemas import CategoryOut


class CategoriesService:
    def __init__(self, repo: CategoriesRepository) -> None:
        self.repo = repo

    async def list_tree(self) -> list[dict]:
        """Get all categories as a tree (top-level with nested children)."""
        rows = await self.repo.get_all()
        by_id: dict[int, dict] = {r["id"]: {**dict(r), "children": []} for r in rows}
        tree: list[dict] = []
        for r in rows:
            node = by_id[r["id"]]
            if r["parent_id"] is None:
                tree.append(node)
            else:
                parent = by_id.get(r["parent_id"])
                if parent:
                    parent["children"].append(node)
        return tree

    async def create(self, name: str, parent_id: int | None) -> CategoryOut:
        """Create a category with validation."""
        name = name.strip()
        if not name:
            raise InvalidOperationError("name is required")

        if parent_id is not None:
            parent = await self.repo.get_parent(parent_id)
            if parent["parent_id"] is not None:
                raise InvalidOperationError("Maximum depth is 2 levels (category > subcategory)")

        sort_order = await self.repo.get_next_sort_order()
        cat_id = await self.repo.create(name, parent_id, sort_order)
        return CategoryOut(id=cat_id, name=name, parent_id=parent_id, sort_order=sort_order)

    async def update(self, cat_id: int, name: str | None, parent_id: int | None) -> CategoryOut:
        """Update a category with validation."""
        await self.repo.get_by_id(cat_id)

        if parent_id is not None:
            if parent_id == cat_id:
                raise InvalidOperationError("Category cannot be its own parent")
            parent = await self.repo.get_parent(parent_id)
            if parent["parent_id"] is not None:
                raise InvalidOperationError("Maximum depth is 2 levels")

        updates: list[str] = []
        params: list = []
        idx = 1
        if name is not None:
            updates.append(f"name = ${idx}")
            params.append(name.strip())
            idx += 1
        if parent_id is not None:
            updates.append(f"parent_id = ${idx}")
            params.append(parent_id)
            idx += 1
        if not updates:
            raise InvalidOperationError("Nothing to update")

        updated = await self.repo.update(cat_id, updates, params)
        return CategoryOut(**dict(updated))

    async def delete(self, cat_id: int) -> None:
        await self.repo.delete(cat_id)

    async def reorder(self, items: list[dict]) -> None:
        await self.repo.reorder(items)
