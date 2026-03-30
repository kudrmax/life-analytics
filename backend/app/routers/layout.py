"""Router for daily layout ordering."""

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.repositories.layout_repository import LayoutRepository
from app.services.layout_service import LayoutService

router = APIRouter(prefix="/api/layout", tags=["layout"])


def _service(db, user) -> LayoutService:
    return LayoutService(LayoutRepository(db, user["id"]))


@router.get("")
async def get_layout(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).get_order_data()


@router.post("/blocks")
async def save_block_order(
    items: list[dict],
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _service(db, current_user).save_block_order(items)
    return {"ok": True}


@router.post("/inner")
async def save_inner_order(
    data: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _service(db, current_user).save_inner_order(
        data["block_type"], data["block_id"], data["items"],
    )
    return {"ok": True}
