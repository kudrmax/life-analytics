from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.database import get_db
from app.auth import get_current_user
from app.schemas import AWSyncRequest
from app.repositories.integrations_repository import IntegrationsRepository
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _service(db, user) -> IntegrationService:
    return IntegrationService(IntegrationsRepository(db, user["id"]), db)


@router.get("")
async def list_integrations(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).list_integrations()


@router.get("/todoist/auth-url")
async def todoist_auth_url(current_user: dict = Depends(get_current_user)):
    svc = IntegrationService(None, None)  # type: ignore[arg-type]
    url = svc.get_todoist_auth_url(current_user["id"])
    return {"url": url}


@router.get("/todoist/callback")
async def todoist_callback(code: str = Query(...), state: str = Query(...), db=Depends(get_db)):
    svc = IntegrationService(None, db)  # type: ignore[arg-type]
    await svc.todoist_callback(code, state)
    return RedirectResponse("/")


@router.get("/todoist/available-metrics")
async def todoist_available_metrics(current_user: dict = Depends(get_current_user)):
    return IntegrationService.get_todoist_available_metrics()


@router.delete("/{provider}/disconnect")
async def disconnect_integration(provider: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).disconnect(provider)
    return {"status": "disconnected"}


@router.post("/{provider}/fetch")
async def fetch_integration_data(
    provider: str,
    date: str = Query(None),
    metric_id: int = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _service(db, current_user).fetch_data(provider, date, metric_id)


# ─── ActivityWatch ───────────────────────────────────────────────

@router.get("/activitywatch/status")
async def aw_status(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_status()


@router.post("/activitywatch/enable")
async def aw_enable(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).aw_enable()
    return {"status": "enabled"}


@router.delete("/activitywatch/disable")
async def aw_disable(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).aw_disable()
    return {"status": "disabled"}


@router.post("/activitywatch/sync")
async def aw_sync(body: AWSyncRequest, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_sync(body)


@router.get("/activitywatch/summary")
async def aw_summary(date: str = Query(...), db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_summary(date)


@router.get("/activitywatch/trends")
async def aw_trends(start: str = Query(...), end: str = Query(...), db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_trends(start, end)


@router.get("/activitywatch/categories")
async def aw_list_categories(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_list_categories()


@router.post("/activitywatch/categories", status_code=201)
async def aw_create_category(body: dict, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_create_category(body.get("name", ""), body.get("color", "#6c5ce7"))


@router.put("/activitywatch/categories/{cat_id}")
async def aw_update_category(cat_id: int, body: dict, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).aw_update_category(cat_id, body)
    return {"status": "updated"}


@router.delete("/activitywatch/categories/{cat_id}")
async def aw_delete_category(cat_id: int, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).aw_delete_category(cat_id)
    return {"status": "deleted"}


@router.get("/activitywatch/apps")
async def aw_list_apps(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return await _service(db, current_user).aw_list_apps()


@router.put("/activitywatch/apps/{app_name}/category")
async def aw_set_app_category(app_name: str, body: dict, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db, current_user).aw_set_app_category(app_name, body.get("category_id"))
    return {"status": "updated"}


@router.put("/activitywatch/apps/batch-category")
async def aw_batch_set_category(body: dict, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    count = await _service(db, current_user).aw_batch_set_category(body.get("app_names", []), body.get("category_id"))
    return {"status": "updated", "count": count}


@router.get("/activitywatch/available-metrics")
async def aw_available_metrics(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    return IntegrationService.aw_available_metrics()
