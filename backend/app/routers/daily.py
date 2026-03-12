import json
from collections import defaultdict
from datetime import date as date_type

from fastapi import APIRouter, Depends

from app.database import get_db
from app.auth import get_current_user, get_privacy_mode
from app.metric_helpers import mask_name, mask_icon, is_blocked
from app.formula import convert_metric_value, evaluate_formula
from app.metric_helpers import format_display_value
from app.timing import QueryTimer


def _parse_formula(raw):
    """Parse formula from DB — may be JSON string or list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _extract_dep_value(item):
    """Извлечь значение метрики-зависимости для проверки условия."""
    if item.get("slots"):
        for s in item["slots"]:
            if s.get("entry") is not None:
                return s["entry"]["value"]
        return None
    if item.get("entry") is not None:
        return item["entry"]["value"]
    return None


def _evaluate_condition(cond, dep_value):
    """Проверить выполнение условия по значению зависимости."""
    cond_type = cond["type"]
    cond_value = cond.get("value")

    if dep_value is None:
        return False

    if cond_type == "filled":
        return True

    if cond_type == "equals":
        if isinstance(dep_value, list):
            if isinstance(cond_value, list):
                return any(v in dep_value for v in cond_value)
            return cond_value in dep_value
        return dep_value == cond_value

    if cond_type == "not_equals":
        if isinstance(dep_value, list):
            if isinstance(cond_value, list):
                return not any(v in dep_value for v in cond_value)
            return cond_value not in dep_value
        return dep_value != cond_value

    return True


router = APIRouter(prefix="/api/daily", tags=["daily"])


@router.get("/{date}")
async def daily_summary(date: str, db=Depends(get_db), current_user: dict = Depends(get_current_user), privacy_mode: bool = Depends(get_privacy_mode)):
    qt = QueryTimer(f"daily/{date}")
    metrics = await db.fetch(
        """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                  cc.formula, cc.result_type,
                  ic.provider, ic.metric_key, ic.value_type,
                  ifc.filter_name, iqc.filter_query,
                  icatc.activitywatch_category_id, iapc.app_name AS config_app_name,
                  ec.multi_select,
                  mcond.depends_on_metric_id AS condition_metric_id,
                  mcond.condition_type, mcond.condition_value
           FROM metric_definitions md
           LEFT JOIN scale_config sc ON sc.metric_id = md.id
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
           LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
           LEFT JOIN integration_category_config icatc ON icatc.metric_id = md.id
           LEFT JOIN integration_app_config iapc ON iapc.metric_id = md.id
           LEFT JOIN enum_config ec ON ec.metric_id = md.id
           LEFT JOIN metric_condition mcond ON mcond.metric_id = md.id
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
        """SELECT ms.id, ms.metric_id, ms.label, ms.sort_order, ms.category_id
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
            """SELECT DISTINCT ms.id, ms.metric_id, ms.label, ms.sort_order, ms.category_id
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

    if entry_ids_by_type.get("duration"):
        rows = await db.fetch(
            "SELECT entry_id, value FROM values_duration WHERE entry_id = ANY($1)",
            entry_ids_by_type["duration"],
        )
        for r in rows:
            values_map[r["entry_id"]] = r["value"]

    if entry_ids_by_type.get("enum"):
        rows = await db.fetch(
            "SELECT entry_id, selected_option_ids FROM values_enum WHERE entry_id = ANY($1)",
            entry_ids_by_type["enum"],
        )
        for r in rows:
            values_map[r["entry_id"]] = list(r["selected_option_ids"])

    # Bulk-load enum options for enum metrics
    enum_metric_ids = [m["id"] for m in metrics if m["type"] == "enum"]
    enum_options_by_metric: dict[int, list] = defaultdict(list)
    if enum_metric_ids:
        eo_rows = await db.fetch(
            """SELECT id, metric_id, label, sort_order FROM enum_options
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            enum_metric_ids,
        )
        for r in eo_rows:
            enum_options_by_metric[r["metric_id"]].append({
                "id": r["id"], "label": r["label"], "sort_order": r["sort_order"],
            })

    # Batch-load notes for text metrics
    text_metric_ids = [m["id"] for m in metrics if m["type"] == "text"]
    notes_count_map: dict[int, int] = {}
    notes_by_metric: dict[int, list] = defaultdict(list)
    if text_metric_ids:
        nc_rows = await db.fetch(
            "SELECT metric_id, COUNT(*) AS cnt FROM notes WHERE metric_id = ANY($1) AND user_id = $2 AND date = $3 GROUP BY metric_id",
            text_metric_ids, current_user["id"], d,
        )
        for r in nc_rows:
            notes_count_map[r["metric_id"]] = r["cnt"]
        n_rows = await db.fetch(
            "SELECT id, metric_id, text, created_at FROM notes WHERE metric_id = ANY($1) AND user_id = $2 AND date = $3 ORDER BY created_at",
            text_metric_ids, current_user["id"], d,
        )
        for r in n_rows:
            notes_by_metric[r["metric_id"]].append({
                "id": r["id"], "text": r["text"], "created_at": str(r["created_at"]),
            })

    qt.mark("values")
    # --- Build result using pre-loaded values ---
    result = []
    for m in metrics:
        mid = m["id"]
        metric_entries = entries_by_metric.get(mid, [])
        slots = enabled_slots.get(mid, [])
        extra_disabled = disabled_with_entries.get(mid, [])
        m_private = m.get("private", False)
        m_blocked = is_blocked(m_private, privacy_mode)

        item = {
            "metric_id": mid,
            "slug": m["slug"],
            "name": mask_name(m["name"], m_private, privacy_mode),
            "icon": mask_icon(m.get("icon", ""), m_private, privacy_mode),
            "category_id": m.get("category_id"),
            "type": m["type"],
            "scale_min": m["scale_min"],
            "scale_max": m["scale_max"],
            "scale_step": m["scale_step"],
            "private": m_private,
            "entry": None,
            "slots": None,
            "formula": _parse_formula(m.get("formula")) or None,
            "result_type": m.get("result_type"),
            "provider": m.get("provider"),
            "metric_key": m.get("metric_key"),
            "value_type": m.get("value_type"),
            "multi_select": m.get("multi_select"),
            "enum_options": enum_options_by_metric.get(mid) if m["type"] == "enum" else None,
            "notes": notes_by_metric.get(mid, []) if m["type"] == "text" else None,
            "note_count": notes_count_map.get(mid, 0) if m["type"] == "text" else None,
            "condition": {
                "depends_on_metric_id": m.get("condition_metric_id"),
                "type": m.get("condition_type"),
                "value": json.loads(m["condition_value"]) if m.get("condition_value") is not None else None,
            } if m.get("condition_metric_id") else None,
        }

        # If metric is blocked by privacy mode, hide all values
        if m_blocked:
            item["entry"] = None
            item["slots"] = None
            item["notes"] = [] if m["type"] == "text" else None
            item["note_count"] = 0 if m["type"] == "text" else None
            result.append(item)
            continue

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
                    "category_id": s.get("category_id"),
                    "entry": None,
                }
                if entry:
                    value = values_map.get(entry["id"])
                    slot_item["entry"] = {
                        "id": entry["id"],
                        "recorded_at": str(entry["recorded_at"]),
                        "value": value,
                        "display_value": format_display_value(
                            value, m["type"], m.get("result_type"),
                            enum_options_by_metric.get(mid),
                        ),
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
                    "display_value": format_display_value(
                        value, m["type"], m.get("result_type"),
                        enum_options_by_metric.get(mid),
                    ),
                }
                # For filled scale entries, use stored context instead of current config
                sc = scale_context_map.get(entry["id"])
                if sc:
                    item["scale_min"] = sc["scale_min"]
                    item["scale_max"] = sc["scale_max"]
                    item["scale_step"] = sc["scale_step"]

        result.append(item)

    # Evaluate conditions
    items_by_id = {item["metric_id"]: item for item in result}
    for item in result:
        cond = item.get("condition")
        if not cond:
            item["condition_met"] = True
            continue
        dep = items_by_id.get(cond["depends_on_metric_id"])
        if not dep:
            item["condition_met"] = True
            continue
        dep_value = _extract_dep_value(dep)
        item["condition_met"] = _evaluate_condition(cond, dep_value)

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
                "display_value": format_display_value(computed_val, "computed", result_type),
            }

    # Auto metrics
    auto_metrics = []
    for item in result:
        m_info = metrics_by_id.get(item["metric_id"])
        if not m_info or m_info["type"] == "computed":
            continue
        display_name = item["name"]  # already masked if needed

        # "note_count" — для text
        if m_info["type"] == "text":
            auto_metrics.append({
                "name": f"{display_name}: кол-во заметок",
                "auto_type": "note_count",
                "source_metric_id": item["metric_id"],
                "source_metric_name": display_name,
                "value": notes_count_map.get(item["metric_id"], 0),
            })

        # "nonzero" — для number и duration
        if m_info["type"] in ("number", "duration"):
            if item["slots"]:
                vals = [s["entry"]["value"] for s in item["slots"] if s["entry"] is not None]
                is_nonzero = any(v != 0 for v in vals) if vals else False
            else:
                is_nonzero = (item["entry"] is not None and item["entry"]["value"] != 0)

            auto_metrics.append({
                "name": f"{display_name}: не ноль",
                "auto_type": "nonzero",
                "source_metric_id": item["metric_id"],
                "source_metric_name": display_name,
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

    # Progress calculation (skip computed/integration, text=filled if note_count>0, multi-slot each slot separately)
    progress_filled = 0
    progress_total = 0
    for item in result:
        mt = item["type"]
        if mt in ("computed", "integration"):
            continue
        if not item.get("condition_met", True):
            continue
        if mt == "text":
            progress_total += 1
            if item.get("note_count", 0) > 0:
                progress_filled += 1
            continue
        if item["slots"]:
            for s in item["slots"]:
                progress_total += 1
                if s["entry"] is not None:
                    progress_filled += 1
        else:
            progress_total += 1
            if item["entry"] is not None:
                progress_filled += 1
    progress_percent = round(progress_filled / progress_total * 100) if progress_total > 0 else 0

    # Post-process: split multi-slot metrics by slot categories
    final_result = []
    for item in result:
        if not item["slots"] or len(item["slots"]) == 0:
            final_result.append(item)
            continue

        # Defensive rule: for metrics with slots, category_id always from slots
        groups: dict[int | None, list] = {}
        for s in item["slots"]:
            cat = s.get("category_id")
            groups.setdefault(cat, []).append(s)

        if len(groups) == 1:
            # All slots in one category — single item with slot's category_id
            cat_id = next(iter(groups.keys()))
            item["category_id"] = cat_id
            final_result.append(item)
        else:
            # Different categories — split into separate items
            for cat_id, cat_slots in groups.items():
                split_item = {**item}
                split_item["category_id"] = cat_id
                split_item["slots"] = cat_slots
                split_item["is_slot_split"] = True
                final_result.append(split_item)

    result = final_result

    qt.mark("build")
    qt.log()
    return {
        "date": date,
        "metrics": result,
        "auto_metrics": auto_metrics,
        "progress": {
            "filled": progress_filled,
            "total": progress_total,
            "percent": progress_percent,
        },
    }
