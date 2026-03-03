from collections import defaultdict
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

    metric_ids = [m["id"] for m in metrics]

    # Get enabled slots for all metrics
    enabled_slots_rows = await db.fetch(
        """SELECT ms.id, ms.metric_id, ms.label, ms.sort_order
           FROM measurement_slots ms
           WHERE ms.metric_id = ANY($1) AND ms.enabled = TRUE
           ORDER BY ms.metric_id, ms.sort_order""",
        metric_ids,
    ) if metric_ids else []

    enabled_slots: dict[int, list] = defaultdict(list)
    for r in enabled_slots_rows:
        enabled_slots[r["metric_id"]].append(r)

    # Get disabled slots that have entries on this date
    disabled_slot_ids_with_entries = []
    if metric_ids:
        disabled_slot_ids_with_entries = await db.fetch(
            """SELECT DISTINCT ms.id, ms.metric_id, ms.label, ms.sort_order
               FROM measurement_slots ms
               JOIN entries e ON e.slot_id = ms.id AND e.date = $1 AND e.user_id = $2
               WHERE ms.metric_id = ANY($3) AND ms.enabled = FALSE
               ORDER BY ms.metric_id, ms.sort_order""",
            d, current_user["id"], metric_ids,
        )

    disabled_with_entries: dict[int, list] = defaultdict(list)
    for r in disabled_slot_ids_with_entries:
        disabled_with_entries[r["metric_id"]].append(r)

    # Build entries lookup: metric_id -> list of entries (multiple for multi-slot)
    entries_by_metric: dict[int, list] = defaultdict(list)
    for e in entries:
        entries_by_metric[e["metric_id"]].append(e)

    result = []
    for m in metrics:
        mid = m["id"]
        metric_entries = entries_by_metric.get(mid, [])
        slots = enabled_slots.get(mid, [])
        extra_disabled = disabled_with_entries.get(mid, [])

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
            "slots": None,
        }

        if slots or extra_disabled:
            # Multi-slot metric: combine enabled + disabled-with-entries
            all_visible = list(slots) + list(extra_disabled)
            all_visible.sort(key=lambda s: s["sort_order"])

            # Build slot_id -> entry lookup
            entry_by_slot: dict[int, dict] = {}
            for e in metric_entries:
                if e["slot_id"] is not None:
                    entry_by_slot[e["slot_id"]] = e

            slot_items = []
            for s in all_visible:
                entry = entry_by_slot.get(s["id"])
                slot_item = {
                    "slot_id": s["id"],
                    "label": s["label"],
                    "entry": None,
                }
                if entry:
                    value = await get_entry_value(db, entry["id"], m["type"])
                    slot_item["entry"] = {
                        "id": entry["id"],
                        "recorded_at": str(entry["recorded_at"]),
                        "value": value,
                    }
                    # Scale context from stored values
                    if m["type"] == "scale":
                        vs = await db.fetchrow(
                            "SELECT scale_min, scale_max, scale_step FROM values_scale WHERE entry_id = $1",
                            entry["id"],
                        )
                        if vs:
                            slot_item["entry"]["scale_min"] = vs["scale_min"]
                            slot_item["entry"]["scale_max"] = vs["scale_max"]
                            slot_item["entry"]["scale_step"] = vs["scale_step"]

                slot_items.append(slot_item)

            item["slots"] = slot_items
        else:
            # Single entry metric (no slots)
            entry = None
            for e in metric_entries:
                if e["slot_id"] is None:
                    entry = e
                    break

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
