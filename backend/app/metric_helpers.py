"""Backward-compatibility shim — re-exports from canonical locations.

New code should import from:
  - app.domain.privacy (mask_name, mask_icon, is_blocked, PRIVATE_MASK, PRIVATE_ICON)
  - app.domain.formatters (format_display_value)
  - app.services.metric_builder (build_metric_out)
  - app.repositories.entry_repository.EntryRepository (get_entry_value, insert_value, ...)
  - app.repositories.metric_repository.MetricRepository (get_slots_for_metrics, ...)

This module exists solely so that existing unit tests continue to work
without modification — the standalone function signatures are preserved.
"""

# --- Re-exports: pure domain functions ---
from app.domain.privacy import (  # noqa: F401
    mask_name,
    mask_icon,
    is_blocked,
    PRIVATE_MASK,
    PRIVATE_ICON,
)

from app.domain.formatters import format_display_value  # noqa: F401

from app.services.metric_builder import build_metric_out  # noqa: F401

# --- Legacy standalone functions (kept for backward-compat with tests) ---

from collections import defaultdict
from datetime import date as date_type, datetime, timezone

import asyncpg


async def get_metric_slots(
    conn: asyncpg.Connection,
    metric_ids: list[int],
    enabled_only: bool = True,
) -> dict[int, list]:
    """Return {metric_id: [{id, label, sort_order, category_id}, ...]}."""
    condition = "AND msl.enabled = TRUE" if enabled_only else ""
    rows = await conn.fetch(
        f"""SELECT msl.metric_id, ms.id, ms.label, ms.sort_order, msl.category_id
            FROM metric_slots msl
            JOIN measurement_slots ms ON ms.id = msl.slot_id
            WHERE msl.metric_id = ANY($1) {condition}
            ORDER BY msl.metric_id, ms.sort_order""",
        metric_ids,
    )
    result: dict[int, list] = defaultdict(list)
    for r in rows:
        result[r["metric_id"]].append({
            "id": r["id"], "label": r["label"], "sort_order": r["sort_order"],
            "category_id": r["category_id"],
        })
    return result


async def get_enum_options(
    conn: asyncpg.Connection,
    metric_ids: list[int],
    enabled_only: bool = True,
) -> dict[int, list]:
    """Return {metric_id: [{id, label, sort_order, enabled}, ...]}."""
    condition = "AND eo.enabled = TRUE" if enabled_only else ""
    rows = await conn.fetch(
        f"""SELECT eo.id, eo.metric_id, eo.label, eo.sort_order, eo.enabled
            FROM enum_options eo
            WHERE eo.metric_id = ANY($1) {condition}
            ORDER BY eo.metric_id, eo.sort_order""",
        metric_ids,
    )
    result: dict[int, list] = defaultdict(list)
    for r in rows:
        result[r["metric_id"]].append({
            "id": r["id"], "label": r["label"],
            "sort_order": r["sort_order"], "enabled": r["enabled"],
        })
    return result


async def resolve_storage_type(conn: asyncpg.Connection, metric_id: int, metric_type: str) -> str:
    """For integration metrics, resolve the actual storage type from integration_config."""
    if metric_type != "integration":
        return metric_type
    row = await conn.fetchrow(
        "SELECT value_type FROM integration_config WHERE metric_id = $1", metric_id
    )
    return row["value_type"] if row else "number"


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
    elif metric_type == "number":
        row = await conn.fetchrow(
            "SELECT value FROM values_number WHERE entry_id = $1", entry_id
        )
        return row["value"] if row else None
    elif metric_type == "scale":
        row = await conn.fetchrow(
            "SELECT value FROM values_scale WHERE entry_id = $1", entry_id
        )
        return row["value"] if row else None
    elif metric_type == "duration":
        row = await conn.fetchrow(
            "SELECT value FROM values_duration WHERE entry_id = $1", entry_id
        )
        return row["value"] if row else None
    elif metric_type == "enum":
        row = await conn.fetchrow(
            "SELECT selected_option_ids FROM values_enum WHERE entry_id = $1", entry_id
        )
        return list(row["selected_option_ids"]) if row else None
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
) -> None:
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "INSERT INTO values_time (entry_id, value) VALUES ($1, $2)",
            entry_id, ts,
        )
    elif metric_type == "number":
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
    elif metric_type == "duration":
        await conn.execute(
            "INSERT INTO values_duration (entry_id, value) VALUES ($1, $2)",
            entry_id, int(value),
        )
    elif metric_type == "enum":
        option_ids = value if isinstance(value, list) else [value]
        await conn.execute(
            "INSERT INTO values_enum (entry_id, selected_option_ids) VALUES ($1, $2)",
            entry_id, option_ids,
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
) -> None:
    if metric_type == "time":
        ts = _parse_time(value, entry_date)
        await conn.execute(
            "UPDATE values_time SET value = $1 WHERE entry_id = $2",
            ts, entry_id,
        )
    elif metric_type == "number":
        await conn.execute(
            "UPDATE values_number SET value = $1 WHERE entry_id = $2",
            int(value), entry_id,
        )
    elif metric_type == "scale":
        await conn.execute(
            "UPDATE values_scale SET value = $1 WHERE entry_id = $2",
            int(value), entry_id,
        )
    elif metric_type == "duration":
        await conn.execute(
            "UPDATE values_duration SET value = $1 WHERE entry_id = $2",
            int(value), entry_id,
        )
    elif metric_type == "enum":
        option_ids = value if isinstance(value, list) else [value]
        await conn.execute(
            "UPDATE values_enum SET selected_option_ids = $1 WHERE entry_id = $2",
            option_ids, entry_id,
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
