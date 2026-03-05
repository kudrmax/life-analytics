import json
from collections import defaultdict
from datetime import date as date_type

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user
from app.formula import convert_metric_value, evaluate_formula
from app.timing import QueryTimer


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
    qt = QueryTimer(f"daily/{date}")
    metrics = await db.fetch(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                  cc.formula, cc.result_type,
                  ic.provider, ic.metric_key, ic.value_type,
                  ifc.filter_name, iqc.filter_query,
                  icatc.category_id, iapc.app_name AS config_app_name
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
           LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
           LEFT JOIN integration_category_config icatc ON icatc.metric_id = md.id
           LEFT JOIN integration_app_config iapc ON iapc.metric_id = md.id
           WHERE md.enabled = TRUE AND md.user_id = $1
           ORDER BY md.sort_order, md.id""",
        current_user["id"],
    )

    qt.mark("metrics")
    d = date_type.fromisoformat(date)
    entries = await db.fetch(
        "SELECT * FROM entries WHERE date = $1 AND user_id = $2",
        d, current_user["id"],
    )

    qt.mark("entries")
    metric_ids = [m["id"] for m in metrics]

    # Get enabled slots for all metrics
    enabled_slots_rows = await db.fetch(
        """SELECT ms.id, ms.metric_id, ms.label, ms.sort_order
           FROM measurement_slots ms
           WHERE ms.metric_id = ANY($1) AND ms.enabled = TRUE
           ORDER BY ms.metric_id, ms.sort_order""",
        metric_ids,
    ) if metric_ids else []

    qt.mark("slots")
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

    qt.mark("disabled_slots")
    disabled_with_entries: dict[int, list] = defaultdict(list)
    for r in disabled_slot_ids_with_entries:
        disabled_with_entries[r["metric_id"]].append(r)

    # Build entries lookup: metric_id -> list of entries (multiple for multi-slot)
    entries_by_metric: dict[int, list] = defaultdict(list)
    for e in entries:
        entries_by_metric[e["metric_id"]].append(e)

    # --- Batch-load all entry values instead of N+1 queries ---
    # Build metric_id -> effective storage type lookup
    metric_type_map: dict[int, str] = {}
    for m in metrics:
        if m["type"] == "integration":
            metric_type_map[m["id"]] = m.get("value_type") or "number"
        else:
            metric_type_map[m["id"]] = m["type"]

    # Group entry IDs by storage type
    entry_ids_by_type: dict[str, list[int]] = defaultdict(list)
    all_entry_ids = [e["id"] for e in entries]
    for e in entries:
        etype = metric_type_map.get(e["metric_id"], "bool")
        entry_ids_by_type[etype].append(e["id"])

    # Batch-fetch values from each typed table
    values_map: dict[int, any] = {}  # entry_id -> value
    scale_context_map: dict[int, dict] = {}  # entry_id -> {scale_min, scale_max, scale_step}

    if entry_ids_by_type.get("bool"):
        rows = await db.fetch(
            "SELECT entry_id, value FROM values_bool WHERE entry_id = ANY($1)",
            entry_ids_by_type["bool"],
        )
        for r in rows:
            values_map[r["entry_id"]] = r["value"]

    if entry_ids_by_type.get("number"):
        rows = await db.fetch(
            "SELECT entry_id, value FROM values_number WHERE entry_id = ANY($1)",
            entry_ids_by_type["number"],
        )
        for r in rows:
            values_map[r["entry_id"]] = r["value"]

    if entry_ids_by_type.get("time"):
        rows = await db.fetch(
            "SELECT entry_id, value FROM values_time WHERE entry_id = ANY($1)",
            entry_ids_by_type["time"],
        )
        for r in rows:
            ts = r["value"]
            values_map[r["entry_id"]] = f"{ts.hour:02d}:{ts.minute:02d}"

    if entry_ids_by_type.get("scale"):
        rows = await db.fetch(
            "SELECT entry_id, value, scale_min, scale_max, scale_step FROM values_scale WHERE entry_id = ANY($1)",
            entry_ids_by_type["scale"],
        )
        for r in rows:
            values_map[r["entry_id"]] = r["value"]
            scale_context_map[r["entry_id"]] = {
                "scale_min": r["scale_min"],
                "scale_max": r["scale_max"],
                "scale_step": r["scale_step"],
            }

    qt.mark("values")
    # --- Build result using pre-loaded values ---
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
            "provider": m.get("provider"),
            "metric_key": m.get("metric_key"),
            "value_type": m.get("value_type"),
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
                    value = values_map.get(entry["id"])
                    slot_item["entry"] = {
                        "id": entry["id"],
                        "recorded_at": str(entry["recorded_at"]),
                        "value": value,
                    }
                    # Scale context from stored values
                    sc = scale_context_map.get(entry["id"])
                    if sc:
                        slot_item["entry"]["scale_min"] = sc["scale_min"]
                        slot_item["entry"]["scale_max"] = sc["scale_max"]
                        slot_item["entry"]["scale_step"] = sc["scale_step"]

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
                value = values_map.get(entry["id"])
                item["entry"] = {
                    "id": entry["id"],
                    "recorded_at": str(entry["recorded_at"]),
                    "value": value,
                }
                # For filled scale entries, use stored context instead of current config
                sc = scale_context_map.get(entry["id"])
                if sc:
                    item["scale_min"] = sc["scale_min"]
                    item["scale_max"] = sc["scale_max"]
                    item["scale_step"] = sc["scale_step"]

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

    # Auto metrics
    auto_metrics = []
    for item in result:
        m_info = metrics_by_id.get(item["metric_id"])
        if not m_info or m_info["type"] == "computed":
            continue

        # "nonzero" — только для number
        if m_info["type"] == "number":
            if item["slots"]:
                vals = [s["entry"]["value"] for s in item["slots"] if s["entry"] is not None]
                is_nonzero = any(v != 0 for v in vals) if vals else False
            else:
                is_nonzero = (item["entry"] is not None and item["entry"]["value"] != 0)

            auto_metrics.append({
                "name": f"{m_info['name']}: не ноль",
                "auto_type": "nonzero",
                "source_metric_id": item["metric_id"],
                "source_metric_name": m_info["name"],
                "value": is_nonzero,
            })

    # Calendar auto metrics
    auto_metrics.extend([
        {"name": "День недели", "auto_type": "day_of_week",
         "source_metric_id": None, "source_metric_name": None,
         "value": d.isoweekday()},
        {"name": "Месяц", "auto_type": "month",
         "source_metric_id": None, "source_metric_name": None,
         "value": d.month},
        {"name": "Неделя года", "auto_type": "week_number",
         "source_metric_id": None, "source_metric_name": None,
         "value": d.isocalendar()[1]},
    ])

    qt.mark("build")
    qt.log()
    return {"date": date, "metrics": result, "auto_metrics": auto_metrics}
