import json

from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from app.database import get_db
from app.schemas import MetricConfigCreate, MetricConfigUpdate, MetricConfigOut
from app.auth import get_current_user

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def row_to_metric(row: aiosqlite.Row) -> MetricConfigOut:
    return MetricConfigOut(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        type=row["type"],
        frequency=row["frequency"],
        source=row["source"],
        config=json.loads(row["config_json"]),
        enabled=bool(row["enabled"]),
        sort_order=row["sort_order"],
    )


@router.get("", response_model=list[MetricConfigOut])
async def list_metrics(enabled_only: bool = False, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    query = "SELECT * FROM metric_configs WHERE user_id = ?"
    params = [current_user["id"]]
    if enabled_only:
        query += " AND enabled = 1"
    query += " ORDER BY sort_order, rowid"
    rows = await db.execute(query, params)
    return [row_to_metric(r) for r in await rows.fetchall()]


@router.get("/{metric_id}", response_model=MetricConfigOut)
async def get_metric(metric_id: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    row = await db.execute(
        "SELECT * FROM metric_configs WHERE id = ? AND user_id = ?", (metric_id, current_user["id"])
    )
    row = await row.fetchone()
    if not row:
        raise HTTPException(404, "Metric not found")
    return row_to_metric(row)


@router.post("", response_model=MetricConfigOut, status_code=201)
async def create_metric(data: MetricConfigCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    existing = await db.execute(
        "SELECT id FROM metric_configs WHERE id = ? AND user_id = ?", (data.id, current_user["id"])
    )
    if await existing.fetchone():
        raise HTTPException(409, "Metric with this id already exists")

    await db.execute(
        """INSERT INTO metric_configs (id, name, category, type, frequency, source, config_json, enabled, sort_order, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.id,
            data.name,
            data.category,
            data.type,
            data.frequency,
            data.source,
            json.dumps(data.config),
            int(data.enabled),
            data.sort_order,
            current_user["id"],
        ),
    )
    await db.commit()
    return await get_metric(data.id, db, current_user)


@router.patch("/{metric_id}", response_model=MetricConfigOut)
async def update_metric(metric_id: str, data: MetricConfigUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    existing = await get_metric(metric_id, db, current_user)

    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.category is not None:
        updates["category"] = data.category
    if data.type is not None:
        updates["type"] = data.type
    if data.frequency is not None:
        updates["frequency"] = data.frequency
    if data.source is not None:
        updates["source"] = data.source
    if data.config is not None:
        updates["config_json"] = json.dumps(data.config)
    if data.enabled is not None:
        updates["enabled"] = int(data.enabled)
    if data.sort_order is not None:
        updates["sort_order"] = data.sort_order

    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [metric_id, current_user["id"]]
        await db.execute(
            f"UPDATE metric_configs SET {set_clause} WHERE id = ? AND user_id = ?", values
        )
        await db.commit()

    return await get_metric(metric_id, db, current_user)


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(metric_id: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await get_metric(metric_id, db, current_user)  # 404 if not found
    await db.execute("DELETE FROM metric_configs WHERE id = ? AND user_id = ?", (metric_id, current_user["id"]))
    await db.commit()
