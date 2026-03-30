"""Service layer for data export — ZIP generation with metrics, entries, AW data."""

import csv
import json
import zipfile
from collections import defaultdict
from io import StringIO, BytesIO

from app.domain.enums import MetricType
from app.repositories.entry_repository import EntryRepository
from app.repositories.export_repository import ExportRepository


class ExportService:
    def __init__(self, repo: ExportRepository, conn) -> None:
        self.repo = repo
        self.conn = conn

    async def export_zip(self) -> BytesIO:
        """Generate ZIP archive with all user data."""
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            metrics = await self._export_metrics(zip_file)
            await self._export_entries(zip_file, metrics)
            await self._export_aw_data(zip_file)
            await self._export_notes(zip_file)

        zip_buffer.seek(0)
        return zip_buffer

    async def _export_metrics(self, zip_file: zipfile.ZipFile) -> list:
        metrics = await self.repo.get_metrics_for_export()
        metric_ids = [m["id"] for m in metrics]

        all_slots_rows = await self.repo.get_slots_for_export(metric_ids)
        slots_by_metric: dict[int, list[dict]] = defaultdict(list)
        for r in all_slots_rows:
            slots_by_metric[r["metric_id"]].append({"label": r["label"], "category_id": r["category_id"]})

        computed_cfgs = await self.repo.get_computed_configs(metric_ids)
        enum_opts_by_metric = await self.repo.get_enum_options_for_export(metric_ids)
        cond_by_metric = await self.repo.get_conditions_for_export(metric_ids)
        cat_rows = await self.repo.get_categories()
        cat_by_id = {r["id"]: r for r in cat_rows}

        def _cat_path(cat_id):
            if not cat_id or cat_id not in cat_by_id:
                return ''
            c = cat_by_id[cat_id]
            if c["parent_id"] and c["parent_id"] in cat_by_id:
                return f"{cat_by_id[c['parent_id']]['name']} > {c['name']}"
            return c["name"]

        metrics_csv = StringIO()
        writer = csv.writer(metrics_csv)
        writer.writerow([
            'id', 'slug', 'name', 'category_path', 'icon', 'type',
            'enabled', 'sort_order', 'scale_min', 'scale_max', 'scale_step', 'scale_labels',
            'slot_labels', 'formula', 'result_type', 'provider', 'metric_key', 'value_type',
            'filter_name', 'filter_query', 'enum_options', 'multi_select', 'private',
            'condition_metric_slug', 'condition_type', 'condition_value',
            'description', 'hide_in_cards', 'is_checkpoint', 'interval_binding',
        ])

        for m in metrics:
            # Don't export slot_labels for moment metrics (their metric_slots are disabled)
            if m.get("interval_binding") == "moment":
                slot_labels = []
            else:
                slot_data = slots_by_metric.get(m["id"], [])
                has_slot_cats = any(sd["category_id"] is not None for sd in slot_data)
                if has_slot_cats:
                    slot_labels = [{"label": sd["label"], "category_path": _cat_path(sd["category_id"])} for sd in slot_data]
                else:
                    slot_labels = [sd["label"] for sd in slot_data]

            cc = computed_cfgs.get(m["id"])
            formula_export = ''
            result_type_export = ''
            if cc and cc["formula"]:
                raw_formula = cc["formula"]
                if isinstance(raw_formula, str):
                    raw_formula = json.loads(raw_formula)
                portable = [{k: v for k, v in t.items() if k != "id"} if isinstance(t, dict) else t for t in raw_formula]
                formula_export = json.dumps(portable)
                result_type_export = cc["result_type"] or ''

            cond = cond_by_metric.get(m["id"])
            writer.writerow([
                m["id"], m["slug"], m["name"], _cat_path(m.get("category_id")), m.get("icon", ""), m["type"],
                1 if m["enabled"] else 0, m["sort_order"],
                m["scale_min"] if m["scale_min"] is not None else '',
                m["scale_max"] if m["scale_max"] is not None else '',
                m["scale_step"] if m["scale_step"] is not None else '',
                m["scale_labels"] if m.get("scale_labels") else '',
                json.dumps(slot_labels) if slot_labels else '',
                formula_export, result_type_export,
                m.get("provider") or '', m.get("metric_key") or '', m.get("value_type") or '',
                m.get("filter_name") or '', m.get("filter_query") or '',
                json.dumps(enum_opts_by_metric.get(m["id"], [])) if m["type"] == MetricType.enum else '',
                1 if m.get("multi_select") else '' if m["type"] != MetricType.enum else 0,
                1 if m.get("private") else 0,
                cond["depends_on_slug"] if cond else '',
                cond["condition_type"] if cond else '',
                cond["condition_value"] if cond and cond["condition_value"] is not None else '',
                m.get("description") or '',
                1 if m.get("hide_in_cards") else 0,
                1 if m.get("is_checkpoint") else 0,
                m.get("interval_binding", "all_day"),
            ])

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())
        return metrics

    async def _export_entries(self, zip_file: zipfile.ZipFile, metrics: list) -> None:
        slug_lookup = {m["id"]: m["slug"] for m in metrics}
        type_lookup = {
            m["id"]: (m.get("value_type") or MetricType.number) if m["type"] == MetricType.integration else m["type"]
            for m in metrics
        }
        enum_id_to_label = await self.repo.get_all_enum_options_by_id([m["id"] for m in metrics])

        entries_csv = StringIO()
        writer = csv.writer(entries_csv)
        writer.writerow(['date', 'metric_slug', 'value', 'slot_sort_order', 'slot_label'])

        entry_repo = EntryRepository(self.conn, self.repo.user_id)
        entries = await self.repo.get_entries_for_export()
        for e in entries:
            slug = slug_lookup.get(e["metric_id"])
            if not slug:
                continue
            mt = type_lookup.get(e["metric_id"], MetricType.bool)
            if mt in (MetricType.computed, MetricType.text):
                continue
            value = await entry_repo.get_entry_value(e["id"], mt)
            if mt == MetricType.enum and isinstance(value, list):
                id_map = enum_id_to_label.get(e["metric_id"], {})
                value = [id_map.get(oid, str(oid)) for oid in value]
            writer.writerow([
                str(e["date"]), slug, json.dumps(value),
                e["slot_sort_order"] if e["slot_sort_order"] is not None else '',
                e["slot_label"] or '',
            ])

        zip_file.writestr('entries.csv', entries_csv.getvalue())

    async def _export_aw_data(self, zip_file: zipfile.ZipFile) -> None:
        aw_daily_rows = await self.repo.get_aw_daily()
        if aw_daily_rows:
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['date', 'total_seconds', 'active_seconds'])
            for r in aw_daily_rows:
                writer.writerow([str(r["date"]), r["total_seconds"], r["active_seconds"]])
            zip_file.writestr('aw_daily.csv', buf.getvalue())

        aw_app_rows = await self.repo.get_aw_apps()
        if aw_app_rows:
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['date', 'app_name', 'source', 'duration_seconds'])
            for r in aw_app_rows:
                writer.writerow([str(r["date"]), r["app_name"], r["source"], r["duration_seconds"]])
            zip_file.writestr('aw_apps.csv', buf.getvalue())

    async def _export_notes(self, zip_file: zipfile.ZipFile) -> None:
        notes_rows = await self.repo.get_notes_for_export()
        if notes_rows:
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(['date', 'metric_slug', 'text', 'created_at'])
            for r in notes_rows:
                writer.writerow([str(r["date"]), r["metric_slug"], r["text"], str(r["created_at"])])
            zip_file.writestr('notes.csv', buf.getvalue())
