import os
from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError

from app.database import get_db, seed_default_categories
from app.auth import get_current_user, SECRET_KEY, ALGORITHM
from app.encryption import encrypt_token
from app.integrations.todoist.client import TodoistClient
from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON
from app.integrations.todoist.service import fetch_and_store
from app.integrations.activitywatch.service import process_and_store as aw_process_and_store
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS, ACTIVITYWATCH_ICON
from app.schemas import AWSyncRequest

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

TODOIST_CLIENT_ID = os.environ.get("TODOIST_CLIENT_ID", "")
TODOIST_CLIENT_SECRET = os.environ.get("TODOIST_CLIENT_SECRET", "")


@router.get("")
async def list_integrations(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        "SELECT provider, enabled, created_at FROM user_integrations WHERE user_id = $1",
        current_user["id"],
    )
    connected = {r["provider"]: r for r in rows}
    result = []
    # Todoist — show only if configured on server
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
    # ActivityWatch — always available (no server-side config needed)
    aw_settings = await db.fetchrow(
        "SELECT enabled FROM activitywatch_settings WHERE user_id = $1",
        current_user["id"],
    )
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
    await db.execute(
        """INSERT INTO user_integrations (user_id, provider, encrypted_token)
           VALUES ($1, 'todoist', $2)
           ON CONFLICT (user_id, provider) DO UPDATE
           SET encrypted_token = EXCLUDED.encrypted_token, enabled = TRUE""",
        user_id, encrypted,
    )

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
    await db.execute(
        """UPDATE metric_definitions SET enabled = FALSE
           WHERE user_id = $1 AND id IN (
               SELECT metric_id FROM integration_config WHERE provider = $2
           )""",
        current_user["id"], provider,
    )
    result = await db.execute(
        "DELETE FROM user_integrations WHERE user_id = $1 AND provider = $2",
        current_user["id"], provider,
    )
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
    settings = await db.fetchrow(
        "SELECT enabled, aw_url FROM activitywatch_settings WHERE user_id = $1",
        current_user["id"],
    )
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
    await db.execute(
        """INSERT INTO activitywatch_settings (user_id, enabled)
           VALUES ($1, TRUE)
           ON CONFLICT (user_id) DO UPDATE SET enabled = TRUE""",
        current_user["id"],
    )
    await seed_default_categories(db, current_user["id"])
    return {"status": "enabled"}


@router.delete("/activitywatch/disable")
async def aw_disable(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await db.execute(
        "UPDATE activitywatch_settings SET enabled = FALSE WHERE user_id = $1",
        current_user["id"],
    )
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
    d = date_type.fromisoformat(date)
    summary = await db.fetchrow(
        "SELECT total_seconds, active_seconds, synced_at FROM activitywatch_daily_summary WHERE user_id = $1 AND date = $2",
        current_user["id"], d,
    )
    apps = await db.fetch(
        """SELECT app_name, source, duration_seconds
           FROM activitywatch_app_usage
           WHERE user_id = $1 AND date = $2
           ORDER BY duration_seconds DESC""",
        current_user["id"], d,
    )
    if not summary:
        return {"date": date, "synced": False, "total_seconds": 0, "active_seconds": 0, "apps": [], "domains": []}

    return {
        "date": date,
        "synced": True,
        "total_seconds": summary["total_seconds"],
        "active_seconds": summary["active_seconds"],
        "synced_at": summary["synced_at"].isoformat(),
        "apps": [
            {"app_name": a["app_name"], "duration_seconds": a["duration_seconds"]}
            for a in apps if a["source"] == "window"
        ],
        "domains": [
            {"domain": a["app_name"], "duration_seconds": a["duration_seconds"]}
            for a in apps if a["source"] == "web"
        ],
    }


@router.get("/activitywatch/trends")
async def aw_trends(
    start: str = Query(...),
    end: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    rows = await db.fetch(
        """SELECT date, total_seconds, active_seconds
           FROM activitywatch_daily_summary
           WHERE user_id = $1 AND date >= $2 AND date <= $3
           ORDER BY date""",
        current_user["id"], start_d, end_d,
    )
    return {
        "start": start,
        "end": end,
        "points": [
            {
                "date": str(r["date"]),
                "total_hours": round(r["total_seconds"] / 3600, 2),
                "active_hours": round(r["active_seconds"] / 3600, 2),
            }
            for r in rows
        ],
    }


# ─── ActivityWatch Categories ───────────────────────────────────


@router.get("/activitywatch/categories")
async def aw_list_categories(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Auto-seed categories for users who enabled AW before this feature
    await seed_default_categories(db, current_user["id"])

    rows = await db.fetch(
        """SELECT id, name, color, sort_order
           FROM activitywatch_categories
           WHERE user_id = $1
           ORDER BY sort_order, id""",
        current_user["id"],
    )
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
    max_order = await db.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) FROM activitywatch_categories WHERE user_id = $1",
        current_user["id"],
    )
    try:
        cat_id = await db.fetchval(
            """INSERT INTO activitywatch_categories (user_id, name, color, sort_order)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            current_user["id"], name, color, max_order + 1,
        )
    except Exception:
        raise HTTPException(409, "Category with this name already exists")
    return {"id": cat_id, "name": name, "color": color, "sort_order": max_order + 1}


@router.put("/activitywatch/categories/{cat_id}")
async def aw_update_category(
    cat_id: int,
    body: dict,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
        cat_id, current_user["id"],
    )
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
    params.extend([cat_id, current_user["id"]])
    await db.execute(
        f"UPDATE activitywatch_categories SET {', '.join(updates)} WHERE id = ${idx} AND user_id = ${idx + 1}",
        *params,
    )
    return {"status": "updated"}


@router.delete("/activitywatch/categories/{cat_id}")
async def aw_delete_category(
    cat_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        "DELETE FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
        cat_id, current_user["id"],
    )
    if result == "DELETE 0":
        raise HTTPException(404, "Category not found")
    return {"status": "deleted"}


@router.get("/activitywatch/apps")
async def aw_list_apps(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        """SELECT DISTINCT au.app_name,
                  acm.category_id,
                  ac.name AS category_name,
                  ac.color AS category_color
           FROM activitywatch_app_usage au
           LEFT JOIN activitywatch_app_category_map acm
               ON acm.user_id = au.user_id AND acm.app_name = au.app_name
           LEFT JOIN activitywatch_categories ac ON ac.id = acm.category_id
           WHERE au.user_id = $1 AND au.source = 'window'
           ORDER BY au.app_name""",
        current_user["id"],
    )
    return [
        {
            "app_name": r["app_name"],
            "category_id": r["category_id"],
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
    category_id = body.get("category_id")
    if category_id is None:
        await db.execute(
            "DELETE FROM activitywatch_app_category_map WHERE user_id = $1 AND app_name = $2",
            current_user["id"], app_name,
        )
    else:
        cat = await db.fetchrow(
            "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
            category_id, current_user["id"],
        )
        if not cat:
            raise HTTPException(404, "Category not found")
        await db.execute(
            """INSERT INTO activitywatch_app_category_map (user_id, app_name, category_id)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id, app_name) DO UPDATE SET category_id = EXCLUDED.category_id""",
            current_user["id"], app_name, category_id,
        )
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
    if category_id is not None:
        cat = await db.fetchrow(
            "SELECT id FROM activitywatch_categories WHERE id = $1 AND user_id = $2",
            category_id, current_user["id"],
        )
        if not cat:
            raise HTTPException(404, "Category not found")
    for app_name in app_names:
        if category_id is None:
            await db.execute(
                "DELETE FROM activitywatch_app_category_map WHERE user_id = $1 AND app_name = $2",
                current_user["id"], app_name,
            )
        else:
            await db.execute(
                """INSERT INTO activitywatch_app_category_map (user_id, app_name, category_id)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (user_id, app_name) DO UPDATE SET category_id = EXCLUDED.category_id""",
                current_user["id"], app_name, category_id,
            )
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
