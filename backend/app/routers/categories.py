from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import CategoryCreate, CategoryUpdate, CategoryOut
from app.repositories.categories_repository import CategoriesRepository

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = CategoriesRepository(db, current_user["id"])
    rows = await repo.get_all()
    # Build tree: top-level with children
    by_id = {r["id"]: {**dict(r), "children": []} for r in rows}
    tree = []
    for r in rows:
        node = by_id[r["id"]]
        if r["parent_id"] is None:
            tree.append(node)
        else:
            parent = by_id.get(r["parent_id"])
            if parent:
                parent["children"].append(node)
    return tree


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(
    data: CategoryCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = CategoriesRepository(db, current_user["id"])
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "name is required")

    if data.parent_id is not None:
        parent = await repo.get_parent(data.parent_id)
        if parent["parent_id"] is not None:
            raise HTTPException(400, "Maximum depth is 2 levels (category > subcategory)")

    sort_order = await repo.get_next_sort_order()
    cat_id = await repo.create(name, data.parent_id, sort_order)
    return CategoryOut(id=cat_id, name=name, parent_id=data.parent_id, sort_order=sort_order)


@router.patch("/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: int,
    data: CategoryUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = CategoriesRepository(db, current_user["id"])
    await repo.get_by_id(cat_id)

    if data.parent_id is not None:
        if data.parent_id == cat_id:
            raise HTTPException(400, "Category cannot be its own parent")
        parent = await repo.get_parent(data.parent_id)
        if parent["parent_id"] is not None:
            raise HTTPException(400, "Maximum depth is 2 levels")

    updates, params = [], []
    idx = 1
    if data.name is not None:
        updates.append(f"name = ${idx}")
        params.append(data.name.strip())
        idx += 1
    if data.parent_id is not None:
        updates.append(f"parent_id = ${idx}")
        params.append(data.parent_id)
        idx += 1
    if not updates:
        raise HTTPException(400, "Nothing to update")

    updated = await repo.update(cat_id, updates, params)
    return CategoryOut(**dict(updated))


@router.delete("/{cat_id}", status_code=204)
async def delete_category(
    cat_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = CategoriesRepository(db, current_user["id"])
    await repo.delete(cat_id)


@router.post("/reorder")
async def reorder_categories(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = CategoriesRepository(db, current_user["id"])
    await repo.reorder(items)
    return {"ok": True}
