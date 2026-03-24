"""Pure helper functions for daily service — conditions, auto-metrics, progress."""

from datetime import date as date_type

from app.domain.enums import MetricType
from app.formula import convert_metric_value, evaluate_formula
from app.domain.formatters import format_display_value
from app.analytics.value_converter import ValueConverter

_parse_formula = ValueConverter.parse_formula


def extract_dep_value(item: dict):
    """Extract dependency value from a daily item for condition evaluation."""
    if item.get("slots"):
        for s in item["slots"]:
            if s.get("entry") is not None:
                return s["entry"]["value"]
        return None
    if item.get("entry") is not None:
        return item["entry"]["value"]
    return None


def evaluate_condition(cond: dict, dep_value) -> bool:
    """Check if a condition is met given the dependency value."""
    cond_type = cond["type"]
    cond_value = cond.get("value")
    if dep_value is None:
        return False
    if cond_type == "filled":
        return True
    if cond_type == "equals":
        if isinstance(dep_value, list):
            return any(v in dep_value for v in cond_value) if isinstance(cond_value, list) else cond_value in dep_value
        return dep_value == cond_value
    if cond_type == "not_equals":
        if isinstance(dep_value, list):
            return not any(v in dep_value for v in cond_value) if isinstance(cond_value, list) else cond_value not in dep_value
        return dep_value != cond_value
    return True


def evaluate_visibility(result: list[dict]) -> None:
    """Set condition_met flag on all items."""
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
        item["condition_met"] = evaluate_condition(cond, extract_dep_value(dep))


def compute_formulas(result: list[dict], metrics_by_id: dict) -> None:
    """Evaluate computed metrics from existing metric values."""
    numeric_by_id: dict[int, float | None] = {}
    for item in result:
        m = metrics_by_id.get(item["metric_id"])
        if not m or m["type"] == MetricType.computed:
            continue
        mt = m["type"]
        if item["slots"]:
            vals = [cv for s in item["slots"] if s["entry"] is not None
                    for cv in [convert_metric_value(s["entry"]["value"], mt, m["scale_min"], m["scale_max"])]
                    if cv is not None]
            numeric_by_id[item["metric_id"]] = (sum(vals) / len(vals)) if vals else None
        else:
            numeric_by_id[item["metric_id"]] = (
                convert_metric_value(item["entry"]["value"], mt, m["scale_min"], m["scale_max"])
                if item["entry"] is not None else None
            )

    for item in result:
        m = metrics_by_id.get(item["metric_id"])
        if not m or m["type"] != MetricType.computed:
            continue
        formula = _parse_formula(m.get("formula"))
        rt = m.get("result_type") or "float"
        if not formula:
            continue
        val = evaluate_formula(formula, numeric_by_id, rt)
        if val is not None:
            item["entry"] = {"id": None, "recorded_at": None, "value": val,
                             "display_value": format_display_value(val, "computed", rt)}


def build_auto_metrics(
    result: list[dict], metrics_by_id: dict, notes_count_map: dict, d: date_type,
) -> list[dict]:
    """Build auto-generated virtual metrics."""
    auto: list[dict] = []
    for item in result:
        m = metrics_by_id.get(item["metric_id"])
        if not m or m["type"] == MetricType.computed:
            continue
        name = item["name"]
        if m["type"] == MetricType.text:
            auto.append({"name": f"{name}: кол-во заметок", "auto_type": "note_count",
                         "source_metric_id": item["metric_id"], "source_metric_name": name,
                         "value": notes_count_map.get(item["metric_id"], 0)})
        if m["type"] in (MetricType.number, MetricType.duration):
            if item["slots"]:
                vals = [s["entry"]["value"] for s in item["slots"] if s["entry"] is not None]
                nz = any(v != 0 for v in vals) if vals else False
            else:
                nz = item["entry"] is not None and item["entry"]["value"] != 0
            auto.append({"name": f"{name}: не ноль", "auto_type": "nonzero",
                         "source_metric_id": item["metric_id"], "source_metric_name": name, "value": nz})
    auto.extend([
        {"name": "День недели", "auto_type": "day_of_week", "source_metric_id": None, "source_metric_name": None, "value": d.isoweekday()},
        {"name": "Месяц", "auto_type": "month", "source_metric_id": None, "source_metric_name": None, "value": d.month},
        {"name": "Календарный тип", "auto_type": "is_workday", "source_metric_id": None, "source_metric_name": None, "value": d.isoweekday() <= 5},
    ])
    return auto


def calculate_progress(result: list[dict]) -> dict:
    """Calculate fill progress across all metrics."""
    filled = total = 0
    for item in result:
        mt = item["type"]
        if mt in (MetricType.computed, MetricType.integration) or not item.get("condition_met", True):
            continue
        if mt == MetricType.text:
            total += 1
            if item.get("note_count", 0) > 0:
                filled += 1
            continue
        if item["slots"]:
            for s in item["slots"]:
                total += 1
                if s["entry"] is not None:
                    filled += 1
        else:
            total += 1
            if item["entry"] is not None:
                filled += 1
    return {"filled": filled, "total": total, "percent": round(filled / total * 100) if total > 0 else 0}


def split_by_slot_categories(result: list[dict]) -> list[dict]:
    """Split multi-slot metrics with different slot categories into separate items."""
    final: list[dict] = []
    for item in result:
        if not item["slots"]:
            final.append(item)
            continue
        groups: dict[int | None, list] = {}
        for s in item["slots"]:
            groups.setdefault(s.get("category_id"), []).append(s)
        if len(groups) == 1:
            item["category_id"] = next(iter(groups.keys()))
            final.append(item)
        else:
            for cat_id, cat_slots in groups.items():
                split = {**item, "category_id": cat_id, "slots": cat_slots, "is_slot_split": True}
                final.append(split)
    return final


def split_by_checkpoints(result: list[dict], all_user_slots: list) -> list[dict]:
    """Split multi-slot metrics into per-checkpoint items for checkpoint-based page layout.

    Each metric with slots becomes N separate cards — one per checkpoint section.
    Daily metrics (no slots) get checkpoint_section_id = None.
    """
    # Build slot_id → label mapping
    slot_labels = {s["id"]: s["label"] for s in all_user_slots}

    final: list[dict] = []
    for item in result:
        if not item.get("slots"):
            # Daily metric — no checkpoint section
            item["checkpoint_section_id"] = None
            item["checkpoint_section_label"] = None
            final.append(item)
            continue

        # Split each slot into its own item
        for s in item["slots"]:
            slot_id = s["slot_id"]
            split = {
                **item,
                "checkpoint_section_id": slot_id,
                "checkpoint_section_label": slot_labels.get(slot_id, s.get("label", "")),
                "slots": [s],
                "is_slot_split": True,
            }
            final.append(split)

    return final
