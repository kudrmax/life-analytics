from datetime import date as date_type

import asyncpg

from app.encryption import decrypt_token
from app.integrations.todoist.client import TodoistClient
from app.metric_helpers import insert_value, update_value, resolve_storage_type


async def fetch_and_store(conn: asyncpg.Connection, user_id: int, for_date: date_type) -> int:
    """Fetch data from Todoist and upsert entries for all enabled Todoist metrics.

    Returns the count of completed tasks.
    """
    row = await conn.fetchrow(
        "SELECT encrypted_token FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
        user_id,
    )
    if not row:
        raise ValueError("Todoist not connected")

    access_token = decrypt_token(row["encrypted_token"])

    metric_rows = await conn.fetch(
        """SELECT md.id, ic.metric_key, ic.value_type FROM metric_definitions md
           JOIN integration_config ic ON ic.metric_id = md.id
           WHERE md.user_id = $1 AND ic.provider = 'todoist' AND md.enabled = TRUE""",
        user_id,
    )
    if not metric_rows:
        raise ValueError("No Todoist metrics found")

    # Fetch data once from Todoist
    client = TodoistClient(access_token)
    count = await client.get_completed_tasks_count(for_date)

    # Compute values per metric_key (for now all use the same count)
    values_by_key = {
        'completed_tasks_count': count,
    }

    async with conn.transaction():
        for mr in metric_rows:
            metric_id = mr["id"]
            value = values_by_key.get(mr["metric_key"])
            if value is None:
                continue
            storage_type = mr["value_type"]

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

    return count
