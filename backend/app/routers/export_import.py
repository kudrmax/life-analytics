"""
Export and import data in ZIP format (metrics + entries).
"""
import csv
import json
import zipfile
from collections import defaultdict
from io import StringIO, BytesIO
from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import get_entry_value, insert_value
from app.repositories.export_import_repository import ExportImportRepository

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_data(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    repo = ExportImportRepository(db, current_user["id"])
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export metrics
        metrics_csv = StringIO()
        metrics_writer = csv.writer(metrics_csv)
        metrics_writer.writerow([
            'id', 'slug', 'name', 'category_path', 'icon', 'type',
            'enabled', 'sort_order', 'scale_min', 'scale_max', 'scale_step', 'scale_labels',
            'slot_labels', 'formula', 'result_type', 'provider', 'metric_key', 'value_type',
            'filter_name', 'filter_query', 'enum_options', 'multi_select', 'private',
            'condition_metric_slug', 'condition_type', 'condition_value',
            'description', 'hide_in_cards',
        ])

        metrics = await repo.get_metrics_for_export()

        # Get slots for all metrics (with category_id from junction table)
        metric_ids = [m["id"] for m in metrics]
        all_slots_rows = await repo.get_slots_for_export(metric_ids)

        slots_by_metric: dict[int, list[dict]] = defaultdict(list)
        for r in all_slots_rows:
            slots_by_metric[r["metric_id"]].append({
                "label": r["label"], "category_id": r["category_id"],
            })

        # Load computed_config for all metrics
        computed_cfgs = await repo.get_computed_configs(metric_ids)

        # Load enum options for export
        enum_opts_by_metric = await repo.get_enum_options_for_export(metric_ids)

        # Load conditions for export
        cond_by_metric = await repo.get_conditions_for_export(metric_ids)

        # Build ID→label lookup for enum entry export
        enum_id_to_label = await repo.get_all_enum_options_by_id(metric_ids)

        # Build category id -> path lookup
        cat_rows = await repo.get_categories()
        cat_by_id = {r["id"]: r for r in cat_rows}

        def _cat_path(cat_id):
            if not cat_id or cat_id not in cat_by_id:
                return ''
            c = cat_by_id[cat_id]
            if c["parent_id"] and c["parent_id"] in cat_by_id:
                return f"{cat_by_id[c['parent_id']]['name']} > {c['name']}"
            return c["name"]

        for m in metrics:
            slot_data = slots_by_metric.get(m["id"], [])
            # Export slot_labels: if any slot has category_id, use extended format
            has_slot_cats = any(sd["category_id"] is not None for sd in slot_data)
            if has_slot_cats:
                slot_labels = [
                    {"label": sd["label"], "category_path": _cat_path(sd["category_id"])}
                    for sd in slot_data
                ]
            else:
                slot_labels = [sd["label"] for sd in slot_data]
            # Export formula (slug-based, no IDs for portability)
            cc = computed_cfgs.get(m["id"])
            formula_export = ''
            result_type_export = ''
            if cc and cc["formula"]:
                raw_formula = cc["formula"]
                if isinstance(raw_formula, str):
                    raw_formula = json.loads(raw_formula)
                portable = [
                    {k: v for k, v in t.items() if k != "id"} if isinstance(t, dict) else t
                    for t in raw_formula
                ]
                formula_export = json.dumps(portable)
                result_type_export = cc["result_type"] or ''
            cond = cond_by_metric.get(m["id"])
            metrics_writer.writerow([
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
                json.dumps(enum_opts_by_metric.get(m["id"], [])) if m["type"] == "enum" else '',
                1 if m.get("multi_select") else '' if m["type"] != "enum" else 0,
                1 if m.get("private") else 0,
                cond["depends_on_slug"] if cond else '',
                cond["condition_type"] if cond else '',
                cond["condition_value"] if cond and cond["condition_value"] is not None else '',
                m.get("description") or '',
                1 if m.get("hide_in_cards") else 0,
            ])

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())

        # Export entries
        entries_csv = StringIO()
        entries_writer = csv.writer(entries_csv)
        entries_writer.writerow(['date', 'metric_slug', 'value', 'slot_sort_order', 'slot_label'])

        slug_lookup = {m["id"]: m["slug"] for m in metrics}
        type_lookup = {
            m["id"]: (m.get("value_type") or "number") if m["type"] == "integration" else m["type"]
            for m in metrics
        }

        entries = await repo.get_entries_for_export()

        for e in entries:
            slug = slug_lookup.get(e["metric_id"])
            if not slug:
                continue

            mt = type_lookup.get(e["metric_id"], "bool")
            if mt == "computed" or mt == "text":
                continue  # computed/text metrics have no stored entries
            value = await get_entry_value(db, e["id"], mt)
            # Convert enum option IDs to labels for portability
            if mt == "enum" and isinstance(value, list):
                id_map = enum_id_to_label.get(e["metric_id"], {})
                value = [id_map.get(oid, str(oid)) for oid in value]
            entries_writer.writerow([
                str(e["date"]), slug,
                json.dumps(value),
                e["slot_sort_order"] if e["slot_sort_order"] is not None else '',
                e["slot_label"] or '',
            ])

        zip_file.writestr('entries.csv', entries_csv.getvalue())

        # Export ActivityWatch daily summary
        aw_daily_rows = await repo.get_aw_daily()
        if aw_daily_rows:
            aw_daily_csv = StringIO()
            aw_daily_writer = csv.writer(aw_daily_csv)
            aw_daily_writer.writerow(['date', 'total_seconds', 'active_seconds'])
            for r in aw_daily_rows:
                aw_daily_writer.writerow([str(r["date"]), r["total_seconds"], r["active_seconds"]])
            zip_file.writestr('aw_daily.csv', aw_daily_csv.getvalue())

        # Export ActivityWatch app usage
        aw_app_rows = await repo.get_aw_apps()
        if aw_app_rows:
            aw_apps_csv = StringIO()
            aw_apps_writer = csv.writer(aw_apps_csv)
            aw_apps_writer.writerow(['date', 'app_name', 'source', 'duration_seconds'])
            for r in aw_app_rows:
                aw_apps_writer.writerow([str(r["date"]), r["app_name"], r["source"], r["duration_seconds"]])
            zip_file.writestr('aw_apps.csv', aw_apps_csv.getvalue())

        # Export notes (text metrics)
        notes_rows = await repo.get_notes_for_export()
        if notes_rows:
            notes_csv = StringIO()
            notes_writer = csv.writer(notes_csv)
            notes_writer.writerow(['date', 'metric_slug', 'text', 'created_at'])
            for r in notes_rows:
                notes_writer.writerow([str(r["date"]), r["metric_slug"], r["text"], str(r["created_at"])])
            zip_file.writestr('notes.csv', notes_csv.getvalue())

    zip_buffer.seek(0)
    filename = f"life_analytics_{current_user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, "File must be a ZIP archive")

    content = await file.read()
    zip_buffer = BytesIO(content)

    repo = ExportImportRepository(db, current_user["id"])

    metrics_imported = 0
    metrics_updated = 0
    metrics_errors = []
    entries_imported = 0
    entries_skipped = 0
    entries_errors = []

    try:
        with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
            if 'metrics.csv' not in zip_file.namelist():
                raise HTTPException(400, "ZIP must contain metrics.csv")
            if 'entries.csv' not in zip_file.namelist():
                raise HTTPException(400, "ZIP must contain entries.csv")

            # Import metrics
            metrics_csv_text = zip_file.read('metrics.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(metrics_csv_text))

            for row_num, row in enumerate(reader, start=2):
                try:
                    slug = row.get('slug', '')
                    if not slug:
                        metrics_errors.append(f"Row {row_num}: Missing slug")
                        continue

                    name = row.get('name', slug)
                    icon = row.get('icon', '')
                    enabled = row.get('enabled', '1') in ('1', 'True', 'true', True)
                    sort_order = int(row.get('sort_order', 0))

                    # Resolve category_id from CSV
                    # New format: category_path ("Parent > Child")
                    # Old format: category + fill_time columns
                    csv_category_path = row.get('category_path', '')
                    csv_category = row.get('category', '')
                    csv_fill_time = row.get('fill_time', '')
                    if csv_category_path:
                        import_cat_id = await repo.resolve_category_path(csv_category_path)
                    elif csv_fill_time or csv_category:
                        # Legacy format: build path from fill_time > category
                        if csv_fill_time and csv_category:
                            legacy_path = f"{csv_fill_time} > {csv_category}"
                        elif csv_fill_time:
                            legacy_path = csv_fill_time
                        else:
                            legacy_path = csv_category
                        import_cat_id = await repo.resolve_category_path(legacy_path)
                    else:
                        import_cat_id = None

                    existing = await repo.find_metric_by_slug(slug)

                    metric_type = row.get('type', 'bool')
                    if metric_type not in ('bool', 'time', 'number', 'duration', 'scale', 'computed', 'integration', 'enum', 'text'):
                        metric_type = 'bool'

                    # Parse enum config from CSV
                    csv_enum_options_raw = row.get('enum_options', '')
                    csv_enum_options = []
                    if csv_enum_options_raw:
                        try:
                            csv_enum_options = json.loads(csv_enum_options_raw)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    csv_multi_select = row.get('multi_select', '')
                    multi_select = csv_multi_select in ('1', 'True', 'true') if csv_multi_select else False
                    csv_private = row.get('private', '')
                    is_private = csv_private in ('1', 'True', 'true')
                    csv_description = row.get('description', '') or None
                    csv_hide_in_cards = row.get('hide_in_cards', '')
                    hide_in_cards = csv_hide_in_cards in ('1', 'True', 'true')

                    # Parse scale config from CSV
                    csv_scale_min = row.get('scale_min', '')
                    csv_scale_max = row.get('scale_max', '')
                    csv_scale_step = row.get('scale_step', '')
                    csv_scale_labels_raw = row.get('scale_labels', '')
                    csv_scale_labels: str | None = None
                    if csv_scale_labels_raw:
                        try:
                            json.loads(csv_scale_labels_raw)  # validate
                            csv_scale_labels = csv_scale_labels_raw
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Parse slot_labels from CSV (supports legacy [str] and new [{label, category_path}])
                    csv_slot_labels_raw = row.get('slot_labels', '')
                    csv_slot_configs: list[dict] = []  # [{label, category_id}]
                    if csv_slot_labels_raw:
                        try:
                            parsed_slots = json.loads(csv_slot_labels_raw)
                            for item in parsed_slots:
                                if isinstance(item, str):
                                    csv_slot_configs.append({"label": item})
                                elif isinstance(item, dict):
                                    cat_id = None
                                    cp = item.get("category_path", "")
                                    if cp:
                                        cat_id = await repo.resolve_category_path(cp)
                                    csv_slot_configs.append({"label": item.get("label", ""), "category_id": cat_id})
                        except (json.JSONDecodeError, TypeError):
                            pass
                    csv_slot_labels = [c["label"] for c in csv_slot_configs]

                    # Parse integration fields from CSV
                    csv_provider = row.get('provider', '')
                    csv_metric_key = row.get('metric_key', '')
                    csv_value_type = row.get('value_type', '')
                    csv_filter_name = row.get('filter_name', '')
                    csv_filter_query = row.get('filter_query', '')

                    if existing:
                        await repo.update_metric_on_import(
                            existing["id"], name, import_cat_id, enabled,
                            sort_order, icon, is_private, csv_description, hide_in_cards,
                        )
                        # Update scale_config if needed
                        if metric_type == 'scale' and csv_scale_min and csv_scale_max and csv_scale_step:
                            s_min, s_max, s_step = int(csv_scale_min), int(csv_scale_max), int(csv_scale_step)
                            existing_cfg = await repo.get_scale_config(existing["id"])
                            await repo.upsert_scale_config(
                                existing["id"], s_min, s_max, s_step,
                                csv_scale_labels, existing_cfg is not None,
                            )
                        # Upsert integration_config if needed
                        if metric_type == 'integration' and csv_provider and csv_metric_key:
                            await repo.upsert_integration_config(
                                existing["id"], csv_provider, csv_metric_key, csv_value_type or 'number',
                            )
                            if csv_metric_key == 'filter_tasks_count' and csv_filter_name:
                                await repo.upsert_integration_filter_config(existing["id"], csv_filter_name)
                            elif csv_metric_key == 'query_tasks_count' and csv_filter_query:
                                await repo.upsert_integration_query_config(existing["id"], csv_filter_query)
                        # Upsert enum_config if needed
                        if metric_type == 'enum' and csv_enum_options:
                            await repo.upsert_enum_config(existing["id"], multi_select)
                            await _import_enum_options(repo, existing["id"], csv_enum_options)
                        # Import slots if provided
                        if len(csv_slot_configs) >= 2:
                            await _import_slots(repo, existing["id"], csv_slot_configs)
                        metrics_updated += 1
                    else:
                        new_id = await repo.create_metric_on_import(
                            slug, name, import_cat_id, icon, metric_type,
                            enabled, sort_order, is_private, csv_description, hide_in_cards,
                        )
                        # Create scale_config for new scale metrics
                        if metric_type == 'scale':
                            s_min = int(csv_scale_min) if csv_scale_min else 1
                            s_max = int(csv_scale_max) if csv_scale_max else 5
                            s_step = int(csv_scale_step) if csv_scale_step else 1
                            await repo.upsert_scale_config(new_id, s_min, s_max, s_step, csv_scale_labels, False)
                        # Create integration_config for new integration metrics
                        if metric_type == 'integration' and csv_provider and csv_metric_key:
                            await repo.upsert_integration_config(
                                new_id, csv_provider, csv_metric_key, csv_value_type or 'number',
                            )
                            if csv_metric_key == 'filter_tasks_count' and csv_filter_name:
                                await repo.upsert_integration_filter_config(new_id, csv_filter_name)
                            elif csv_metric_key == 'query_tasks_count' and csv_filter_query:
                                await repo.upsert_integration_query_config(new_id, csv_filter_query)
                        # Create enum_config for new enum metrics
                        if metric_type == 'enum' and csv_enum_options:
                            await repo.upsert_enum_config(new_id, multi_select)
                            for i, label in enumerate(csv_enum_options):
                                await repo.insert_enum_option(new_id, i, label)
                        # Create slots if provided
                        if len(csv_slot_configs) >= 2:
                            for i, cfg in enumerate(csv_slot_configs):
                                slot_id = await repo.find_or_create_slot(cfg["label"])
                                await repo.insert_metric_slot(new_id, slot_id, i, cfg.get("category_id"))
                        metrics_imported += 1

                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            # Build slug->id and slug->type lookups after metric import
            metric_rows = await repo.get_metrics_with_types()
            slug_to_id = {r["slug"]: r["id"] for r in metric_rows}
            slug_to_type = {
                r["slug"]: (r["ic_value_type"] or "number") if r["type"] == "integration" else r["type"]
                for r in metric_rows
            }

            # Deferred: import computed formulas (need full slug->id map)
            metrics_csv_text2 = zip_file.read('metrics.csv').decode('utf-8')
            reader2 = csv.DictReader(StringIO(metrics_csv_text2))
            for row in reader2:
                if row.get('type') != 'computed':
                    continue
                slug = row.get('slug', '')
                mid = slug_to_id.get(slug)
                if not mid:
                    continue
                formula_raw = row.get('formula', '')
                result_type = row.get('result_type', 'float') or 'float'
                if formula_raw:
                    try:
                        portable_tokens = json.loads(formula_raw)
                        resolved = []
                        valid = True
                        for t in portable_tokens:
                            if isinstance(t, dict) and t.get("type") == "metric":
                                ref_id = slug_to_id.get(t.get("slug", ""))
                                if ref_id:
                                    resolved.append({"type": "metric", "id": ref_id, "slug": t["slug"]})
                                else:
                                    valid = False
                                    break
                            else:
                                resolved.append(t)
                        if valid and resolved:
                            await repo.upsert_computed_config(mid, json.dumps(resolved), result_type)
                    except (json.JSONDecodeError, TypeError, KeyError):
                        pass

            # Deferred: import conditions (need full slug->id map)
            metrics_csv_text3 = zip_file.read('metrics.csv').decode('utf-8')
            reader3 = csv.DictReader(StringIO(metrics_csv_text3))
            for row in reader3:
                cond_slug = row.get('condition_metric_slug', '').strip()
                if not cond_slug:
                    continue
                slug = row.get('slug', '')
                mid = slug_to_id.get(slug)
                dep_id = slug_to_id.get(cond_slug)
                if not mid or not dep_id:
                    continue
                cond_type = row.get('condition_type', '').strip()
                if cond_type not in ('filled', 'equals', 'not_equals'):
                    continue
                cond_val_raw = row.get('condition_value', '').strip()
                cond_val = None
                if cond_val_raw:
                    try:
                        cond_val = json.dumps(json.loads(cond_val_raw))
                    except (json.JSONDecodeError, TypeError):
                        pass
                await repo.upsert_condition(mid, dep_id, cond_type, cond_val)

            # Build metric_id -> {sort_order: slot_id} lookup
            all_metric_ids = list(slug_to_id.values())
            slot_lookup = await repo.get_slot_lookup(all_metric_ids)

            # Import entries
            entries_csv_text = zip_file.read('entries.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(entries_csv_text))

            for row_num, row in enumerate(reader, start=2):
                try:
                    slug = row.get('metric_slug', '')
                    metric_id = slug_to_id.get(slug)
                    if not metric_id:
                        entries_skipped += 1
                        continue
                    if slug_to_type.get(slug) in ("computed", "text"):
                        entries_skipped += 1
                        continue

                    date = row['date']
                    d = date_type.fromisoformat(date)

                    # Determine slot_id from CSV columns
                    slot_id = None
                    csv_slot_sort_order = row.get('slot_sort_order', '')
                    if csv_slot_sort_order != '' and csv_slot_sort_order is not None:
                        try:
                            so = int(csv_slot_sort_order)
                            # Find existing slot by metric + sort_order
                            if metric_id in slot_lookup and so in slot_lookup[metric_id]:
                                slot_id = slot_lookup[metric_id][so]
                            else:
                                # Create slot on the fly
                                csv_slot_label = row.get('slot_label', '')
                                new_slot_id = await repo.find_or_create_slot(csv_slot_label or f'Slot {so}')
                                await repo.insert_metric_slot_on_fly(metric_id, new_slot_id, so)
                                slot_lookup[metric_id][so] = new_slot_id
                                slot_id = new_slot_id
                        except (ValueError, TypeError):
                            pass

                    # Check for duplicate
                    if await repo.check_entry_duplicate(metric_id, d, slot_id):
                        entries_skipped += 1
                        continue

                    mt = slug_to_type.get(slug, "bool")
                    value_raw = row.get('value', 'false')
                    value = json.loads(value_raw)

                    if mt == "enum":
                        # value is list of option labels — resolve to IDs
                        if not isinstance(value, list):
                            entries_skipped += 1
                            continue
                        label_to_opt_id = await repo.get_enum_option_labels(metric_id)
                        option_ids = [label_to_opt_id[lbl] for lbl in value if lbl in label_to_opt_id]
                        if not option_ids:
                            entries_skipped += 1
                            continue
                        value = option_ids
                    elif mt == "time":
                        # value should be "HH:MM" string
                        if not isinstance(value, str):
                            entries_skipped += 1
                            continue
                    elif mt == "number" or mt == "duration":
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            entries_skipped += 1
                            continue
                    elif mt == "scale":
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            entries_skipped += 1
                            continue
                    else:
                        if isinstance(value, dict):
                            value = bool(value.get('value', False))
                        else:
                            value = bool(value)

                    async with db.transaction():
                        entry_id = await repo.create_entry(metric_id, d, slot_id)
                        await insert_value(db, entry_id, value, mt, entry_date=d, metric_id=metric_id)

                    entries_imported += 1

                except Exception as e:
                    entries_errors.append(f"Row {row_num}: {str(e)}")
                    entries_skipped += 1

            # Import ActivityWatch data (optional CSVs)
            if 'aw_daily.csv' in zip_file.namelist():
                aw_daily_text = zip_file.read('aw_daily.csv').decode('utf-8')
                for row in csv.DictReader(StringIO(aw_daily_text)):
                    d = date_type.fromisoformat(row['date'])
                    await repo.upsert_aw_daily(d, int(row['total_seconds']), int(row['active_seconds']))

            if 'aw_apps.csv' in zip_file.namelist():
                aw_apps_text = zip_file.read('aw_apps.csv').decode('utf-8')
                for row in csv.DictReader(StringIO(aw_apps_text)):
                    d = date_type.fromisoformat(row['date'])
                    await repo.upsert_aw_app(
                        d, row['app_name'], row.get('source', 'window'), int(row['duration_seconds']),
                    )

            # Import notes (text metrics)
            if 'notes.csv' in zip_file.namelist():
                notes_text = zip_file.read('notes.csv').decode('utf-8')
                for row in csv.DictReader(StringIO(notes_text)):
                    slug = row.get('metric_slug', '')
                    mid = slug_to_id.get(slug)
                    if not mid:
                        continue
                    d = date_type.fromisoformat(row['date'])
                    text = row.get('text', '')
                    if not text:
                        continue
                    # Deduplicate by metric + date + text
                    if not await repo.check_note_exists(mid, d, text):
                        await repo.insert_note(mid, d, text)

    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Import failed: {str(e)}")

    return {
        "metrics": {
            "imported": metrics_imported,
            "updated": metrics_updated,
            "errors": metrics_errors[:10] if metrics_errors else [],
        },
        "entries": {
            "imported": entries_imported,
            "skipped": entries_skipped,
            "errors": entries_errors[:10] if entries_errors else [],
        },
    }


async def _import_enum_options(repo: ExportImportRepository, metric_id: int, labels: list[str]) -> None:
    """Create or update enum options during import."""
    existing = await repo.get_enum_options_ordered(metric_id)
    for i, label in enumerate(labels):
        matching = [o for o in existing if o["sort_order"] == i]
        if matching:
            await repo.update_enum_option(matching[0]["id"], label)
        else:
            await repo.insert_enum_option(metric_id, i, label)
    for o in existing:
        if o["sort_order"] >= len(labels):
            await repo.disable_enum_option(o["id"])


async def _import_slots(
    repo: ExportImportRepository, metric_id: int, configs: list[dict],
) -> None:
    """Create or update metric slot bindings during import.

    configs: list of {label: str, category_id: int | None}
    """
    existing_slots = await repo.get_metric_slots(metric_id)
    existing_by_sort = {s["sort_order"]: s for s in existing_slots}

    for i, cfg in enumerate(configs):
        label = cfg["label"] if isinstance(cfg, dict) else cfg
        cat_id = cfg.get("category_id") if isinstance(cfg, dict) else None
        slot_id = await repo.find_or_create_slot(label)

        if i in existing_by_sort:
            # Update existing junction row
            await repo.update_metric_slot_on_import(existing_by_sort[i]["id"], slot_id, cat_id)
        else:
            await repo.upsert_metric_slot(metric_id, slot_id, i, cat_id)

    for s in existing_slots:
        if s["sort_order"] >= len(configs):
            await repo.disable_metric_slot(s["id"])
    # Defensive rule: clear metric category_id when slots have categories
    if any(isinstance(c, dict) and c.get("category_id") for c in configs):
        await repo.clear_metric_category(metric_id)
