from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.schemas import MetricDefinitionCreate, MetricDefinitionUpdate, MetricDefinitionOut
from app.auth import get_current_user
from app.metric_helpers import build_metric_out

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=list[MetricDefinitionOut])
async def list_metrics(
    enabled_only: bool = False,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query = "SELECT * FROM metric_definitions WHERE user_id = $1"
    params = [current_user["id"]]
    if enabled_only:
        query += " AND enabled = TRUE"
    query += " ORDER BY sort_order, id"
    rows = await db.fetch(query, *params)
    return [await build_metric_out(r) for r in rows]


@router.get("/{metric_id}", response_model=MetricDefinitionOut)
async def get_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")
    return await build_metric_out(row)


@router.post("", response_model=MetricDefinitionOut, status_code=201)
async def create_metric(
    data: MetricDefinitionCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    existing = await db.fetchval(
        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
        data.slug, current_user["id"],
    )
    if existing:
        raise HTTPException(409, "Metric with this slug already exists")

    metric_id = await db.fetchval(
        """INSERT INTO metric_definitions
           (user_id, slug, name, category, type, enabled, sort_order)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING id""",
        current_user["id"],
        data.slug,
        data.name,
        data.category,
        data.type.value,
        data.enabled,
        data.sort_order,
    )

    return await get_metric(metric_id, db, current_user)


@router.patch("/{metric_id}", response_model=MetricDefinitionOut)
async def update_metric(
    metric_id: int,
    data: MetricDefinitionUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")

    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.category is not None:
        updates["category"] = data.category
    if data.enabled is not None:
        updates["enabled"] = data.enabled
    if data.sort_order is not None:
        updates["sort_order"] = data.sort_order

    if updates:
        set_parts = []
        values = []
        for i, (k, v) in enumerate(updates.items(), start=1):
            set_parts.append(f"{k} = ${i}")
            values.append(v)
        values.append(metric_id)
        values.append(current_user["id"])
        set_clause = ", ".join(set_parts)
        await db.execute(
            f"UPDATE metric_definitions SET {set_clause} WHERE id = ${len(values) - 1} AND user_id = ${len(values)}",
            *values,
        )

    return await get_metric(metric_id, db, current_user)


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Metric not found")
    await db.execute(
        "DELETE FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
