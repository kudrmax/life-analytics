from datetime import date as date_type, datetime, timezone

from todoist_api_python.api_async import TodoistAPIAsync


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

    async def verify_token(self) -> bool:
        api = TodoistAPIAsync(self._token)
        try:
            await api.get_projects()
            return True
        except Exception:
            return False
        finally:
            await _close_api(api)
