from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.schemas import CheckpointCreate, CheckpointUpdate, CheckpointSettingsOut
from app.repositories.checkpoints_repository import CheckpointsRepository
from app.services.checkpoints_service import CheckpointsService

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


def _service(db, user) -> CheckpointsService:
    return CheckpointsService(CheckpointsRepository(db, user["id"]))


@router.get("", response_model=list[CheckpointSettingsOut])
async def list_checkpoints(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).list_all()


@router.post("", response_model=CheckpointSettingsOut, status_code=201)
async def create_checkpoint(data: CheckpointCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(data.label, data.description)


@router.patch("/{checkpoint_id}", response_model=CheckpointSettingsOut)
async def update_checkpoint(checkpoint_id: int, data: CheckpointUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(checkpoint_id, data.label, data.description)


@router.delete("/{checkpoint_id}", status_code=204)
async def delete_checkpoint(checkpoint_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(checkpoint_id)


@router.post("/{source_id}/merge/{target_id}")
async def merge_checkpoints(source_id: int, target_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).merge(source_id, target_id)


@router.post("/reorder")
async def reorder_checkpoints(items: list[dict], db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).reorder(items)
    return {"ok": True}


@router.get("/intervals")
async def list_intervals(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).get_intervals()
