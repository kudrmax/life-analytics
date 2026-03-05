from datetime import date as date_type

import asyncpg

from app.encryption import decrypt_token
from app.integrations.todoist.client import TodoistClient
from app.metric_helpers import insert_value, update_value, resolve_storage_type


async def fetch_and_store(conn: asyncpg.Connection, user_id: int, for_date: date_type, metric_id: int | None = None) -> dict:
    """Fetch data from Todoist and upsert entries for enabled Todoist metrics.

    If metric_id is given, only that metric is fetched.
    Returns {"results": [...], "errors": [...]}.
    """
    row = await conn.fetchrow(
        "SELECT encrypted_token FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
        user_id,
    )
    if not row:
        raise ValueError("Todoist not connected")

    access_token = decrypt_token(row["encrypted_token"])

    query = """SELECT md.id, ic.metric_key, ic.value_type,
                  ifc.filter_name, iqc.filter_query
           FROM metric_definitions md
           JOIN integration_config ic ON ic.metric_id = md.id
           LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
           LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
           WHERE md.user_id = $1 AND ic.provider = 'todoist' AND md.enabled = TRUE"""
    params = [user_id]
    if metric_id is not None:
        query += " AND md.id = $2"
        params.append(metric_id)
    metric_rows = await conn.fetch(query, *params)
    if not metric_rows:
        raise ValueError("No Todoist metrics found")

    client = TodoistClient(access_token)

    # Cache: compute each value type once where possible
    completed_count = None
    results = []
    errors = []

    for mr in metric_rows:
        metric_id = mr["id"]
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
                    errors.append({"metric_id": metric_id, "error": "Имя фильтра не задано"})
                    continue
                query = await client.get_filter_query_by_name(filter_name)
                if query is None:
                    errors.append({"metric_id": metric_id, "error": f"Фильтр '{filter_name}' не найден в Todoist"})
                    continue
                value = await client.get_tasks_count_by_query(query)

            elif metric_key == "query_tasks_count":
                filter_query = mr["filter_query"]
                if not filter_query:
                    errors.append({"metric_id": metric_id, "error": "Запрос не задан"})
                    continue
                value = await client.get_tasks_count_by_query(filter_query)

            else:
                errors.append({"metric_id": metric_id, "error": f"Неизвестный metric_key: {metric_key}"})
                continue

        except Exception as e:
            errors.append({"metric_id": metric_id, "error": str(e)})
            continue

        # Upsert entry
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND slot_id IS NULL",
                metric_id, user_id, for_date,
            )
            if existing:
                await update_value(conn, existing["id"], value, storage_type, metric_id=metric_id)
            else:
                entry_id = await conn.fetchval(
                    "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
                    metric_id, user_id, for_date,
                )
                await insert_value(conn, entry_id, value, storage_type, entry_date=for_date, metric_id=metric_id)

        results.append({"metric_id": metric_id, "value": value})

    return {"results": results, "errors": errors}
