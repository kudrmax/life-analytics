from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user, get_privacy_mode
from app.repositories.daily_repository import DailyRepository
from app.services.daily_service import DailyService

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(
    date: str,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    service = DailyService(DailyRepository(db, current_user["id"]))
    return await service.get_daily_summary(date, privacy_mode)
