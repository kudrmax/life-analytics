from datetime import date as date_type

import asyncpg

from app.encryption import decrypt_token
from app.integrations.todoist.client import TodoistClient


async def fetch_and_store(conn: asyncpg.Connection, user_id: int, for_date: date_type) -> int:
    """Fetch completed tasks count from Todoist and upsert entry.

    Returns the count of completed tasks.
    """
    # Get encrypted token
    row = await conn.fetchrow(
        "SELECT encrypted_token FROM user_integrations WHERE user_id = $1 AND provider = 'todoist' AND enabled = TRUE",
        user_id,
    )
    if not row:
        raise ValueError("Todoist not connected")

    access_token = decrypt_token(row["encrypted_token"])

    # Find the integration metric
    metric_row = await conn.fetchrow(
        """SELECT md.id FROM metric_definitions md
           JOIN integration_config ic ON ic.metric_id = md.id
           WHERE md.user_id = $1 AND ic.provider = 'todoist' AND md.enabled = TRUE""",
        user_id,
    )
    if not metric_row:
        raise ValueError("Todoist metric not found")

    metric_id = metric_row["id"]

    # Fetch data from Todoist
    client = TodoistClient(access_token)
    count = await client.get_completed_tasks_count(for_date)

    # Upsert entry
    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND slot_id IS NULL",
            metric_id, user_id, for_date,
        )
        if existing:
            await conn.execute(
                "UPDATE values_number SET value = $1 WHERE entry_id = $2",
                count, existing["id"],
            )
        else:
            entry_id = await conn.fetchval(
                "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
                metric_id, user_id, for_date,
            )
            await conn.execute(
                "INSERT INTO values_number (entry_id, value) VALUES ($1, $2)",
                entry_id, count,
            )

    return count
