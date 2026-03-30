"""Service layer for daily summary — orchestrates data loading and response building."""

import json
from collections import defaultdict
from datetime import date as date_type

from app.domain.enums import MetricType
from app.domain.privacy import mask_name, mask_icon, is_blocked
from app.domain.formatters import format_display_value
from app.analytics.value_converter import ValueConverter
from app.repositories.daily_repository import DailyRepository
from app.services.daily_helpers import (
    evaluate_visibility, compute_formulas, build_auto_metrics,
    calculate_progress, split_by_checkpoints,
)
from app.timing import QueryTimer

_parse_formula = ValueConverter.parse_formula


class DailyService:
    def __init__(self, repo: DailyRepository) -> None:
        self.repo = repo

    async def get_daily_summary(self, date_str: str, privacy_mode: bool) -> dict:
        qt = QueryTimer(f"daily/{date_str}")
        d = date_type.fromisoformat(date_str)
        data = await self._load_daily_data(d, qt)
        result = self._build_metric_responses(data, d, privacy_mode)
        qt.mark("values")
        evaluate_visibility(result)
        compute_formulas(result, data["metrics_by_id"])
        auto_metrics = build_auto_metrics(result, data["metrics_by_id"], data["notes_count_map"], d)
        progress = calculate_progress(result)
        all_user_checkpoints = data.get("all_user_checkpoints", [])
        active_intervals = data.get("active_intervals", [])
        result = split_by_checkpoints(result, all_user_checkpoints, active_intervals)
        qt.mark("build"); qt.log()
        checkpoints = [{"id": c["id"], "label": c["label"]} for c in all_user_checkpoints]
        intervals = [{"id": iv["id"], "start_checkpoint_id": iv["start_checkpoint_id"],
                       "end_checkpoint_id": iv["end_checkpoint_id"], "label": iv["label"]} for iv in active_intervals]
        return {"date": date_str, "metrics": result, "checkpoints": checkpoints, "intervals": intervals, "auto_metrics": auto_metrics, "progress": progress}

    async def _load_daily_data(self, d: date_type, qt: QueryTimer) -> dict:
        metrics = await self.repo.get_enabled_metrics_with_config()
        qt.mark("metrics")
        entries = await self.repo.get_entries_for_date(d)
        qt.mark("entries")
        metric_ids = [m["id"] for m in metrics]

        # Load checkpoint bindings
        enabled_cp_rows = await self.repo.get_enabled_checkpoints(metric_ids)
        qt.mark("checkpoints")
        enabled_checkpoints: dict[int, list] = defaultdict(list)
        for r in enabled_cp_rows:
            enabled_checkpoints[r["metric_id"]].append(r)

        disabled_cp_rows = await self.repo.get_disabled_checkpoints_with_entries(metric_ids, d)
        qt.mark("disabled_checkpoints")
        disabled_checkpoints: dict[int, list] = defaultdict(list)
        for r in disabled_cp_rows:
            disabled_checkpoints[r["metric_id"]].append(r)

        # Load interval bindings
        enabled_iv_rows = await self.repo.get_enabled_intervals(metric_ids)
        qt.mark("intervals")
        enabled_intervals: dict[int, list] = defaultdict(list)
        for r in enabled_iv_rows:
            enabled_intervals[r["metric_id"]].append(r)

        disabled_iv_rows = await self.repo.get_disabled_intervals_with_entries(metric_ids, d)
        qt.mark("disabled_intervals")
        disabled_intervals: dict[int, list] = defaultdict(list)
        for r in disabled_iv_rows:
            disabled_intervals[r["metric_id"]].append(r)

        entries_by_metric: dict[int, list] = defaultdict(list)
        for e in entries:
            entries_by_metric[e["metric_id"]].append(e)

        metric_type_map: dict[int, str] = {}
        for m in metrics:
            metric_type_map[m["id"]] = (m.get("value_type") or MetricType.number) if m["type"] == MetricType.integration else m["type"]

        entry_ids_by_type: dict[str, list[int]] = defaultdict(list)
        for e in entries:
            entry_ids_by_type[metric_type_map.get(e["metric_id"], MetricType.bool)].append(e["id"])

        values_map, scale_ctx = await self.repo.batch_load_values(entry_ids_by_type)
        enum_ids = [m["id"] for m in metrics if m["type"] == MetricType.enum]
        enum_opts = await self.repo.get_enum_options_for_metrics(enum_ids)
        text_ids = [m["id"] for m in metrics if m["type"] == MetricType.text]
        notes_count, notes_by = await self.repo.get_notes_for_date(text_ids, d)

        # Load all user checkpoints and active intervals for layout
        all_user_checkpoints = await self.repo.get_all_user_checkpoints()
        active_intervals = await self.repo.get_active_intervals()

        return {
            "metrics": metrics, "metrics_by_id": {m["id"]: m for m in metrics},
            "enabled_checkpoints": enabled_checkpoints, "disabled_checkpoints": disabled_checkpoints,
            "enabled_intervals": enabled_intervals, "disabled_intervals": disabled_intervals,
            "entries_by_metric": entries_by_metric,
            "values_map": values_map, "scale_context_map": scale_ctx,
            "enum_options_by_metric": enum_opts,
            "notes_count_map": notes_count, "notes_by_metric": notes_by,
            "all_user_checkpoints": all_user_checkpoints,
            "active_intervals": active_intervals,
        }

    def _build_metric_responses(self, data: dict, d: date_type, privacy_mode: bool) -> list[dict]:
        result: list[dict] = []
        for m in data["metrics"]:
            mid = m["id"]
            m_private = m.get("private", False)
            m_blocked = is_blocked(m_private, privacy_mode)

            item = {
                "metric_id": mid, "slug": m["slug"],
                "name": mask_name(m["name"], m_private, privacy_mode),
                "description": m.get("description"),
                "icon": mask_icon(m.get("icon", ""), m_private, privacy_mode),
                "category_id": m.get("category_id"), "type": m["type"],
                "scale_min": m["scale_min"], "scale_max": m["scale_max"], "scale_step": m["scale_step"],
                "scale_labels": json.loads(m["scale_labels"]) if m.get("scale_labels") is not None else None,
                "private": m_private, "hide_in_cards": m.get("hide_in_cards", False),
                "is_checkpoint": m.get("is_checkpoint", False),
                "interval_binding": m.get("interval_binding", "all_day"),
                "entry": None, "checkpoints": None, "intervals": None,
                "formula": _parse_formula(m.get("formula")) or None,
                "result_type": m.get("result_type"), "provider": m.get("provider"),
                "metric_key": m.get("metric_key"), "value_type": m.get("value_type"),
                "multi_select": m.get("multi_select"),
                "enum_options": data["enum_options_by_metric"].get(mid) if m["type"] == MetricType.enum else None,
                "notes": data["notes_by_metric"].get(mid, []) if m["type"] == MetricType.text else None,
                "note_count": data["notes_count_map"].get(mid, 0) if m["type"] == MetricType.text else None,
                "condition": {
                    "depends_on_metric_id": m.get("condition_metric_id"),
                    "type": m.get("condition_type"),
                    "value": json.loads(m["condition_value"]) if m.get("condition_value") is not None else None,
                } if m.get("condition_metric_id") else None,
            }
            if m_blocked:
                item["notes"] = [] if m["type"] == MetricType.text else None
                item["note_count"] = 0 if m["type"] == MetricType.text else None
                result.append(item); continue

            cp_slots = data["enabled_checkpoints"].get(mid, [])
            cp_extra = data["disabled_checkpoints"].get(mid, [])
            iv_slots = data["enabled_intervals"].get(mid, [])
            iv_extra = data["disabled_intervals"].get(mid, [])
            if cp_slots or cp_extra:
                self._fill_checkpoints(item, m, data["entries_by_metric"].get(mid, []), cp_slots, cp_extra, data)
            if iv_slots or iv_extra:
                self._fill_intervals(item, m, data["entries_by_metric"].get(mid, []), iv_slots, iv_extra, data)
            if not cp_slots and not cp_extra and not iv_slots and not iv_extra:
                self._fill_single(item, m, data["entries_by_metric"].get(mid, []), data)
            result.append(item)
        return result

    def _fill_checkpoints(self, item: dict, m: dict, entries: list, checkpoints: list, extra: list, data: dict) -> None:
        """Fill checkpoint sub-items for checkpoint metrics (is_checkpoint=True)."""
        mid = m["id"]
        all_cp = sorted(list(checkpoints) + list(extra), key=lambda s: s["sort_order"])
        by_checkpoint = {e["checkpoint_id"]: e for e in entries if e.get("checkpoint_id") is not None}
        items: list[dict] = []
        for cp in all_cp:
            si: dict = {"checkpoint_id": cp["id"], "label": cp["label"], "category_id": cp.get("category_id"), "entry": None}
            e = by_checkpoint.get(cp["id"])
            if e:
                v = data["values_map"].get(e["id"])
                si["entry"] = {"id": e["id"], "recorded_at": str(e["recorded_at"]), "value": v,
                               "display_value": format_display_value(v, m["type"], m.get("result_type"),
                                                                     data["enum_options_by_metric"].get(mid), scale_labels=item.get("scale_labels"))}
                sc = data["scale_context_map"].get(e["id"])
                if sc:
                    si["entry"]["scale_min"] = sc["scale_min"]; si["entry"]["scale_max"] = sc["scale_max"]; si["entry"]["scale_step"] = sc["scale_step"]
            items.append(si)
        item["checkpoints"] = items

    def _fill_intervals(self, item: dict, m: dict, entries: list, intervals: list, extra: list, data: dict) -> None:
        """Fill interval sub-items for interval metrics (interval_binding=by_interval)."""
        mid = m["id"]
        all_iv = sorted(list(intervals) + list(extra), key=lambda s: s["start_sort_order"])
        by_interval = {e["interval_id"]: e for e in entries if e.get("interval_id") is not None}
        items: list[dict] = []
        for iv in all_iv:
            si: dict = {"interval_id": iv["id"], "label": iv["label"], "category_id": iv.get("category_id"), "entry": None}
            e = by_interval.get(iv["id"])
            if e:
                v = data["values_map"].get(e["id"])
                si["entry"] = {"id": e["id"], "recorded_at": str(e["recorded_at"]), "value": v,
                               "display_value": format_display_value(v, m["type"], m.get("result_type"),
                                                                     data["enum_options_by_metric"].get(mid), scale_labels=item.get("scale_labels"))}
                sc = data["scale_context_map"].get(e["id"])
                if sc:
                    si["entry"]["scale_min"] = sc["scale_min"]; si["entry"]["scale_max"] = sc["scale_max"]; si["entry"]["scale_step"] = sc["scale_step"]
            items.append(si)
        item["intervals"] = items

    def _fill_single(self, item: dict, m: dict, entries: list, data: dict) -> None:
        mid = m["id"]
        e = next((e for e in entries if e.get("checkpoint_id") is None and e.get("interval_id") is None), None)
        if e:
            v = data["values_map"].get(e["id"])
            item["entry"] = {"id": e["id"], "recorded_at": str(e["recorded_at"]), "value": v,
                             "display_value": format_display_value(v, m["type"], m.get("result_type"),
                                                                   data["enum_options_by_metric"].get(mid), scale_labels=item.get("scale_labels"))}
            sc = data["scale_context_map"].get(e["id"])
            if sc:
                item["scale_min"] = sc["scale_min"]; item["scale_max"] = sc["scale_max"]; item["scale_step"] = sc["scale_step"]

