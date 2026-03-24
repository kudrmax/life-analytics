from __future__ import annotations

from datetime import date as date_type
from typing import TYPE_CHECKING

from app.encryption import decrypt_token
from app.integrations.todoist.client import TodoistClient
from app.repositories.entry_repository import EntryRepository

if TYPE_CHECKING:
    from app.repositories.integrations_repository import IntegrationsRepository


async def fetch_and_store(repo: IntegrationsRepository, for_date: date_type, metric_id: int | None = None) -> dict:
    """Fetch data from Todoist and upsert entries for enabled Todoist metrics.

    If metric_id is given, only that metric is fetched.
    Returns {"results": [...], "errors": [...]}.
    """
    row = await repo.get_todoist_token()
    if not row:
        raise ValueError("Todoist not connected")

    access_token = decrypt_token(row["encrypted_token"])
    entry_repo = EntryRepository(repo.conn, repo.user_id)

    metric_rows = await repo.get_todoist_metrics(metric_id)
    if not metric_rows:
        raise ValueError("No Todoist metrics found")

    client = TodoistClient(access_token)

    # Cache: compute each value type once where possible
    completed_count = None
    results = []
    errors = []

    for mr in metric_rows:
        mid = mr["id"]
        metric_key = mr["metric_key"]
        storage_type = mr["value_type"]
        value = None

        try:
            if metric_key == "completed_tasks_count":
                if completed_count is None:
                    completed_count = await client.get_completed_tasks_count(for_date)
                value = completed_count

            elif metric_key == "filter_tasks_count":
                filter_name = mr["filter_name"]
                if not filter_name:
                    errors.append({"metric_id": mid, "error": "Имя фильтра не задано"})
                    continue
                query = await client.get_filter_query_by_name(filter_name)
                if query is None:
                    errors.append({"metric_id": mid, "error": f"Фильтр '{filter_name}' не найден в Todoist"})
                    continue
                value = await client.get_tasks_count_by_query(query)

            elif metric_key == "query_tasks_count":
                filter_query = mr["filter_query"]
                if not filter_query:
                    errors.append({"metric_id": mid, "error": "Запрос не задан"})
                    continue
                value = await client.get_tasks_count_by_query(filter_query)

            else:
                errors.append({"metric_id": mid, "error": f"Неизвестный metric_key: {metric_key}"})
                continue

        except Exception as e:
            errors.append({"metric_id": mid, "error": str(e)})
            continue

        # Upsert entry
        async with repo.conn.transaction():
            existing = await repo.get_entry_by_metric_date(mid, for_date)
            if existing:
                await entry_repo.update_value(existing["id"], value, storage_type, metric_id=mid)
            else:
                entry_id = await repo.create_entry(mid, for_date)
                await entry_repo.insert_value(entry_id, value, storage_type, entry_date=for_date, metric_id=mid)

        results.append({"metric_id": mid, "value": value})

    return {"results": results, "errors": errors}
