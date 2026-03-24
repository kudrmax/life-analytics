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
    calculate_progress, split_by_checkpoints, build_interval_label_map,
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
        all_user_slots = data.get("all_user_slots", [])
        result = split_by_checkpoints(result, all_user_slots)
        qt.mark("build"); qt.log()
        checkpoints = [{"id": s["id"], "label": s["label"]} for s in all_user_slots]
        return {"date": date_str, "metrics": result, "checkpoints": checkpoints, "auto_metrics": auto_metrics, "progress": progress}

    async def _load_daily_data(self, d: date_type, qt: QueryTimer) -> dict:
        metrics = await self.repo.get_enabled_metrics_with_config()
        qt.mark("metrics")
        entries = await self.repo.get_entries_for_date(d)
        qt.mark("entries")
        metric_ids = [m["id"] for m in metrics]

        enabled_slots_rows = await self.repo.get_enabled_slots(metric_ids)
        qt.mark("slots")
        enabled_slots: dict[int, list] = defaultdict(list)
        for r in enabled_slots_rows:
            enabled_slots[r["metric_id"]].append(r)

        disabled_rows = await self.repo.get_disabled_slots_with_entries(metric_ids, d)
        qt.mark("disabled_slots")
        disabled_with_entries: dict[int, list] = defaultdict(list)
        for r in disabled_rows:
            disabled_with_entries[r["metric_id"]].append(r)

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

        # Load all user slots for interval label mapping
        all_user_slots = await self.repo.get_all_user_slots()
        interval_label_map = self._build_interval_label_map(all_user_slots)

        return {
            "metrics": metrics, "metrics_by_id": {m["id"]: m for m in metrics},
            "enabled_slots": enabled_slots, "disabled_with_entries": disabled_with_entries,
            "entries_by_metric": entries_by_metric,
            "values_map": values_map, "scale_context_map": scale_ctx,
            "enum_options_by_metric": enum_opts,
            "notes_count_map": notes_count, "notes_by_metric": notes_by,
            "interval_label_map": interval_label_map,
            "all_user_slots": all_user_slots,
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
                "interval_binding": m.get("interval_binding", "daily"),
                "entry": None, "slots": None,
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

            slots = data["enabled_slots"].get(mid, [])
            extra = data["disabled_with_entries"].get(mid, [])
            if slots or extra:
                self._fill_slots(item, m, data["entries_by_metric"].get(mid, []), slots, extra, data)
            else:
                self._fill_single(item, m, data["entries_by_metric"].get(mid, []), data)
            result.append(item)
        return result

    @staticmethod
    def _build_interval_label_map(all_user_slots: list) -> dict[int, str]:
        return build_interval_label_map(all_user_slots)

    def _fill_slots(self, item, m, entries, slots, extra, data) -> None:
        mid = m["id"]
        all_vis = sorted(list(slots) + list(extra), key=lambda s: s["sort_order"])
        by_slot = {e["slot_id"]: e for e in entries if e["slot_id"] is not None}
        interval_labels = data.get("interval_label_map", {})
        is_interval = m.get("interval_binding", "daily") in ("fixed", "floating")
        items = []
        for s in all_vis:
            label = interval_labels.get(s["id"], s["label"]) if is_interval else s["label"]
            si: dict = {"slot_id": s["id"], "label": label, "category_id": s.get("category_id"), "entry": None}
            e = by_slot.get(s["id"])
            if e:
                v = data["values_map"].get(e["id"])
                si["entry"] = {"id": e["id"], "recorded_at": str(e["recorded_at"]), "value": v,
                               "display_value": format_display_value(v, m["type"], m.get("result_type"),
                                                                     data["enum_options_by_metric"].get(mid), scale_labels=item.get("scale_labels"))}
                sc = data["scale_context_map"].get(e["id"])
                if sc:
                    si["entry"]["scale_min"] = sc["scale_min"]; si["entry"]["scale_max"] = sc["scale_max"]; si["entry"]["scale_step"] = sc["scale_step"]
            items.append(si)
        item["slots"] = items

    def _fill_single(self, item, m, entries, data) -> None:
        mid = m["id"]
        e = next((e for e in entries if e["slot_id"] is None), None)
        if e:
            v = data["values_map"].get(e["id"])
            item["entry"] = {"id": e["id"], "recorded_at": str(e["recorded_at"]), "value": v,
                             "display_value": format_display_value(v, m["type"], m.get("result_type"),
                                                                   data["enum_options_by_metric"].get(mid), scale_labels=item.get("scale_labels"))}
            sc = data["scale_context_map"].get(e["id"])
            if sc:
                item["scale_min"] = sc["scale_min"]; item["scale_max"] = sc["scale_max"]; item["scale_step"] = sc["scale_step"]
