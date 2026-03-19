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
                  COALESCE(cnt.c, 0) AS usage_count
           FROM measurement_slots ms
           LEFT JOIN (SELECT slot_id, COUNT(*) c FROM metric_slots GROUP BY slot_id) cnt
             ON cnt.slot_id = ms.id
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
        "SELECT COUNT(*) FROM metric_slots WHERE slot_id = $1",
        slot_id,
    )
    if usage_count > 0:
        raise HTTPException(
            409,
            f"Время замера используется в {usage_count} метриках. Сначала отвяжите его.",
        )

    await db.execute(
        "DELETE FROM measurement_slots WHERE id = $1 AND user_id = $2",
        slot_id, current_user["id"],
    )


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
