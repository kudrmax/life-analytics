from datetime import date as date_type, datetime, timezone

import httpx
from todoist_api_python.api_async import TodoistAPIAsync

TODOIST_SYNC_URL = "https://api.todoist.com/api/v1/sync"
TODOIST_FILTER_URL = "https://api.todoist.com/api/v1/tasks/filter"


async def _close_api(api: TodoistAPIAsync):
    """Safely close the API client (handles SDK versions with/without close)."""
    if hasattr(api, 'close'):
        await api.close()


class TodoistClient:
    def __init__(self, access_token: str):
        self._token = access_token

    async def get_completed_tasks_count(self, for_date: date_type) -> int:
        since = datetime(for_date.year, for_date.month, for_date.day, 0, 0, 0, tzinfo=timezone.utc)
        until = datetime(for_date.year, for_date.month, for_date.day, 23, 59, 59, tzinfo=timezone.utc)
        api = TodoistAPIAsync(self._token)
        count = 0
        try:
            async for batch in await api.get_completed_tasks_by_completion_date(
                since=since, until=until,
            ):
                count += len(batch)
        finally:
            await _close_api(api)
        return count

    async def get_filter_query_by_name(self, filter_name: str) -> str | None:
        """Fetch user's filters via Sync API and find query by filter name (case-insensitive)."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                TODOIST_SYNC_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                json={"sync_token": "*", "resource_types": '["filters"]'},
            )
            resp.raise_for_status()
            data = resp.json()
        for f in data.get("filters", []):
            if f.get("name", "").lower() == filter_name.lower():
                return f.get("query")
        return None

    async def get_tasks_count_by_query(self, query: str) -> int:
        """Count tasks matching a filter query via GET /api/v1/tasks/filter.

        Comma-separated sub-queries are split and executed individually
        (the Filter API does not support the comma operator).
        Tasks are deduplicated by ID across sub-queries.
        """
        sub_queries = [q.strip() for q in query.split(",") if q.strip()]
        seen_ids: set[str] = set()
        async with httpx.AsyncClient(timeout=30) as client:
            for sq in sub_queries:
                cursor = None
                while True:
                    params: dict = {"query": sq, "limit": 200}
                    if cursor:
                        params["cursor"] = cursor
                    resp = await client.get(
                        TODOIST_FILTER_URL,
                        headers={"Authorization": f"Bearer {self._token}"},
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for task in data.get("results", data.get("items", [])):
                        seen_ids.add(task["id"])
                    cursor = data.get("next_cursor")
                    if not cursor:
                        break
        return len(seen_ids)

    async def verify_token(self) -> bool:
        api = TodoistAPIAsync(self._token)
        try:
            await api.get_projects()
            return True
        except Exception:
            return False
        finally:
            await _close_api(api)
