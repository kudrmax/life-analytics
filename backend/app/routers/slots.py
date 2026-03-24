from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.schemas import SlotCreate, SlotUpdate, SlotOut
from app.repositories.slots_repository import SlotsRepository
from app.services.slots_service import SlotsService

router = APIRouter(prefix="/api/slots", tags=["slots"])


def _service(db, user) -> SlotsService:
    return SlotsService(SlotsRepository(db, user["id"]))


@router.get("", response_model=list[SlotOut])
async def list_slots(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).list_all()


@router.post("", response_model=SlotOut, status_code=201)
async def create_slot(data: SlotCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(data.label, data.description)


@router.patch("/{slot_id}", response_model=SlotOut)
async def update_slot(slot_id: int, data: SlotUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(slot_id, data.label, data.description)


@router.delete("/{slot_id}", status_code=204)
async def delete_slot(slot_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(slot_id)


@router.post("/{source_id}/merge/{target_id}")
async def merge_slots(source_id: int, target_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).merge(source_id, target_id)


@router.post("/reorder")
async def reorder_slots(items: list[dict], db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).reorder(items)
    return {"ok": True}
