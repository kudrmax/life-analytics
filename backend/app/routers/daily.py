import json
from statistics import mean

from fastapi import APIRouter, Depends
import aiosqlite

from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    # Get all enabled metrics for user
    metrics_rows = await db.execute(
        "SELECT * FROM metric_configs WHERE enabled = 1 AND user_id = ? ORDER BY sort_order, rowid",
        (current_user["id"],)
    )
    metrics = await metrics_rows.fetchall()

    # Get all entries for date and user
    entries_rows = await db.execute(
        "SELECT * FROM entries WHERE date = ? AND user_id = ? ORDER BY timestamp", (date, current_user["id"])
    )
    entries = await entries_rows.fetchall()

    # Group entries by metric_id
    entries_by_metric: dict[str, list] = {}
    for e in entries:
        mid = e["metric_id"]
        entries_by_metric.setdefault(mid, []).append(e)

    result = []
    for m in metrics:
        mid = m["id"]
        metric_entries = entries_by_metric.get(mid, [])
        config = json.loads(m["config_json"])

        item = {
            "metric_id": mid,
            "name": m["name"],
            "category": m["category"],
            "type": m["type"],
            "frequency": m["frequency"],
            "source": m["source"],
            "config": config,
            "entries": [],
            "summary": None,
        }

        parsed_entries = []
        for e in metric_entries:
            val = json.loads(e["value_json"])
            parsed_entries.append({
                "id": e["id"],
                "timestamp": e["timestamp"],
                "value": val,
            })
        item["entries"] = parsed_entries

        # Aggregate for multiple-frequency metrics
        if m["frequency"] == "multiple" and parsed_entries:
            values = [
                e["value"].get("value")
                for e in parsed_entries
                if e["value"].get("value") is not None
            ]
            numeric = [v for v in values if isinstance(v, (int, float))]
            if numeric:
                item["summary"] = {
                    "avg": round(mean(numeric), 2),
                    "min": min(numeric),
                    "max": max(numeric),
                    "count": len(numeric),
                }

        result.append(item)

    return {"date": date, "metrics": result}
