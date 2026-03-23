from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.schemas import CategoryCreate, CategoryUpdate, CategoryOut
from app.repositories.categories_repository import CategoriesRepository
from app.services.categories_service import CategoriesService

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _service(db, user) -> CategoriesService:
    return CategoriesService(CategoriesRepository(db, user["id"]))


@router.get("", response_model=list[CategoryOut])
async def list_categories(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).list_tree()


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(data.name, data.parent_id)


@router.patch("/{cat_id}", response_model=CategoryOut)
async def update_category(cat_id: int, data: CategoryUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(cat_id, data.name, data.parent_id)


@router.delete("/{cat_id}", status_code=204)
async def delete_category(cat_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(cat_id)


@router.post("/reorder")
async def reorder_categories(items: list[dict], db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).reorder(items)
    return {"ok": True}
