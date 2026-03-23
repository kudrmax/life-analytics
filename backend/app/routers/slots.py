from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.auth import get_current_user
from app.schemas import SlotCreate, SlotUpdate, SlotOut
from app.repositories.slots_repository import SlotsRepository

router = APIRouter(prefix="/api/slots", tags=["slots"])


@router.get("", response_model=list[SlotOut])
async def list_slots(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = SlotsRepository(db, current_user["id"])
    rows = await repo.get_all_with_usage()
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

    repo = SlotsRepository(db, current_user["id"])
    sort_order = await repo.get_next_sort_order()
    slot_id = await repo.create(label, sort_order)
    return SlotOut(id=slot_id, label=label, sort_order=sort_order)


@router.patch("/{slot_id}", response_model=SlotOut)
async def update_slot(
    slot_id: int,
    data: SlotUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = SlotsRepository(db, current_user["id"])
    await repo.get_by_id(slot_id)

    if data.label is not None:
        label = data.label.strip()
        if not label:
            raise HTTPException(400, "label is required")
        await repo.update_label(slot_id, label)

    updated = await repo.get_updated(slot_id)
    return SlotOut(**dict(updated))


@router.delete("/{slot_id}", status_code=204)
async def delete_slot(
    slot_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = SlotsRepository(db, current_user["id"])
    await repo.get_by_id(slot_id)

    usage_count = await repo.get_enabled_usage_count(slot_id)
    if usage_count > 0:
        names = await repo.get_enabled_metric_names(slot_id)
        raise HTTPException(
            409,
            f"Время замера используется в метриках: {', '.join(names)}. Сначала отвяжите его.",
        )

    await repo.delete_disabled_metric_slots(slot_id)
    await repo.delete(slot_id)


@router.post("/{source_id}/merge/{target_id}")
async def merge_slots(
    source_id: int,
    target_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if source_id == target_id:
        raise HTTPException(400, "Нельзя объединить слот сам с собой")

    repo = SlotsRepository(db, current_user["id"])
    await repo.get_by_id(source_id)
    await repo.get_by_id(target_id)

    stats = await repo.merge(source_id, target_id)
    return {"ok": True, **stats}


@router.post("/reorder")
async def reorder_slots(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = SlotsRepository(db, current_user["id"])
    await repo.reorder(items)
    return {"ok": True}
