"""Service layer for data import — ZIP parsing, metric import, orchestration."""

import csv
import json
import zipfile
from io import StringIO, BytesIO

from app.domain.enums import MetricType
from app.domain.exceptions import InvalidOperationError
from app.repositories.import_repository import ImportRepository
from app.services.import_entries_service import EntryImporter


_INTERVAL_BINDING_MAP = {"daily": "all_day", "fixed": "by_interval", "floating": "by_interval"}


def _normalize_interval_binding(raw: str) -> str:
    return _INTERVAL_BINDING_MAP.get(raw, raw)


class ImportService:
    def __init__(self, repo: ImportRepository, conn) -> None:
        self.repo = repo
        self.conn = conn

    async def import_zip(self, content: bytes) -> dict:
        zip_buffer = BytesIO(content)
        try:
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                if 'metrics.csv' not in zf.namelist():
                    raise InvalidOperationError("ZIP must contain metrics.csv")
                if 'entries.csv' not in zf.namelist():
                    raise InvalidOperationError("ZIP must contain entries.csv")

                mi, mu, me = await self._import_metrics(zf)
                slug_to_id, slug_to_type = await self._build_slug_lookups()
                await self._import_computed_formulas(zf, slug_to_id)
                await self._import_conditions(zf, slug_to_id)

                importer = EntryImporter(self.repo, self.conn)
                ei, es, ee = await importer.import_entries(zf, slug_to_id, slug_to_type)
                await importer.import_aw_data(zf)
                await importer.import_notes(zf, slug_to_id)
        except zipfile.BadZipFile:
            raise InvalidOperationError("Invalid ZIP file")
        except InvalidOperationError:
            raise
        except Exception as e:
            raise InvalidOperationError(f"Import failed: {str(e)}")

        return {
            "metrics": {"imported": mi, "updated": mu, "errors": me[:10] if me else []},
            "entries": {"imported": ei, "skipped": es, "errors": ee[:10] if ee else []},
        }

    async def _import_metrics(self, zf) -> tuple[int, int, list[str]]:
        imported = updated = 0
        errors: list[str] = []
        text = zf.read('metrics.csv').decode('utf-8')
        for row_num, row in enumerate(csv.DictReader(StringIO(text)), start=2):
            try:
                slug = row.get('slug', '')
                if not slug:
                    errors.append(f"Row {row_num}: Missing slug"); continue

                cat_id = await self._resolve_category(row)
                existing = await self.repo.find_metric_by_slug(slug)
                mt = row.get('type', MetricType.bool.value)
                valid_types = {t.value for t in MetricType}
                if mt not in valid_types:
                    mt = MetricType.bool.value

                parsed = self._parse_row(row)
                slot_configs = await self._parse_slot_configs(row)

                if existing:
                    await self.repo.update_metric_on_import(
                        existing["id"], parsed["name"], cat_id, parsed["enabled"],
                        parsed["sort_order"], parsed["icon"], parsed["private"], parsed["desc"], parsed["hic"],
                        parsed["is_checkpoint"], parsed["interval_binding"])
                    await self._update_configs(existing["id"], mt, row, parsed, slot_configs)
                    updated += 1
                else:
                    new_id = await self.repo.create_metric_on_import(
                        slug, parsed["name"], cat_id, parsed["icon"], mt,
                        parsed["enabled"], parsed["sort_order"], parsed["private"], parsed["desc"], parsed["hic"],
                        parsed["is_checkpoint"], parsed["interval_binding"])
                    await self._create_configs(new_id, mt, row, parsed, slot_configs)
                    imported += 1
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
        return imported, updated, errors

    async def _build_slug_lookups(self) -> tuple[dict, dict]:
        rows = await self.repo.get_metrics_with_types()
        s2id = {r["slug"]: r["id"] for r in rows}
        s2t = {r["slug"]: (r["ic_value_type"] or MetricType.number) if r["type"] == MetricType.integration else r["type"] for r in rows}
        return s2id, s2t

    async def _import_computed_formulas(self, zf, slug_to_id: dict) -> None:
        text = zf.read('metrics.csv').decode('utf-8')
        for row in csv.DictReader(StringIO(text)):
            if row.get('type') != MetricType.computed.value: continue
            mid = slug_to_id.get(row.get('slug', ''))
            if not mid: continue
            raw = row.get('formula', '')
            rt = row.get('result_type', 'float') or 'float'
            if not raw: continue
            try:
                tokens = json.loads(raw)
                resolved, valid = [], True
                for t in tokens:
                    if isinstance(t, dict) and t.get("type") == "metric":
                        ref = slug_to_id.get(t.get("slug", ""))
                        if ref: resolved.append({"type": "metric", "id": ref, "slug": t["slug"]})
                        else: valid = False; break
                    else: resolved.append(t)
                if valid and resolved:
                    await self.repo.upsert_computed_config(mid, json.dumps(resolved), rt)
            except (json.JSONDecodeError, TypeError, KeyError): pass

    async def _import_conditions(self, zf, slug_to_id: dict) -> None:
        text = zf.read('metrics.csv').decode('utf-8')
        for row in csv.DictReader(StringIO(text)):
            cs = row.get('condition_metric_slug', '').strip()
            if not cs: continue
            mid = slug_to_id.get(row.get('slug', ''))
            dep = slug_to_id.get(cs)
            if not mid or not dep: continue
            ct = row.get('condition_type', '').strip()
            if ct not in ('filled', 'equals', 'not_equals'): continue
            cv_raw = row.get('condition_value', '').strip()
            cv = None
            if cv_raw:
                try: cv = json.dumps(json.loads(cv_raw))
                except (json.JSONDecodeError, TypeError): pass
            await self.repo.upsert_condition(mid, dep, ct, cv)

    # ── Helpers ───────────────────────────────────────────────────

    async def _resolve_category(self, row: dict) -> int | None:
        cp = row.get('category_path', '')
        cat = row.get('category', '')
        ft = row.get('fill_time', '')
        if cp: return await self.repo.resolve_category_path(cp)
        if ft or cat:
            path = f"{ft} > {cat}" if ft and cat else (ft or cat)
            return await self.repo.resolve_category_path(path)
        return None

    @staticmethod
    def _parse_row(row: dict) -> dict:
        eo_raw = row.get('enum_options', '')
        eo = []
        if eo_raw:
            try: eo = json.loads(eo_raw)
            except (json.JSONDecodeError, TypeError): pass
        sl_raw = row.get('scale_labels', '')
        sl = None
        if sl_raw:
            try: json.loads(sl_raw); sl = sl_raw
            except (json.JSONDecodeError, TypeError): pass
        return {
            "name": row.get('name', row.get('slug', '')), "icon": row.get('icon', ''),
            "enabled": row.get('enabled', '1') in ('1', 'True', 'true', True),
            "sort_order": int(row.get('sort_order', 0)),
            "private": row.get('private', '') in ('1', 'True', 'true'),
            "desc": row.get('description', '') or None,
            "hic": row.get('hide_in_cards', '') in ('1', 'True', 'true'),
            "is_checkpoint": row.get('is_checkpoint', '') in ('1', 'True', 'true'),
            "interval_binding": _normalize_interval_binding(row.get('interval_binding', 'all_day') or 'all_day'),
            "multi": row.get('multi_select', '') in ('1', 'True', 'true'),
            "enum_opts": eo, "scale_labels": sl,
            "smin": row.get('scale_min', ''), "smax": row.get('scale_max', ''), "sstep": row.get('scale_step', ''),
            "provider": row.get('provider', ''), "mkey": row.get('metric_key', ''),
            "vtype": row.get('value_type', ''), "fname": row.get('filter_name', ''), "fquery": row.get('filter_query', ''),
        }

    async def _parse_slot_configs(self, row: dict) -> list[dict]:
        raw = row.get('slot_labels', '')
        if not raw: return []
        try:
            parsed = json.loads(raw)
            configs: list[dict] = []
            for item in parsed:
                if isinstance(item, str): configs.append({"label": item})
                elif isinstance(item, dict):
                    cid = await self.repo.resolve_category_path(item.get("category_path", "")) if item.get("category_path") else None
                    configs.append({"label": item.get("label", ""), "category_id": cid})
            return configs
        except (json.JSONDecodeError, TypeError): return []

    async def _update_configs(self, mid, mt, row, p, slot_configs) -> None:
        if mt == MetricType.scale.value and p["smin"] and p["smax"] and p["sstep"]:
            cfg = await self.repo.get_scale_config(mid)
            await self.repo.upsert_scale_config(mid, int(p["smin"]), int(p["smax"]), int(p["sstep"]), p["scale_labels"], cfg is not None)
        if mt == MetricType.integration.value and p["provider"] and p["mkey"]:
            await self.repo.upsert_integration_config(mid, p["provider"], p["mkey"], p["vtype"] or 'number')
            if p["mkey"] == 'filter_tasks_count' and p["fname"]:
                await self.repo.upsert_integration_filter_config(mid, p["fname"])
            elif p["mkey"] == 'query_tasks_count' and p["fquery"]:
                await self.repo.upsert_integration_query_config(mid, p["fquery"])
        if mt == MetricType.enum.value and p["enum_opts"]:
            await self.repo.upsert_enum_config(mid, p["multi"])
            await self._import_enum_options(mid, p["enum_opts"])
        if len(slot_configs) >= 2:
            await self._import_slots(mid, slot_configs)

    async def _create_configs(self, mid, mt, row, p, slot_configs) -> None:
        if mt == MetricType.scale.value:
            await self.repo.upsert_scale_config(mid, int(p["smin"] or 1), int(p["smax"] or 5), int(p["sstep"] or 1), p["scale_labels"], False)
        if mt == MetricType.integration.value and p["provider"] and p["mkey"]:
            await self.repo.upsert_integration_config(mid, p["provider"], p["mkey"], p["vtype"] or 'number')
            if p["mkey"] == 'filter_tasks_count' and p["fname"]:
                await self.repo.upsert_integration_filter_config(mid, p["fname"])
            elif p["mkey"] == 'query_tasks_count' and p["fquery"]:
                await self.repo.upsert_integration_query_config(mid, p["fquery"])
        if mt == MetricType.enum.value and p["enum_opts"]:
            await self.repo.upsert_enum_config(mid, p["multi"])
            for i, label in enumerate(p["enum_opts"]):
                await self.repo.insert_enum_option(mid, i, label)
        if len(slot_configs) >= 2:
            for i, cfg in enumerate(slot_configs):
                sid = await self.repo.find_or_create_slot(cfg["label"])
                await self.repo.insert_metric_slot(mid, sid, i, cfg.get("category_id"))

    async def _import_enum_options(self, mid: int, labels: list[str]) -> None:
        existing = await self.repo.get_enum_options_ordered(mid)
        for i, label in enumerate(labels):
            match = [o for o in existing if o["sort_order"] == i]
            if match: await self.repo.update_enum_option(match[0]["id"], label)
            else: await self.repo.insert_enum_option(mid, i, label)
        for o in existing:
            if o["sort_order"] >= len(labels): await self.repo.disable_enum_option(o["id"])

    async def _import_slots(self, mid: int, configs: list[dict]) -> None:
        existing = await self.repo.get_metric_slots(mid)
        by_sort = {s["sort_order"]: s for s in existing}
        for i, cfg in enumerate(configs):
            label = cfg["label"] if isinstance(cfg, dict) else cfg
            cid = cfg.get("category_id") if isinstance(cfg, dict) else None
            sid = await self.repo.find_or_create_slot(label)
            if i in by_sort: await self.repo.update_metric_slot_on_import(by_sort[i]["id"], sid, cid)
            else: await self.repo.upsert_metric_slot(mid, sid, i, cid)
        for s in existing:
            if s["sort_order"] >= len(configs): await self.repo.disable_metric_slot(s["id"])
        if any(isinstance(c, dict) and c.get("category_id") for c in configs):
            await self.repo.clear_metric_category(mid)
