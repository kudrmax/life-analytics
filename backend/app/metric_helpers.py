"""
Shared helpers for metric operations across routers.
"""
import asyncpg

from app.schemas import MetricDefinitionOut


async def build_metric_out(row: asyncpg.Record) -> MetricDefinitionOut:
    return MetricDefinitionOut(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        category=row["category"],
        type=row["type"],
        enabled=row["enabled"],
        sort_order=row["sort_order"],
    )


async def get_entry_value(conn: asyncpg.Connection, entry_id: int) -> bool | None:
    row = await conn.fetchrow(
        "SELECT value FROM values_bool WHERE entry_id = $1", entry_id
    )
    return row["value"] if row else None


async def insert_value(conn: asyncpg.Connection, entry_id: int, value: bool):
    await conn.execute(
        "INSERT INTO values_bool (entry_id, value) VALUES ($1, $2)",
        entry_id, value,
    )


async def update_value(conn: asyncpg.Connection, entry_id: int, value: bool):
    await conn.execute(
        "UPDATE values_bool SET value = $1 WHERE entry_id = $2",
        value, entry_id,
    )


async def get_metric_type(conn: asyncpg.Connection, metric_id: int, user_id: int) -> str | None:
    row = await conn.fetchrow(
        "SELECT type FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, user_id,
    )
    return row["type"] if row else None
