from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import SlotCreate, SlotUpdate, SlotOut

router = APIRouter(prefix="/api/slots", tags=["slots"])


@router.get("", response_model=list[SlotOut])
async def list_slots(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        """SELECT ms.id, ms.label, ms.sort_order,
                  COALESCE(cnt.c, 0) AS usage_count,
                  COALESCE(cnt.names, ARRAY[]::text[]) AS usage_metric_names
           FROM measurement_slots ms
           LEFT JOIN (
               SELECT msl.slot_id, COUNT(*) c,
                      array_agg(DISTINCT md.name ORDER BY md.name) AS names
               FROM metric_slots msl
               JOIN metric_definitions md ON md.id = msl.metric_id
               WHERE msl.enabled = TRUE
               GROUP BY msl.slot_id
           ) cnt ON cnt.slot_id = ms.id
           WHERE ms.user_id = $1
           ORDER BY ms.sort_order, ms.id""",
        current_user["id"],
    )
    return [SlotOut(**dict(r)) for r in rows]


@router.post("", response_model=SlotOut, status_code=201)
async def create_slot(
    data: SlotCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    label = data.label.strip()
    if not label:
        raise HTTPException(400, "label is required")

    max_order = await db.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) FROM measurement_slots WHERE user_id = $1",
        current_user["id"],
    )
    try:
        slot_id = await db.fetchval(
            """INSERT INTO measurement_slots (user_id, label, sort_order)
               VALUES ($1, $2, $3) RETURNING id""",
            current_user["id"], label, max_order + 1,
        )
    except Exception:
        raise HTTPException(409, "Время замера с таким названием уже существует")
    return SlotOut(id=slot_id, label=label, sort_order=max_order + 1)


@router.patch("/{slot_id}", response_model=SlotOut)
async def update_slot(
    slot_id: int,
    data: SlotUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT * FROM measurement_slots WHERE id = $1 AND user_id = $2",
        slot_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Время замера не найдено")

    if data.label is not None:
        label = data.label.strip()
        if not label:
            raise HTTPException(400, "label is required")
        try:
            await db.execute(
                "UPDATE measurement_slots SET label = $1 WHERE id = $2 AND user_id = $3",
                label, slot_id, current_user["id"],
            )
        except Exception:
            raise HTTPException(409, "Время замера с таким названием уже существует")

    updated = await db.fetchrow(
        "SELECT id, label, sort_order FROM measurement_slots WHERE id = $1",
        slot_id,
    )
    return SlotOut(**dict(updated))


@router.delete("/{slot_id}", status_code=204)
async def delete_slot(
    slot_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM measurement_slots WHERE id = $1 AND user_id = $2",
        slot_id, current_user["id"],
    )
    if not row:
        raise HTTPException(404, "Время замера не найдено")

    usage_count = await db.fetchval(
        "SELECT COUNT(*) FROM metric_slots WHERE slot_id = $1 AND enabled = TRUE",
        slot_id,
    )
    if usage_count > 0:
        names_row = await db.fetch(
            """SELECT DISTINCT md.name FROM metric_slots msl
               JOIN metric_definitions md ON md.id = msl.metric_id
               WHERE msl.slot_id = $1 AND msl.enabled = TRUE""",
            slot_id,
        )
        names = ", ".join(r["name"] for r in names_row)
        raise HTTPException(
            409,
            f"Время замера используется в метриках: {names}. Сначала отвяжите его.",
        )

    # Clean up disabled metric_slots rows before deleting the slot
    await db.execute(
        "DELETE FROM metric_slots WHERE slot_id = $1 AND enabled = FALSE",
        slot_id,
    )

    await db.execute(
        "DELETE FROM measurement_slots WHERE id = $1 AND user_id = $2",
        slot_id, current_user["id"],
    )


@router.post("/{source_id}/merge/{target_id}")
async def merge_slots(
    source_id: int,
    target_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if source_id == target_id:
        raise HTTPException(400, "Нельзя объединить слот сам с собой")

    uid = current_user["id"]
    source = await db.fetchrow(
        "SELECT id FROM measurement_slots WHERE id = $1 AND user_id = $2",
        source_id, uid,
    )
    if not source:
        raise HTTPException(404, "Исходный слот не найден")

    target = await db.fetchrow(
        "SELECT id FROM measurement_slots WHERE id = $1 AND user_id = $2",
        target_id, uid,
    )
    if not target:
        raise HTTPException(404, "Целевой слот не найден")

    async with db.transaction():
        # 1. Move metric_slots: if (metric_id, target) already exists, delete source row
        conflicting_ms = await db.fetch(
            """SELECT ms_src.id
               FROM metric_slots ms_src
               JOIN metric_slots ms_tgt ON ms_tgt.metric_id = ms_src.metric_id
                    AND ms_tgt.slot_id = $2
               WHERE ms_src.slot_id = $1""",
            source_id, target_id,
        )
        conflicting_ms_ids = [r["id"] for r in conflicting_ms]
        if conflicting_ms_ids:
            await db.execute(
                "DELETE FROM metric_slots WHERE id = ANY($1::int[])",
                conflicting_ms_ids,
            )

        metrics_moved = await db.execute(
            "UPDATE metric_slots SET slot_id = $1 WHERE slot_id = $2",
            target_id, source_id,
        )
        metrics_affected = int(metrics_moved.split()[-1])

        # 2. Move entries: delete conflicting (same metric_id, user_id, date), move rest
        entries_deleted_result = await db.execute(
            """DELETE FROM entries e_src
               USING entries e_tgt
               WHERE e_src.slot_id = $1
                 AND e_src.user_id = $2
                 AND e_tgt.slot_id = $3
                 AND e_tgt.user_id = $2
                 AND e_tgt.metric_id = e_src.metric_id
                 AND e_tgt.date = e_src.date""",
            source_id, uid, target_id,
        )
        entries_deleted = int(entries_deleted_result.split()[-1])

        entries_moved_result = await db.execute(
            "UPDATE entries SET slot_id = $1 WHERE slot_id = $2 AND user_id = $3",
            target_id, source_id, uid,
        )
        entries_moved = int(entries_moved_result.split()[-1])

        # 3. Delete source slot
        await db.execute(
            "DELETE FROM measurement_slots WHERE id = $1 AND user_id = $2",
            source_id, uid,
        )

    return {
        "ok": True,
        "metrics_affected": metrics_affected + len(conflicting_ms_ids),
        "entries_moved": entries_moved,
        "entries_deleted": entries_deleted,
    }


@router.post("/reorder")
async def reorder_slots(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    async with db.transaction():
        for item in items:
            await db.execute(
                """UPDATE measurement_slots
                   SET sort_order = $1
                   WHERE id = $2 AND user_id = $3""",
                item["sort_order"], item["id"], current_user["id"],
            )
    return {"ok": True}
