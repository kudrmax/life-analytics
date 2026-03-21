"""
Shared helpers for metric operations across routers.
"""
import json
from collections import defaultdict
from datetime import date as date_type, datetime, timezone

import asyncpg

from app.schemas import MetricDefinitionOut, MeasurementSlotOut

PRIVATE_MASK = "***"
PRIVATE_ICON = "🔒"


def mask_name(name: str, is_private: bool, privacy_mode: bool) -> str:
    return PRIVATE_MASK if (is_private and privacy_mode) else name


def mask_icon(icon: str, is_private: bool, privacy_mode: bool) -> str:
    return PRIVATE_ICON if (is_private and privacy_mode) else icon


def is_blocked(is_private: bool, privacy_mode: bool) -> bool:
    return is_private and privacy_mode


async def build_metric_out(
    row: asyncpg.Record,
    slots: list | None = None,
    enum_opts: list | None = None,
    privacy_mode: bool = False,
) -> MetricDefinitionOut:
    formula_raw = row.get("formula")
    if isinstance(formula_raw, str):
        formula_raw = json.loads(formula_raw)
    is_private = row.get("private", False)
    return MetricDefinitionOut(
        id=row["id"],
        slug=row["slug"],
        name=mask_name(row["name"], is_private, privacy_mode),
        description=row.get("description"),
        category_id=row.get("category_id"),
        icon=mask_icon(row.get("icon", ""), is_private, privacy_mode),
        type=row["type"],
        enabled=row["enabled"],
        sort_order=row["sort_order"],
        scale_min=row.get("scale_min"),
        scale_max=row.get("scale_max"),
        scale_step=row.get("scale_step"),
        scale_labels=json.loads(row["scale_labels"]) if row.get("scale_labels") is not None else None,
        slots=[MeasurementSlotOut(**s) for s in slots] if slots else [],
        formula=formula_raw,
        result_type=row.get("result_type"),
        provider=row.get("provider"),
        metric_key=row.get("metric_key"),
        value_type=row.get("value_type"),
        filter_name=row.get("filter_name"),
        filter_query=row.get("filter_query"),
        activitywatch_category_id=row.get("activitywatch_category_id"),
        config_app_name=row.get("config_app_name"),
        enum_options=enum_opts,
        multi_select=row.get("multi_select"),
        private=is_private,
        hide_in_cards=row.get("hide_in_cards", False),
        condition_metric_id=row.get("condition_metric_id"),
        condition_type=row.get("condition_type"),
        condition_value=json.loads(row["condition_value"]) if row.get("condition_value") is not None else None,
    )


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
    elif metric_type == "duration":
        row = await conn.fetchrow(
            "SELECT value FROM values_duration WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        return row["value"]
    elif metric_type == "enum":
        row = await conn.fetchrow(
            "SELECT selected_option_ids FROM values_enum WHERE entry_id = $1", entry_id
        )
        if not row:
            return None
        return list(row["selected_option_ids"])
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
):
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


def format_display_value(
    value: bool | str | int | list[int] | float | None,
    metric_type: str,
    result_type: str | None = None,
    enum_options: list[dict] | None = None,
    scale_labels: dict[str, str] | None = None,
) -> str:
    """Format a raw metric value into a human-readable display string."""
    if value is None:
        return "—"

    if metric_type == "enum":
        if not isinstance(value, list):
            return "—"
        if enum_options:
            id_to_label = {opt["id"]: opt["label"] for opt in enum_options}
            return ", ".join(id_to_label.get(oid, str(oid)) for oid in value)
        return ", ".join(str(v) for v in value)

    if metric_type == "computed":
        rt = result_type or "float"
        if rt == "bool":
            return "Да" if value else "Нет"
        if rt in ("time", "duration"):
            return str(value)
        if rt == "int":
            return str(round(value)) if isinstance(value, (int, float)) else str(value)
        # float
        return f"{value:.2f}" if isinstance(value, float) else str(value)

    if metric_type == "integration":
        return str(value)

    if metric_type == "duration":
        minutes = int(value)
        h, m = divmod(minutes, 60)
        if h > 0:
            return f"{h}ч {m}м"
        return f"{m}м"

    if metric_type == "time":
        return str(value) if value else "—"

    if metric_type in ("number", "scale"):
        if metric_type == "scale" and scale_labels and str(value) in scale_labels:
            return scale_labels[str(value)]
        return str(value) if value is not None else "—"

    # bool
    return "Да" if value else "Нет"


def _parse_time(value: str, entry_date: date_type | None) -> datetime:
    """Parse 'HH:MM' string and combine with entry_date into a TIMESTAMPTZ."""
    parts = value.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    d = entry_date or date_type.today()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
