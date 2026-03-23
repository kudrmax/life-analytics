from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.schemas import InsightCreate, InsightUpdate, InsightOut
from app.repositories.insights_repository import InsightsRepository
from app.services.insights_service import InsightsService

router = APIRouter(prefix="/api/insights", tags=["insights"])


def _service(db, user) -> InsightsService:
    return InsightsService(InsightsRepository(db, user["id"]))


@router.get("", response_model=list[InsightOut])
async def list_insights(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).list_all()


@router.post("", response_model=InsightOut, status_code=201)
async def create_insight(data: InsightCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).create(data)


@router.put("/{insight_id}", response_model=InsightOut)
async def update_insight(insight_id: int, data: InsightUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).update(insight_id, data)


@router.delete("/{insight_id}", status_code=204)
async def delete_insight(insight_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(insight_id)
