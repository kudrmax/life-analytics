"""Pure helper functions for daily service — conditions, auto-metrics, progress."""

from collections.abc import Mapping
from datetime import date as date_type

from app.domain.enums import MetricType
from app.formula import convert_metric_value, evaluate_formula
from app.domain.formatters import format_display_value
from app.analytics.value_converter import ValueConverter

_parse_formula = ValueConverter.parse_formula


def build_interval_label_map(all_user_checkpoints: list[Mapping]) -> dict[int, str]:
    """Build checkpoint_id → interval label mapping (e.g. checkpoint_id(Утро) → "Утро → День").

    Kept for backward compatibility. Uses checkpoints sorted by sort_order.
    """
    sorted_checkpoints = sorted(all_user_checkpoints, key=lambda s: s["sort_order"])
    result: dict[int, str] = {}
    for i, cp in enumerate(sorted_checkpoints):
        if i + 1 < len(sorted_checkpoints):
            result[cp["id"]] = f"{cp['label']} → {sorted_checkpoints[i + 1]['label']}"
    return result


def extract_dep_value(item: dict):
    """Extract dependency value from a daily item for condition evaluation."""
    if item.get("checkpoints"):
        for cp in item["checkpoints"]:
            if cp.get("entry") is not None:
                return cp["entry"]["value"]
        return None
    if item.get("intervals"):
        for iv in item["intervals"]:
            if iv.get("entry") is not None:
                return iv["entry"]["value"]
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
        if item.get("checkpoints"):
            vals = [cv for cp in item["checkpoints"] if cp["entry"] is not None
                    for cv in [convert_metric_value(cp["entry"]["value"], mt, m["scale_min"], m["scale_max"])]
                    if cv is not None]
            numeric_by_id[item["metric_id"]] = (sum(vals) / len(vals)) if vals else None
        elif item.get("intervals"):
            vals = [cv for iv in item["intervals"] if iv["entry"] is not None
                    for cv in [convert_metric_value(iv["entry"]["value"], mt, m["scale_min"], m["scale_max"])]
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
            if item.get("checkpoints"):
                vals = [cp["entry"]["value"] for cp in item["checkpoints"] if cp["entry"] is not None]
                nz = any(v != 0 for v in vals) if vals else False
            elif item.get("intervals"):
                vals = [iv["entry"]["value"] for iv in item["intervals"] if iv["entry"] is not None]
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
        if item.get("checkpoints"):
            for cp in item["checkpoints"]:
                total += 1
                if cp["entry"] is not None:
                    filled += 1
        elif item.get("intervals"):
            for iv in item["intervals"]:
                total += 1
                if iv["entry"] is not None:
                    filled += 1
        else:
            total += 1
            if item["entry"] is not None:
                filled += 1
    return {"filled": filled, "total": total, "percent": round(filled / total * 100) if total > 0 else 0}


def split_by_binding_categories(result: list[dict]) -> list[dict]:
    """Split multi-checkpoint/interval metrics with different categories into separate items."""
    final: list[dict] = []
    for item in result:
        sub_items = item.get("checkpoints") or item.get("intervals")
        if not sub_items:
            final.append(item)
            continue
        groups: dict[int | None, list] = {}
        for s in sub_items:
            groups.setdefault(s.get("category_id"), []).append(s)
        if len(groups) == 1:
            item["category_id"] = next(iter(groups.keys()))
            final.append(item)
        else:
            key = "checkpoints" if item.get("checkpoints") else "intervals"
            for cat_id, cat_items in groups.items():
                split = {**item, "category_id": cat_id, key: cat_items, "is_checkpoint_split": True}
                final.append(split)
    return final


def split_by_checkpoints(
    result: list[dict],
    all_user_checkpoints: list,
    active_intervals: list,
    daily_layout: list | None = None,
) -> list[dict]:
    """Split metrics into per-checkpoint items for checkpoint-based page layout.

    Checkpoint metrics: each checkpoint sub-item becomes a separate card with checkpoint_section_id.
    Interval metrics: each interval sub-item placed after its start checkpoint.
    Daily metrics (no checkpoints/intervals) get checkpoint_section_id = None.

    If daily_layout is provided, blocks are ordered according to the layout.
    Otherwise, default order: checkpoints → intervals → daily metrics.
    """
    # Build interval_id → start_checkpoint_id mapping
    interval_start_cp: dict[int, int] = {}
    for iv in active_intervals:
        interval_start_cp[iv["id"]] = iv["start_checkpoint_id"]

    # Build checkpoint labels
    checkpoint_labels = {c["id"]: c["label"] for c in all_user_checkpoints}

    # Split all items into buckets
    # checkpoint_id → [split_items], interval_id → [split_items], daily → [items]
    by_checkpoint: dict[int, list[dict]] = {}
    by_interval: dict[int, list[dict]] = {}
    daily_items: list[dict] = []
    # Track standalone metric_ids for layout matching
    standalone_by_cat: dict[int, list[dict]] = {}
    standalone_no_cat: list[dict] = []

    for item in result:
        has_checkpoints = item.get("checkpoints")
        has_intervals = item.get("intervals")

        if not has_checkpoints and not has_intervals:
            item["checkpoint_section_id"] = None
            item["checkpoint_section_label"] = None
            cat_id = item.get("category_id")
            if cat_id:
                item["block_type"] = "category"
                item["block_id"] = cat_id
                standalone_by_cat.setdefault(cat_id, []).append(item)
            else:
                item["block_type"] = "metric"
                item["block_id"] = item["metric_id"]
                standalone_no_cat.append(item)
            daily_items.append(item)
            continue

        if has_checkpoints:
            for cp in item["checkpoints"]:
                cp_id = cp["checkpoint_id"]
                split = {
                    **item,
                    "checkpoint_section_id": cp_id,
                    "checkpoint_section_label": checkpoint_labels.get(cp_id, cp.get("label", "")),
                    "checkpoints": [cp],
                    "intervals": None,
                    "is_checkpoint_split": True,
                    "block_type": "checkpoint",
                    "block_id": cp_id,
                }
                by_checkpoint.setdefault(cp_id, []).append(split)

        if has_intervals:
            for iv in item["intervals"]:
                iv_id = iv["interval_id"]
                start_cp_id = interval_start_cp.get(iv_id)
                split = {
                    **item,
                    "checkpoint_section_id": start_cp_id,
                    "checkpoint_section_label": checkpoint_labels.get(start_cp_id, "") if start_cp_id else None,
                    "checkpoints": None,
                    "intervals": [iv],
                    "is_checkpoint_split": True,
                    "block_type": "interval",
                    "block_id": iv_id,
                }
                by_interval.setdefault(iv_id, []).append(split)

    # If no layout, use default order: checkpoints → intervals → daily
    if not daily_layout:
        final: list[dict] = []
        for cp in all_user_checkpoints:
            final.extend(by_checkpoint.get(cp["id"], []))
        for iv in active_intervals:
            final.extend(by_interval.get(iv["id"], []))
        final.extend(daily_items)
        return final

    # Apply layout ordering
    final = []
    used_daily_ids: set[int] = set()
    for entry in daily_layout:
        bt = entry["block_type"]
        bid = entry["block_id"]
        if bt == "checkpoint":
            final.extend(by_checkpoint.get(bid, []))
        elif bt == "interval":
            final.extend(by_interval.get(bid, []))
        elif bt == "category":
            for item in standalone_by_cat.get(bid, []):
                final.append(item)
                used_daily_ids.add(item["metric_id"])
        elif bt == "metric":
            for item in standalone_no_cat:
                if item["metric_id"] == bid and item["metric_id"] not in used_daily_ids:
                    final.append(item)
                    used_daily_ids.add(item["metric_id"])

    # Append any daily items not covered by layout
    for item in daily_items:
        if item["metric_id"] not in used_daily_ids:
            final.append(item)

    return final
