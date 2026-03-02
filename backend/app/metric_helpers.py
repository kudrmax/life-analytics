"""
Shared helpers for metric operations across routers.
"""
from datetime import date as date_type, datetime, timezone

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


async def get_entry_value(
    conn: asyncpg.Connection, entry_id: int, metric_type: str
) -> bool | str | None:
    if metric_type == "time":
        row = await conn.fetchrow(
            "SELECT value FROM values_time WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        ts = row["value"]
        return f"{ts.hour:02d}:{ts.minute:02d}"
    else:
        row = await conn.fetchrow(
            "SELECT value FROM values_bool WHERE entry_id = $1", entry_id
        )
        return row["value"] if row else None


async def insert_value(
    conn: asyncpg.Connection,
    entry_id: int,
    value: bool | str,
    metric_type: str,
    entry_date: date_type | None = None,
):
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "INSERT INTO values_time (entry_id, value) VALUES ($1, $2)",
            entry_id, ts,
        )
    else:
        await conn.execute(
            "INSERT INTO values_bool (entry_id, value) VALUES ($1, $2)",
            entry_id, value,
        )


async def update_value(
    conn: asyncpg.Connection,
    entry_id: int,
    value: bool | str,
    metric_type: str,
    entry_date: date_type | None = None,
):
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "UPDATE values_time SET value = $1 WHERE entry_id = $2",
            ts, entry_id,
        )
    else:
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


def _parse_time(value: str, entry_date: date_type | None) -> datetime:
    """Parse 'HH:MM' string and combine with entry_date into a TIMESTAMPTZ."""
    parts = value.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    d = entry_date or date_type.today()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
