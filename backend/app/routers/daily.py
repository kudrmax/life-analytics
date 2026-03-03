from datetime import date as date_type

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import get_entry_value

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    metrics = await db.fetch(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           WHERE md.enabled = TRUE AND md.user_id = $1
           ORDER BY md.sort_order, md.id""",
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
            "scale_min": m["scale_min"],
            "scale_max": m["scale_max"],
            "scale_step": m["scale_step"],
            "entry": None,
        }

        if entry:
            value = await get_entry_value(db, entry["id"], m["type"])
            item["entry"] = {
                "id": entry["id"],
                "recorded_at": str(entry["recorded_at"]),
                "value": value,
            }
            # For filled scale entries, use stored context instead of current config
            if m["type"] == "scale":
                vs = await db.fetchrow(
                    "SELECT scale_min, scale_max, scale_step FROM values_scale WHERE entry_id = $1",
                    entry["id"],
                )
                if vs:
                    item["scale_min"] = vs["scale_min"]
                    item["scale_max"] = vs["scale_max"]
                    item["scale_step"] = vs["scale_step"]

        result.append(item)

    return {"date": date, "metrics": result}
