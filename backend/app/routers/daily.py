from datetime import date as date_type

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import get_entry_value

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    metrics = await db.fetch(
        "SELECT * FROM metric_definitions WHERE enabled = TRUE AND user_id = $1 ORDER BY sort_order, id",
        current_user["id"],
    )

    d = date_type.fromisoformat(date)
    entries = await db.fetch(
        "SELECT * FROM entries WHERE date = $1 AND user_id = $2",
        d, current_user["id"],
    )

    entries_by_metric: dict[int, dict] = {}
    for e in entries:
        entries_by_metric[e["metric_id"]] = e

    result = []
    for m in metrics:
        mid = m["id"]
        entry = entries_by_metric.get(mid)

        item = {
            "metric_id": mid,
            "slug": m["slug"],
            "name": m["name"],
            "category": m["category"],
            "type": m["type"],
            "entry": None,
        }

        if entry:
            value = await get_entry_value(db, entry["id"], m["type"])
            item["entry"] = {
                "id": entry["id"],
                "recorded_at": str(entry["recorded_at"]),
                "value": value,
            }

        result.append(item)

    return {"date": date, "metrics": result}
