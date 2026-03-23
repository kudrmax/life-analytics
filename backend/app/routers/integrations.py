import os
from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError

from app.database import get_db
from app.auth import get_current_user, SECRET_KEY, ALGORITHM
from app.encryption import encrypt_token
from app.integrations.todoist.client import TodoistClient
from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON
from app.integrations.todoist.service import fetch_and_store
from app.integrations.activitywatch.service import process_and_store as aw_process_and_store
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS, ACTIVITYWATCH_ICON
from app.schemas import AWSyncRequest
from app.repositories.integrations_repository import IntegrationsRepository

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

TODOIST_CLIENT_ID = os.environ.get("TODOIST_CLIENT_ID", "")
TODOIST_CLIENT_SECRET = os.environ.get("TODOIST_CLIENT_SECRET", "")


@router.get("")
async def list_integrations(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    rows = await repo.get_user_integrations()
    connected = {r["provider"]: r for r in rows}
    result = []
    if TODOIST_CLIENT_ID:
        if "todoist" in connected:
            r = connected["todoist"]
            result.append({
                "provider": "todoist",
                "enabled": r["enabled"],
                "connected_at": r["created_at"].isoformat(),
            })
        else:
            result.append({
                "provider": "todoist",
                "enabled": False,
                "connected_at": None,
            })
    aw_settings = await repo.get_aw_settings()
    result.append({
        "provider": "activitywatch",
        "enabled": aw_settings["enabled"] if aw_settings else False,
        "connected_at": None,
    })

    return result


@router.get("/todoist/auth-url")
async def todoist_auth_url(
    current_user: dict = Depends(get_current_user),
):
    if not TODOIST_CLIENT_ID:
        raise HTTPException(500, "Todoist integration not configured")

    state_payload = {
        "sub": str(current_user["id"]),
        "exp": datetime.utcnow() + timedelta(minutes=10),
        "purpose": "todoist_oauth",
    }
    state = jwt.encode(state_payload, SECRET_KEY, algorithm=ALGORITHM)

    from todoist_api_python.authentication import get_authentication_url
    url = get_authentication_url(
        client_id=TODOIST_CLIENT_ID,
        scopes=["data:read"],
        state=state,
    )
    return {"url": url}


@router.get("/todoist/callback")
async def todoist_callback(
    code: str = Query(...),
    state: str = Query(...),
    db=Depends(get_db),
):
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
        if payload.get("purpose") != "todoist_oauth":
            raise HTTPException(400, "Invalid state")
    except JWTError:
        raise HTTPException(400, "Invalid or expired state")

    if not TODOIST_CLIENT_ID or not TODOIST_CLIENT_SECRET:
        raise HTTPException(500, "Todoist integration not configured")

    import requests as req
    try:
        resp = req.post(
            "https://todoist.com/oauth/access_token",
            data={
                "client_id": TODOIST_CLIENT_ID,
                "client_secret": TODOIST_CLIENT_SECRET,
                "code": code,
            },
        )
        resp.raise_for_status()
        access_token = resp.json()["access_token"]
    except Exception as e:
        raise HTTPException(400, f"Failed to get access token: {e}")

    client = TodoistClient(access_token)
    if not await client.verify_token():
        raise HTTPException(400, "Token verification failed")

    encrypted = encrypt_token(access_token)
    repo = IntegrationsRepository(db, user_id)
    await repo.upsert_todoist_token(encrypted)

    return RedirectResponse("/")


@router.get("/todoist/available-metrics")
async def todoist_available_metrics(
    current_user: dict = Depends(get_current_user),
):
    return [
        {
            "key": key,
            "name": info["name"],
            "value_type": info["value_type"],
            "config_fields": info.get("config_fields", []),
        }
        for key, info in TODOIST_METRICS.items()
    ]


@router.delete("/{provider}/disconnect")
async def disconnect_integration(
    provider: str,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    result = await repo.disconnect_provider(provider)
    if result == "DELETE 0":
        raise HTTPException(404, "Integration not found")
    return {"status": "disconnected"}


@router.post("/{provider}/fetch")
async def fetch_integration_data(
    provider: str,
    date: str = Query(None),
    metric_id: int = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    target_date = date_type.fromisoformat(date) if date else date_type.today()

    if provider == "todoist":
        try:
            result = await fetch_and_store(db, current_user["id"], target_date, metric_id=metric_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"Todoist API error: {e}")
        return {
            "provider": provider,
            "date": str(target_date),
            "results": result.get("results", []),
            "errors": result.get("errors", []),
        }

    if provider == "activitywatch":
        from app.integrations.activitywatch.service import compute_integration_metrics
        try:
            await compute_integration_metrics(db, current_user["id"], target_date)
        except Exception as e:
            raise HTTPException(500, f"AW metrics error: {e}")
        return {
            "provider": provider,
            "date": str(target_date),
            "results": [{"status": "updated"}],
            "errors": [],
        }

    raise HTTPException(400, f"Unknown provider: {provider}")


# ─── ActivityWatch ───────────────────────────────────────────────


@router.get("/activitywatch/status")
async def aw_status(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    settings = await repo.get_aw_settings()
    if not settings:
        return {"enabled": False, "aw_url": "http://localhost:5600", "configured": False}
    return {
        "enabled": settings["enabled"],
        "aw_url": settings["aw_url"],
        "configured": True,
    }


@router.post("/activitywatch/enable")
async def aw_enable(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    await repo.aw_enable()
    return {"status": "enabled"}


@router.delete("/activitywatch/disable")
async def aw_disable(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    await repo.aw_disable()
    return {"status": "disabled"}


@router.post("/activitywatch/sync")
async def aw_sync(
    body: AWSyncRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    target_date = date_type.fromisoformat(body.date)
    result = await aw_process_and_store(
        db, current_user["id"], target_date,
        window_events=[e.model_dump() for e in body.window_events],
        afk_events=[e.model_dump() for e in body.afk_events],
        web_events=[e.model_dump() for e in body.web_events] if body.web_events else None,
    )
    return {
        "date": body.date,
        "total_seconds": result["total_seconds"],
        "active_seconds": result["active_seconds"],
        "app_count": len(result["apps"]),
        "domain_count": len(result["domains"]),
    }


@router.get("/activitywatch/summary")
async def aw_summary(
    date: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    d = date_type.fromisoformat(date)
    summary = await repo.get_aw_daily_summary(d)
    apps = await repo.get_aw_app_usage(d)
    if not summary:
        return {"date": date, "synced": False, "total_seconds": 0, "active_seconds": 0, "afk_percent": 0, "apps": [], "domains": [], "all_apps": [], "all_domains": []}

    total_sec = summary["total_seconds"]
    active_sec = summary["active_seconds"]
    afk_percent = round((1 - active_sec / total_sec) * 100) if total_sec > 0 else 0

    all_apps = [
        {
            "app_name": a["app_name"],
            "duration_seconds": a["duration_seconds"],
            "percent": round(a["duration_seconds"] / active_sec * 100) if active_sec > 0 else 0,
        }
        for a in apps if a["source"] == "window"
    ]
    all_domains = [
        {
            "domain": a["app_name"],
            "duration_seconds": a["duration_seconds"],
            "percent": round(a["duration_seconds"] / active_sec * 100) if active_sec > 0 else 0,
        }
        for a in apps if a["source"] == "web"
    ]

    return {
        "date": date,
        "synced": True,
        "total_seconds": total_sec,
        "active_seconds": active_sec,
        "afk_percent": afk_percent,
        "synced_at": summary["synced_at"].isoformat(),
        "apps": all_apps[:7],
        "domains": all_domains[:5],
        "all_apps": all_apps,
        "all_domains": all_domains,
    }


@router.get("/activitywatch/trends")
async def aw_trends(
    start: str = Query(...),
    end: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    rows = await repo.get_aw_trends(start_d, end_d)
    points = []
    for r in rows:
        total_h = round(r["total_seconds"] / 3600, 2)
        active_h = round(r["active_seconds"] / 3600, 2)
        points.append({
            "date": str(r["date"]),
            "total_hours": total_h,
            "active_hours": active_h,
            "afk_hours": round(max(0, total_h - active_h), 2),
        })
    return {
        "start": start,
        "end": end,
        "points": points,
    }


# ─── ActivityWatch Categories ───────────────────────────────────


@router.get("/activitywatch/categories")
async def aw_list_categories(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    rows = await repo.get_aw_categories()
    return [dict(r) for r in rows]


@router.post("/activitywatch/categories", status_code=201)
async def aw_create_category(
    body: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    color = body.get("color", "#6c5ce7")
    repo = IntegrationsRepository(db, current_user["id"])
    sort_order = await repo.get_aw_next_cat_sort_order()
    cat_id = await repo.create_aw_category(name, color, sort_order)
    return {"id": cat_id, "name": name, "color": color, "sort_order": sort_order}


@router.put("/activitywatch/categories/{cat_id}")
async def aw_update_category(
    cat_id: int,
    body: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    row = await repo.get_aw_category(cat_id)
    if not row:
        raise HTTPException(404, "Category not found")
    updates, params = [], []
    idx = 1
    if "name" in body:
        updates.append(f"name = ${idx}")
        params.append(body["name"].strip())
        idx += 1
    if "color" in body:
        updates.append(f"color = ${idx}")
        params.append(body["color"])
        idx += 1
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await repo.update_aw_category(cat_id, updates, params)
    return {"status": "updated"}


@router.delete("/activitywatch/categories/{cat_id}")
async def aw_delete_category(
    cat_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    result = await repo.delete_aw_category(cat_id)
    if result == "DELETE 0":
        raise HTTPException(404, "Category not found")
    return {"status": "deleted"}


@router.get("/activitywatch/apps")
async def aw_list_apps(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    rows = await repo.get_aw_apps_with_categories()
    return [
        {
            "app_name": r["app_name"],
            "category_id": r["activitywatch_category_id"],
            "category_name": r["category_name"],
            "category_color": r["category_color"],
        }
        for r in rows
    ]


@router.put("/activitywatch/apps/{app_name}/category")
async def aw_set_app_category(
    app_name: str,
    body: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = IntegrationsRepository(db, current_user["id"])
    category_id = body.get("category_id")
    if category_id is None:
        await repo.remove_app_category(app_name)
    else:
        cat = await repo.get_aw_category(category_id)
        if not cat:
            raise HTTPException(404, "Category not found")
        await repo.upsert_app_category(app_name, category_id)
    return {"status": "updated"}


@router.put("/activitywatch/apps/batch-category")
async def aw_batch_set_category(
    body: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    app_names = body.get("app_names", [])
    category_id = body.get("category_id")
    if not app_names:
        raise HTTPException(400, "app_names is required")
    repo = IntegrationsRepository(db, current_user["id"])
    if category_id is not None:
        cat = await repo.get_aw_category(category_id)
        if not cat:
            raise HTTPException(404, "Category not found")
    for app_name in app_names:
        if category_id is None:
            await repo.remove_app_category(app_name)
        else:
            await repo.upsert_app_category(app_name, category_id)
    return {"status": "updated", "count": len(app_names)}


# ─── ActivityWatch Available Metrics ─────────────────────────────


@router.get("/activitywatch/available-metrics")
async def aw_available_metrics(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = []
    for key, info in ACTIVITYWATCH_METRICS.items():
        item = {
            "key": key,
            "name": info["name"],
            "description": info.get("description", ""),
            "value_type": info["value_type"],
            "config_fields": info.get("config_fields", []),
        }
        result.append(item)
    return result
