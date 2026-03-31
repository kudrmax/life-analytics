from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.database import get_db
from app.auth import get_current_user, get_privacy_mode
from app.correlation_config import correlation_config
from app.repositories.analytics_repository import AnalyticsRepository
from app.services.analytics_service import AnalyticsService
from app.services.correlation_service import CorrelationService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _service(db, user) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(db, user["id"]), db)


def _corr_service(db, user) -> CorrelationService:
    return CorrelationService(AnalyticsRepository(db, user["id"]), db)


@router.get("/trends")
async def trends(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).trends(metric_id, start, end, privacy_mode)


@router.get("/trends/batch")
async def trends_batch(
    metric_ids: list[int] = Query(default=[]),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).trends_batch(metric_ids, start, end, privacy_mode)


@router.get("/correlations")
async def correlations(
    metric_a: int = Query(...),
    metric_b: int = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _corr_service(db, current_user).pairwise(metric_a, metric_b, start, end)


@router.get("/metric-stats")
async def metric_stats(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).metric_stats(metric_id, start, end, privacy_mode)


@router.get("/metric-distribution")
async def metric_distribution(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).metric_distribution(metric_id, start, end, privacy_mode)


class CorrelationReportRequest(BaseModel):
    start: str
    end: str


class PairStatusBody(BaseModel):
    source_key_a: str
    source_key_b: str
    lag_days: int = 0
    status: str


@router.post("/correlation-report")
async def create_correlation_report(
    body: CorrelationReportRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _corr_service(db, current_user).create_report(body.start, body.end, correlation_config)


@router.get("/correlation-report")
async def get_latest_correlation_report(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _corr_service(db, current_user).get_latest_report()


@router.get("/correlation-report/{report_id}/pairs")
async def get_correlation_pairs(
    report_id: int,
    category: str = "all",
    offset: int = 0,
    limit: int = 50,
    metric_ids: str | None = Query(None),
    status: str | None = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _corr_service(db, current_user).get_pairs(
        report_id, category, offset, limit, metric_ids, privacy_mode, status=status,
    )


@router.put("/correlation-pair-status")
async def set_pair_status(
    body: PairStatusBody,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _corr_service(db, current_user).set_pair_status(
        body.source_key_a, body.source_key_b, body.lag_days, body.status,
    )


@router.delete("/correlation-pair-status")
async def remove_pair_status(
    source_key_a: str = Query(...),
    source_key_b: str = Query(...),
    lag_days: int = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _corr_service(db, current_user).remove_pair_status(
        source_key_a, source_key_b, lag_days,
    )


@router.get("/correlation-pair-chart")
async def correlation_pair_chart(
    pair_id: int = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _corr_service(db, current_user).pair_chart(pair_id, privacy_mode)


@router.get("/streaks")
async def streaks(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).streaks(privacy_mode)
