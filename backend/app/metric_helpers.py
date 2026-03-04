"""
Shared helpers for metric operations across routers.
"""
import json
from collections import defaultdict
from datetime import date as date_type, datetime, timezone

import asyncpg

from app.schemas import MetricDefinitionOut, MeasurementSlotOut


async def build_metric_out(row: asyncpg.Record, slots: list | None = None) -> MetricDefinitionOut:
    formula_raw = row.get("formula")
    if isinstance(formula_raw, str):
        formula_raw = json.loads(formula_raw)
    return MetricDefinitionOut(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        category=row["category"],
        icon=row.get("icon", ""),
        type=row["type"],
        enabled=row["enabled"],
        sort_order=row["sort_order"],
        scale_min=row.get("scale_min"),
        scale_max=row.get("scale_max"),
        scale_step=row.get("scale_step"),
        slots=[MeasurementSlotOut(**s) for s in slots] if slots else [],
        formula=formula_raw,
        result_type=row.get("result_type"),
        provider=row.get("provider"),
        metric_key=row.get("metric_key"),
    )


async def get_metric_slots(
    conn: asyncpg.Connection,
    metric_ids: list[int],
    enabled_only: bool = True,
) -> dict[int, list]:
    """Return {metric_id: [{id, label, sort_order}, ...]}."""
    condition = "AND ms.enabled = TRUE" if enabled_only else ""
    rows = await conn.fetch(
        f"""SELECT ms.id, ms.metric_id, ms.label, ms.sort_order
            FROM measurement_slots ms
            WHERE ms.metric_id = ANY($1) {condition}
            ORDER BY ms.metric_id, ms.sort_order""",
        metric_ids,
    )
    result: dict[int, list] = defaultdict(list)
    for r in rows:
        result[r["metric_id"]].append({
            "id": r["id"], "label": r["label"], "sort_order": r["sort_order"],
        })
    return result


async def get_entry_value(
    conn: asyncpg.Connection, entry_id: int, metric_type: str
) -> bool | str | int | None:
    if metric_type == "time":
        row = await conn.fetchrow(
            "SELECT value FROM values_time WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        ts = row["value"]
        return f"{ts.hour:02d}:{ts.minute:02d}"
    elif metric_type in ("number", "integration"):
        row = await conn.fetchrow(
            "SELECT value FROM values_number WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        return row["value"]
    elif metric_type == "scale":
        row = await conn.fetchrow(
            "SELECT value FROM values_scale WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        return row["value"]
    else:
        row = await conn.fetchrow(
            "SELECT value FROM values_bool WHERE entry_id = $1", entry_id
        )
        return row["value"] if row else None


async def insert_value(
    conn: asyncpg.Connection,
    entry_id: int,
    value: bool | str | int,
    metric_type: str,
    entry_date: date_type | None = None,
    metric_id: int | None = None,
):
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "INSERT INTO values_time (entry_id, value) VALUES ($1, $2)",
            entry_id, ts,
        )
    elif metric_type in ("number", "integration"):
        await conn.execute(
            "INSERT INTO values_number (entry_id, value) VALUES ($1, $2)",
            entry_id, int(value),
        )
    elif metric_type == "scale":
        cfg = await conn.fetchrow(
            "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
            metric_id,
        )
        s_min = cfg["scale_min"] if cfg else 1
        s_max = cfg["scale_max"] if cfg else 5
        s_step = cfg["scale_step"] if cfg else 1
        await conn.execute(
            "INSERT INTO values_scale (entry_id, value, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4, $5)",
            entry_id, int(value), s_min, s_max, s_step,
        )
    else:
        await conn.execute(
            "INSERT INTO values_bool (entry_id, value) VALUES ($1, $2)",
            entry_id, value,
        )


async def update_value(
    conn: asyncpg.Connection,
    entry_id: int,
    value: bool | str | int,
    metric_type: str,
    entry_date: date_type | None = None,
    metric_id: int | None = None,
):
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "UPDATE values_time SET value = $1 WHERE entry_id = $2",
            ts, entry_id,
        )
    elif metric_type in ("number", "integration"):
        await conn.execute(
            "UPDATE values_number SET value = $1 WHERE entry_id = $2",
            int(value), entry_id,
        )
    elif metric_type == "scale":
        await conn.execute(
            "UPDATE values_scale SET value = $1 WHERE entry_id = $2",
            int(value), entry_id,
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
