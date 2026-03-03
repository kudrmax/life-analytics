import json
from collections import defaultdict
from datetime import date as date_type

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import get_entry_value
from app.formula import convert_metric_value, evaluate_formula


def _parse_formula(raw):
    """Parse formula from DB — may be JSON string or list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return raw

router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    metrics = await db.fetch(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                  cc.formula, cc.result_type
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
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
            "icon": m.get("icon", ""),
            "category": m["category"],
            "type": m["type"],
            "scale_min": m["scale_min"],
            "scale_max": m["scale_max"],
            "scale_step": m["scale_step"],
            "entry": None,
            "slots": None,
            "formula": _parse_formula(m.get("formula")) or None,
            "result_type": m.get("result_type"),
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

    # Compute values for computed metrics
    # First, build numeric_by_id from all regular metrics
    numeric_by_id: dict[int, float | None] = {}
    metrics_by_id = {m["id"]: m for m in metrics}
    for item in result:
        m_info = metrics_by_id.get(item["metric_id"])
        if not m_info or m_info["type"] == "computed":
            continue
        mt = m_info["type"]
        if item["slots"]:
            slot_vals = []
            for s in item["slots"]:
                if s["entry"] is not None:
                    cv = convert_metric_value(
                        s["entry"]["value"], mt,
                        m_info["scale_min"], m_info["scale_max"],
                    )
                    if cv is not None:
                        slot_vals.append(cv)
            numeric_by_id[item["metric_id"]] = (sum(slot_vals) / len(slot_vals)) if slot_vals else None
        else:
            if item["entry"] is not None:
                numeric_by_id[item["metric_id"]] = convert_metric_value(
                    item["entry"]["value"], mt,
                    m_info["scale_min"], m_info["scale_max"],
                )
            else:
                numeric_by_id[item["metric_id"]] = None

    # Evaluate computed metrics
    for item in result:
        m_info = metrics_by_id.get(item["metric_id"])
        if not m_info or m_info["type"] != "computed":
            continue
        formula = _parse_formula(m_info.get("formula"))
        result_type = m_info.get("result_type") or "float"
        if not formula:
            continue
        computed_val = evaluate_formula(formula, numeric_by_id, result_type)
        if computed_val is not None:
            item["entry"] = {
                "id": None,
                "recorded_at": None,
                "value": computed_val,
            }

    return {"date": date, "metrics": result}
