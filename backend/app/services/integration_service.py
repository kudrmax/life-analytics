"""Service layer for integrations — Todoist OAuth, ActivityWatch sync, categories."""

import os
from datetime import date as date_type, datetime, timedelta

from jose import jwt, JWTError

from app.auth import SECRET_KEY, ALGORITHM
from app.domain.exceptions import InvalidOperationError, EntityNotFoundError
from app.encryption import encrypt_token
from app.integrations.todoist.client import TodoistClient
from app.integrations.todoist.registry import TODOIST_METRICS
from app.integrations.todoist.service import fetch_and_store
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS
from app.integrations.activitywatch.service import process_and_store as aw_process_and_store
from app.repositories.integrations_repository import IntegrationsRepository

TODOIST_CLIENT_ID = os.environ.get("TODOIST_CLIENT_ID", "")
TODOIST_CLIENT_SECRET = os.environ.get("TODOIST_CLIENT_SECRET", "")


class IntegrationService:
    def __init__(self, repo: IntegrationsRepository, conn) -> None:
        self.repo = repo
        self.conn = conn
        self.user_id = repo.user_id

    async def list_integrations(self) -> list[dict]:
        rows = await self.repo.get_user_integrations()
        connected = {r["provider"]: r for r in rows}
        result = []
        if TODOIST_CLIENT_ID:
            if "todoist" in connected:
                r = connected["todoist"]
                result.append({"provider": "todoist", "enabled": r["enabled"], "connected_at": r["created_at"].isoformat()})
            else:
                result.append({"provider": "todoist", "enabled": False, "connected_at": None})
        aw_settings = await self.repo.get_aw_settings()
        result.append({
            "provider": "activitywatch",
            "enabled": aw_settings["enabled"] if aw_settings else False,
            "connected_at": None,
        })
        return result

    def get_todoist_auth_url(self, user_id: int) -> str:
        if not TODOIST_CLIENT_ID:
            raise InvalidOperationError("Todoist integration not configured")
        state_payload = {
            "sub": str(user_id),
            "exp": datetime.utcnow() + timedelta(minutes=10),
            "purpose": "todoist_oauth",
        }
        state = jwt.encode(state_payload, SECRET_KEY, algorithm=ALGORITHM)
        from todoist_api_python.authentication import get_authentication_url
        url = get_authentication_url(client_id=TODOIST_CLIENT_ID, scopes=["data:read"], state=state)
        return url

    async def todoist_callback(self, code: str, state: str) -> None:
        try:
            payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload["sub"])
            if payload.get("purpose") != "todoist_oauth":
                raise InvalidOperationError("Invalid state")
        except JWTError:
            raise InvalidOperationError("Invalid or expired state")

        if not TODOIST_CLIENT_ID or not TODOIST_CLIENT_SECRET:
            raise InvalidOperationError("Todoist integration not configured")

        import requests as req
        try:
            resp = req.post(
                "https://todoist.com/oauth/access_token",
                data={"client_id": TODOIST_CLIENT_ID, "client_secret": TODOIST_CLIENT_SECRET, "code": code},
            )
            resp.raise_for_status()
            access_token = resp.json()["access_token"]
        except Exception as e:
            raise InvalidOperationError(f"Failed to get access token: {e}")

        client = TodoistClient(access_token)
        if not await client.verify_token():
            raise InvalidOperationError("Token verification failed")

        encrypted = encrypt_token(access_token)
        repo = IntegrationsRepository(self.conn, user_id)
        await repo.upsert_todoist_token(encrypted)

    @staticmethod
    def get_todoist_available_metrics() -> list[dict]:
        return [
            {"key": key, "name": info["name"], "value_type": info["value_type"], "config_fields": info.get("config_fields", [])}
            for key, info in TODOIST_METRICS.items()
        ]

    async def disconnect(self, provider: str) -> None:
        result = await self.repo.disconnect_provider(provider)
        if result == "DELETE 0":
            raise EntityNotFoundError("Integration", 0)

    async def fetch_data(self, provider: str, date: str | None, metric_id: int | None) -> dict:
        target_date = date_type.fromisoformat(date) if date else date_type.today()

        if provider == "todoist":
            try:
                result = await fetch_and_store(self.conn, self.user_id, target_date, metric_id=metric_id)
            except ValueError as e:
                raise InvalidOperationError(str(e))
            except Exception as e:
                raise InvalidOperationError(f"Todoist API error: {e}")
            return {
                "provider": provider, "date": str(target_date),
                "results": result.get("results", []), "errors": result.get("errors", []),
            }

        if provider == "activitywatch":
            from app.integrations.activitywatch.service import compute_integration_metrics
            try:
                await compute_integration_metrics(self.conn, self.user_id, target_date)
            except Exception as e:
                raise InvalidOperationError(f"AW metrics error: {e}")
            return {
                "provider": provider, "date": str(target_date),
                "results": [{"status": "updated"}], "errors": [],
            }

        raise InvalidOperationError(f"Unknown provider: {provider}")

    # ── ActivityWatch ─────────────────────────────────────────────

    async def aw_status(self) -> dict:
        settings = await self.repo.get_aw_settings()
        if not settings:
            return {"enabled": False, "aw_url": "http://localhost:5600", "configured": False}
        return {"enabled": settings["enabled"], "aw_url": settings["aw_url"], "configured": True}

    async def aw_enable(self) -> None:
        await self.repo.aw_enable()

    async def aw_disable(self) -> None:
        await self.repo.aw_disable()

    async def aw_sync(self, body) -> dict:
        target_date = date_type.fromisoformat(body.date)
        result = await aw_process_and_store(
            self.conn, self.user_id, target_date,
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

    async def aw_summary(self, date_str: str) -> dict:
        d = date_type.fromisoformat(date_str)
        summary = await self.repo.get_aw_daily_summary(d)
        apps = await self.repo.get_aw_app_usage(d)
        if not summary:
            return {"date": date_str, "synced": False, "total_seconds": 0, "active_seconds": 0, "afk_percent": 0, "apps": [], "domains": [], "all_apps": [], "all_domains": []}

        total_sec = summary["total_seconds"]
        active_sec = summary["active_seconds"]
        afk_percent = round((1 - active_sec / total_sec) * 100) if total_sec > 0 else 0

        all_apps = [
            {"app_name": a["app_name"], "duration_seconds": a["duration_seconds"],
             "percent": round(a["duration_seconds"] / active_sec * 100) if active_sec > 0 else 0}
            for a in apps if a["source"] == "window"
        ]
        all_domains = [
            {"domain": a["app_name"], "duration_seconds": a["duration_seconds"],
             "percent": round(a["duration_seconds"] / active_sec * 100) if active_sec > 0 else 0}
            for a in apps if a["source"] == "web"
        ]
        return {
            "date": date_str, "synced": True,
            "total_seconds": total_sec, "active_seconds": active_sec, "afk_percent": afk_percent,
            "synced_at": summary["synced_at"].isoformat(),
            "apps": all_apps[:7], "domains": all_domains[:5],
            "all_apps": all_apps, "all_domains": all_domains,
        }

    async def aw_trends(self, start: str, end: str) -> dict:
        start_d = date_type.fromisoformat(start)
        end_d = date_type.fromisoformat(end)
        rows = await self.repo.get_aw_trends(start_d, end_d)
        points = []
        for r in rows:
            total_h = round(r["total_seconds"] / 3600, 2)
            active_h = round(r["active_seconds"] / 3600, 2)
            points.append({
                "date": str(r["date"]), "total_hours": total_h,
                "active_hours": active_h, "afk_hours": round(max(0, total_h - active_h), 2),
            })
        return {"start": start, "end": end, "points": points}

    # ── AW Categories ─────────────────────────────────────────────

    async def aw_list_categories(self) -> list[dict]:
        rows = await self.repo.get_aw_categories()
        return [dict(r) for r in rows]

    async def aw_create_category(self, name: str, color: str) -> dict:
        name = name.strip()
        if not name:
            raise InvalidOperationError("name is required")
        sort_order = await self.repo.get_aw_next_cat_sort_order()
        cat_id = await self.repo.create_aw_category(name, color, sort_order)
        return {"id": cat_id, "name": name, "color": color, "sort_order": sort_order}

    async def aw_update_category(self, cat_id: int, body: dict) -> None:
        row = await self.repo.get_aw_category(cat_id)
        if not row:
            raise EntityNotFoundError("Category", cat_id)
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
            raise InvalidOperationError("Nothing to update")
        await self.repo.update_aw_category(cat_id, updates, params)

    async def aw_delete_category(self, cat_id: int) -> None:
        result = await self.repo.delete_aw_category(cat_id)
        if result == "DELETE 0":
            raise EntityNotFoundError("Category", cat_id)

    async def aw_list_apps(self) -> list[dict]:
        rows = await self.repo.get_aw_apps_with_categories()
        return [
            {"app_name": r["app_name"], "category_id": r["activitywatch_category_id"],
             "category_name": r["category_name"], "category_color": r["category_color"]}
            for r in rows
        ]

    async def aw_set_app_category(self, app_name: str, category_id: int | None) -> None:
        if category_id is None:
            await self.repo.remove_app_category(app_name)
        else:
            cat = await self.repo.get_aw_category(category_id)
            if not cat:
                raise EntityNotFoundError("Category", category_id)
            await self.repo.upsert_app_category(app_name, category_id)

    async def aw_batch_set_category(self, app_names: list[str], category_id: int | None) -> int:
        if not app_names:
            raise InvalidOperationError("app_names is required")
        if category_id is not None:
            cat = await self.repo.get_aw_category(category_id)
            if not cat:
                raise EntityNotFoundError("Category", category_id)
        for app_name in app_names:
            if category_id is None:
                await self.repo.remove_app_category(app_name)
            else:
                await self.repo.upsert_app_category(app_name, category_id)
        return len(app_names)

    @staticmethod
    def aw_available_metrics() -> list[dict]:
        return [
            {"key": key, "name": info["name"], "description": info.get("description", ""),
             "value_type": info["value_type"], "config_fields": info.get("config_fields", [])}
            for key, info in ACTIVITYWATCH_METRICS.items()
        ]
