from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import CategoryCreate, CategoryUpdate, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        """SELECT id, name, parent_id, sort_order
           FROM categories
           WHERE user_id = $1
           ORDER BY sort_order, id""",
        current_user["id"],
    )
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
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "name is required")

    if data.parent_id is not None:
        parent = await db.fetchrow(
            "SELECT id, parent_id FROM categories WHERE id = $1 AND user_id = $2",
            data.parent_id, current_user["id"],
        )
        if not parent:
            raise HTTPException(404, "Parent category not found")
        if parent["parent_id"] is not None:
            raise HTTPException(400, "Maximum depth is 2 levels (category > subcategory)")

    max_order = await db.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) FROM categories WHERE user_id = $1",
        current_user["id"],
    )
    try:
        cat_id = await db.fetchval(
            """INSERT INTO categories (user_id, name, parent_id, sort_order)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            current_user["id"], name, data.parent_id, max_order + 1,
        )
    except Exception:
        raise HTTPException(409, "Category with this name already exists")
    return CategoryOut(id=cat_id, name=name, parent_id=data.parent_id, sort_order=max_order + 1)


@router.patch("/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: int,
    data: CategoryUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM categories WHERE id = $1 AND user_id = $2",
        cat_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Category not found")

    if data.parent_id is not None:
        if data.parent_id == cat_id:
            raise HTTPException(400, "Category cannot be its own parent")
        parent = await db.fetchrow(
            "SELECT id, parent_id FROM categories WHERE id = $1 AND user_id = $2",
            data.parent_id, current_user["id"],
        )
        if not parent:
            raise HTTPException(404, "Parent category not found")
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

    params.extend([cat_id, current_user["id"]])
    await db.execute(
        f"UPDATE categories SET {', '.join(updates)} WHERE id = ${idx} AND user_id = ${idx + 1}",
        *params,
    )
    updated = await db.fetchrow(
        "SELECT id, name, parent_id, sort_order FROM categories WHERE id = $1",
        cat_id,
    )
    return CategoryOut(**dict(updated))


@router.delete("/{cat_id}", status_code=204)
async def delete_category(
    cat_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        "DELETE FROM categories WHERE id = $1 AND user_id = $2",
        cat_id, current_user["id"],
    )
    if result == "DELETE 0":
        raise HTTPException(404, "Category not found")


@router.post("/reorder")
async def reorder_categories(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    async with db.transaction():
        for item in items:
            await db.execute(
                """UPDATE categories
                   SET sort_order = $1, parent_id = $2
                   WHERE id = $3 AND user_id = $4""",
                item["sort_order"], item.get("parent_id"),
                item["id"], current_user["id"],
            )
    return {"ok": True}
