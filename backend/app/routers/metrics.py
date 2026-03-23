from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.database import get_db
from app.schemas import (
    MetricDefinitionCreate, MetricDefinitionUpdate, MetricDefinitionOut, MetricType,
    ConversionPreview, MetricConvertRequest, MetricConvertResponse,
)
from app.auth import get_current_user, get_privacy_mode
from app.repositories.metric_repository import MetricRepository
from app.repositories.metric_config_repository import MetricConfigRepository
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _service(db, user) -> MetricsService:
    repo = MetricRepository(db, user["id"])
    cfg_repo = MetricConfigRepository(db, user["id"])
    return MetricsService(repo, cfg_repo, db)


@router.get("/export/markdown")
async def export_metrics_markdown(db=Depends(get_db), current_user: dict = Depends(get_current_user)) -> Response:
    text = await _service(db, current_user).export_markdown()
    return Response(content=text, media_type="text/markdown")


@router.get("", response_model=list[MetricDefinitionOut])
async def list_metrics(
    enabled_only: bool = False,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).list_all(enabled_only, privacy_mode)


@router.post("/reorder")
async def reorder_metrics(items: list[dict], db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).reorder(items)
    return {"ok": True}


@router.get("/{metric_id}", response_model=MetricDefinitionOut)
async def get_metric(
    metric_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).get_one(metric_id, privacy_mode)


@router.post("", response_model=MetricDefinitionOut, status_code=201)
async def create_metric(
    data: MetricDefinitionCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).create(data, privacy_mode)


@router.patch("/{metric_id}", response_model=MetricDefinitionOut)
async def update_metric(
    metric_id: int,
    data: MetricDefinitionUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    return await _service(db, current_user).update(metric_id, data, privacy_mode)


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(metric_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).delete(metric_id)


@router.get("/{metric_id}/convert/preview", response_model=ConversionPreview)
async def convert_preview(
    metric_id: int,
    target_type: MetricType,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = _service(db, current_user)
    repo = MetricRepository(db, current_user["id"])
    row = await repo.get_by_id_columns(metric_id, "id, type")
    return await svc.conversion_service().preview(metric_id, row["type"], target_type)


@router.post("/{metric_id}/convert", response_model=MetricConvertResponse)
async def convert_metric(
    metric_id: int,
    data: MetricConvertRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = _service(db, current_user)
    repo = MetricRepository(db, current_user["id"])
    async with db.transaction():
        row = await repo.get_by_id_for_update(metric_id)
        return await svc.conversion_service().convert(metric_id, row["type"], data)
