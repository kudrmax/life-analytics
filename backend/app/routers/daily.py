from datetime import date as date_type
from statistics import mean

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import (
    get_config_for_metric, get_measurement_labels,
    build_value_dict, VALUE_TABLE_MAP, _decimal_to_num,
)

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    # Get all enabled metrics for user
    metrics = await db.fetch(
        "SELECT * FROM metric_definitions WHERE enabled = TRUE AND user_id = $1 ORDER BY sort_order, id",
        current_user["id"],
    )

    # Get all entries for date and user
    d = date_type.fromisoformat(date)
    entries = await db.fetch(
        "SELECT * FROM entries WHERE date = $1 AND user_id = $2 ORDER BY measurement_number",
        d, current_user["id"],
    )

    # Group entries by metric_id
    entries_by_metric: dict[int, list] = {}
    for e in entries:
        entries_by_metric.setdefault(e["metric_id"], []).append(e)

    result = []
    for m in metrics:
        mid = m["id"]
        metric_type = m["type"]
        metric_entries = entries_by_metric.get(mid, [])

        config = await get_config_for_metric(db, mid, metric_type)
        labels = await get_measurement_labels(db, mid)

        item = {
            "metric_id": mid,
            "slug": m["slug"],
            "name": m["name"],
            "category": m["category"],
            "type": metric_type,
            "measurements_per_day": m["measurements_per_day"],
            "measurement_labels": labels,
            "config": config,
            "entries": [],
            "summary": None,
        }

        value_table = VALUE_TABLE_MAP[metric_type]
        parsed_entries = []

        for e in metric_entries:
            val_row = await db.fetchrow(f"SELECT * FROM {value_table} WHERE entry_id = $1", e["id"])
            value = build_value_dict(metric_type, val_row)

            parsed_entries.append({
                "id": e["id"],
                "measurement_number": e["measurement_number"],
                "recorded_at": str(e["recorded_at"]),
                "value": value,
            })

        item["entries"] = parsed_entries

        # Aggregate for multi-measurement metrics
        if m["measurements_per_day"] > 1 and parsed_entries:
            numeric_values = []
            for pe in parsed_entries:
                v = pe["value"]
                if metric_type == "scale":
                    val = v.get("value")
                    if val is not None:
                        numeric_values.append(float(val))
                elif metric_type == "number":
                    val = v.get("number_value")
                    if val is not None:
                        numeric_values.append(float(val))

            if numeric_values:
                item["summary"] = {
                    "avg": round(mean(numeric_values), 2),
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "count": len(numeric_values),
                }

        result.append(item)

    return {"date": date, "metrics": result}
