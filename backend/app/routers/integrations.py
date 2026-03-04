import os
from datetime import date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError

from app.database import get_db
from app.auth import get_current_user, SECRET_KEY, ALGORITHM
from app.encryption import encrypt_token
from app.integrations.todoist.client import TodoistClient
from app.integrations.todoist.service import fetch_and_store

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

    existing_metric = await db.fetchval(
        "SELECT id FROM metric_definitions WHERE user_id = $1 AND slug = 'todoist_completed_tasks'",
        user_id,
    )
    if not existing_metric:
        max_order = await db.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) FROM metric_definitions WHERE user_id = $1",
            user_id,
        )
        metric_id = await db.fetchval(
            """INSERT INTO metric_definitions
               (user_id, slug, name, category, icon, type, enabled, sort_order)
               VALUES ($1, 'todoist_completed_tasks', 'Todoist: задачи', 'Интеграции', '✅', 'integration', TRUE, $2)
               RETURNING id""",
            user_id, max_order + 1,
        )
        await db.execute(
            "INSERT INTO integration_config (metric_id, provider, metric_key) VALUES ($1, 'todoist', 'completed_tasks_count')",
            metric_id,
        )
    else:
        await db.execute(
            "UPDATE metric_definitions SET enabled = TRUE WHERE id = $1",
            existing_metric,
        )
        await db.execute(
            """INSERT INTO integration_config (metric_id, provider, metric_key)
               VALUES ($1, 'todoist', 'completed_tasks_count')
               ON CONFLICT (metric_id) DO NOTHING""",
            existing_metric,
        )

    return RedirectResponse("/")


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
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if provider != "todoist":
        raise HTTPException(400, f"Unknown provider: {provider}")

    today = date_type.today()
    try:
        count = await fetch_and_store(db, current_user["id"], today)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Todoist API error: {e}")

    return {"provider": provider, "date": str(today), "value": count}
