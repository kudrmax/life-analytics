"""
Shared helpers for metric operations across routers.
Handles config table reads/writes and value table reads/writes.
"""
from decimal import Decimal

import asyncpg

from app.schemas import MetricDefinitionOut


CONFIG_TABLE_MAP = {
    "bool": "config_bool",
    "number": "config_number",
    "scale": "config_scale",
    "time": "config_time",
}

VALUE_TABLE_MAP = {
    "bool": "values_bool",
    "number": "values_number",
    "scale": "values_scale",
    "time": "values_time",
}


def _decimal_to_num(v):
    """Convert Decimal to int or float for JSON serialization."""
    if isinstance(v, Decimal):
        if v == int(v):
            return int(v)
        return float(v)
    return v


async def get_config_for_metric(conn: asyncpg.Connection, metric_id: int, metric_type: str) -> dict:
    table = CONFIG_TABLE_MAP.get(metric_type)
    if not table:
        return {}

    row = await conn.fetchrow(f"SELECT * FROM {table} WHERE metric_id = $1", metric_id)
    if not row:
        return {}

    config = dict(row)
    config.pop("metric_id", None)

    # Convert Decimal values
    for k, v in config.items():
        config[k] = _decimal_to_num(v)

    return config


async def get_measurement_labels(conn: asyncpg.Connection, metric_id: int) -> list[str]:
    rows = await conn.fetch(
        "SELECT label FROM measurement_labels WHERE metric_id = $1 ORDER BY measurement_number",
        metric_id,
    )
    return [r["label"] for r in rows]


async def build_metric_out(conn: asyncpg.Connection, row: asyncpg.Record) -> MetricDefinitionOut:
    metric_id = row["id"]
    metric_type = row["type"]

    config = await get_config_for_metric(conn, metric_id, metric_type)
    labels = await get_measurement_labels(conn, metric_id)

    return MetricDefinitionOut(
        id=metric_id,
        slug=row["slug"],
        name=row["name"],
        category=row["category"],
        type=metric_type,
        enabled=row["enabled"],
        sort_order=row["sort_order"],
        measurements_per_day=row["measurements_per_day"],
        measurement_labels=labels,
        config=config,
    )


async def insert_config(conn: asyncpg.Connection, metric_id: int, metric_type: str, config: dict):
    if metric_type == "bool":
        await conn.execute(
            "INSERT INTO config_bool (metric_id, true_label, false_label) VALUES ($1, $2, $3)",
            metric_id,
            config.get("true_label", "Да"),
            config.get("false_label", "Нет"),
        )
    elif metric_type == "number":
        await conn.execute(
            """INSERT INTO config_number
               (metric_id, min_value, max_value, step, unit_label, display_mode, bool_label, number_label)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            metric_id,
            config.get("min_value"),
            config.get("max_value"),
            config.get("step", 1),
            config.get("unit_label", ""),
            config.get("display_mode", "number_only"),
            config.get("bool_label", ""),
            config.get("number_label", ""),
        )
    elif metric_type == "scale":
        await conn.execute(
            "INSERT INTO config_scale (metric_id, min_value, max_value, step) VALUES ($1, $2, $3, $4)",
            metric_id,
            config.get("min_value", 1),
            config.get("max_value", 5),
            config.get("step", 1),
        )
    elif metric_type == "time":
        await conn.execute(
            "INSERT INTO config_time (metric_id, placeholder) VALUES ($1, $2)",
            metric_id,
            config.get("placeholder", ""),
        )


async def update_config(conn: asyncpg.Connection, metric_id: int, metric_type: str, config: dict):
    await conn.execute(f"DELETE FROM {CONFIG_TABLE_MAP[metric_type]} WHERE metric_id = $1", metric_id)
    await insert_config(conn, metric_id, metric_type, config)


async def insert_measurement_labels(conn: asyncpg.Connection, metric_id: int, labels: list[str]):
    for i, label in enumerate(labels, start=1):
        await conn.execute(
            "INSERT INTO measurement_labels (metric_id, measurement_number, label) VALUES ($1, $2, $3)",
            metric_id, i, label,
        )


async def replace_measurement_labels(conn: asyncpg.Connection, metric_id: int, labels: list[str]):
    await conn.execute("DELETE FROM measurement_labels WHERE metric_id = $1", metric_id)
    await insert_measurement_labels(conn, metric_id, labels)


def build_value_dict(metric_type: str, value_row: asyncpg.Record | None) -> dict:
    """Convert a value table row into the API response dict."""
    if not value_row:
        return {}

    if metric_type == "bool":
        return {"value": value_row["value"]}
    elif metric_type == "number":
        return {
            "bool_value": value_row["bool_value"],
            "number_value": _decimal_to_num(value_row["number_value"]),
        }
    elif metric_type == "scale":
        return {"value": value_row["value"]}
    elif metric_type == "time":
        t = value_row["value"]
        return {"value": t.strftime("%H:%M") if t else None}
    return {}


async def insert_value(conn: asyncpg.Connection, entry_id: int, metric_type: str, value: dict):
    if metric_type == "bool":
        await conn.execute(
            "INSERT INTO values_bool (entry_id, value) VALUES ($1, $2)",
            entry_id, bool(value.get("value", False)),
        )
    elif metric_type == "number":
        await conn.execute(
            "INSERT INTO values_number (entry_id, bool_value, number_value) VALUES ($1, $2, $3)",
            entry_id, value.get("bool_value"), value.get("number_value"),
        )
    elif metric_type == "scale":
        await conn.execute(
            "INSERT INTO values_scale (entry_id, value) VALUES ($1, $2)",
            entry_id, int(value.get("value", 0)),
        )
    elif metric_type == "time":
        import datetime
        time_str = value.get("value", "00:00")
        parts = time_str.split(":")
        t = datetime.time(int(parts[0]), int(parts[1]))
        await conn.execute(
            "INSERT INTO values_time (entry_id, value) VALUES ($1, $2)",
            entry_id, t,
        )


async def update_value(conn: asyncpg.Connection, entry_id: int, metric_type: str, value: dict):
    table = VALUE_TABLE_MAP[metric_type]
    await conn.execute(f"DELETE FROM {table} WHERE entry_id = $1", entry_id)
    await insert_value(conn, entry_id, metric_type, value)


async def get_metric_type(conn: asyncpg.Connection, metric_id: int, user_id: int) -> str | None:
    row = await conn.fetchrow(
        "SELECT type FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, user_id,
    )
    return row["type"] if row else None


async def seed_metrics_for_user(conn: asyncpg.Connection, user_id: int, metrics: list[dict]):
    """Insert default metrics for a new user inside an existing transaction."""
    for i, m in enumerate(metrics):
        metric_id = await conn.fetchval(
            """INSERT INTO metric_definitions
               (user_id, slug, name, category, type, enabled, sort_order, measurements_per_day)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING id""",
            user_id,
            m["slug"],
            m["name"],
            m.get("category", ""),
            m["type"],
            m.get("enabled", True),
            m.get("sort_order", i),
            m.get("measurements_per_day", 1),
        )

        await insert_config(conn, metric_id, m["type"], m.get("config", {}))

        labels = m.get("measurement_labels", [])
        if labels:
            await insert_measurement_labels(conn, metric_id, labels)
