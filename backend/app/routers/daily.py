import json
from statistics import mean

from fastapi import APIRouter, Depends
import aiosqlite

from app.database import get_db

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db)):
    # Get all enabled metrics
    metrics_rows = await db.execute(
        "SELECT * FROM metric_configs WHERE enabled = 1 ORDER BY sort_order, rowid"
    )
    metrics = await metrics_rows.fetchall()

    # Get all entries for date
    entries_rows = await db.execute(
        "SELECT * FROM entries WHERE date = ? ORDER BY timestamp", (date,)
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
