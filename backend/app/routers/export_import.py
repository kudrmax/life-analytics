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
from app.metric_helpers import get_entry_value, insert_value, get_metric_type

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_data(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export metrics
        metrics_csv = StringIO()
        metrics_writer = csv.writer(metrics_csv)
        metrics_writer.writerow([
            'id', 'slug', 'name', 'category_path', 'icon', 'type',
            'enabled', 'sort_order', 'scale_min', 'scale_max', 'scale_step',
            'slot_labels', 'formula', 'result_type', 'provider', 'metric_key', 'value_type',
            'filter_name', 'filter_query', 'enum_options', 'multi_select', 'private',
            'condition_metric_slug', 'condition_type', 'condition_value',
        ])

        metrics = await db.fetch(
            """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                      ic.provider, ic.metric_key, ic.value_type,
                      ifc.filter_name, iqc.filter_query,
                      ec.multi_select
               FROM metric_definitions md
               LEFT JOIN scale_config sc ON sc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               LEFT JOIN integration_filter_config ifc ON ifc.metric_id = md.id
               LEFT JOIN integration_query_config iqc ON iqc.metric_id = md.id
               LEFT JOIN enum_config ec ON ec.metric_id = md.id
               WHERE md.user_id = $1 ORDER BY md.sort_order, md.id""",
            current_user["id"],
        )

        # Get slots for all metrics (with category_id from junction table)
        metric_ids = [m["id"] for m in metrics]
        all_slots_rows = await db.fetch(
            """SELECT msl.metric_id, ms.label, msl.sort_order, msl.category_id
               FROM metric_slots msl
               JOIN measurement_slots ms ON ms.id = msl.slot_id
               WHERE msl.metric_id = ANY($1) AND msl.enabled = TRUE
               ORDER BY msl.metric_id, msl.sort_order""",
            metric_ids,
        ) if metric_ids else []

        slots_by_metric: dict[int, list[dict]] = defaultdict(list)
        for r in all_slots_rows:
            slots_by_metric[r["metric_id"]].append({
                "label": r["label"], "category_id": r["category_id"],
            })

        # Load computed_config for all metrics
        computed_cfg_rows = await db.fetch(
            "SELECT metric_id, formula, result_type FROM computed_config WHERE metric_id = ANY($1)",
            metric_ids,
        ) if metric_ids else []
        computed_cfgs = {r["metric_id"]: r for r in computed_cfg_rows}

        # Load enum options for export
        enum_opts_rows = await db.fetch(
            """SELECT metric_id, label FROM enum_options
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            metric_ids,
        ) if metric_ids else []
        enum_opts_by_metric: dict[int, list[str]] = defaultdict(list)
        for r in enum_opts_rows:
            enum_opts_by_metric[r["metric_id"]].append(r["label"])

        # Load conditions for export
        cond_rows = await db.fetch(
            """SELECT mc.metric_id, md.slug AS depends_on_slug, mc.condition_type, mc.condition_value
               FROM metric_condition mc
               JOIN metric_definitions md ON md.id = mc.depends_on_metric_id
               WHERE mc.metric_id = ANY($1)""",
            metric_ids,
        ) if metric_ids else []
        cond_by_metric = {r["metric_id"]: r for r in cond_rows}

        # Build ID→label lookup for enum entry export
        enum_id_to_label: dict[int, dict[int, str]] = defaultdict(dict)
        if metric_ids:
            all_enum_opts = await db.fetch(
                "SELECT id, metric_id, label FROM enum_options WHERE metric_id = ANY($1)",
                metric_ids,
            )
            for r in all_enum_opts:
                enum_id_to_label[r["metric_id"]][r["id"]] = r["label"]

        # Build category id -> path lookup
        cat_rows = await db.fetch(
            "SELECT id, name, parent_id FROM categories WHERE user_id = $1",
            current_user["id"],
        )
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

        entries = await db.fetch(
            """SELECT e.*, ms.sort_order AS slot_sort_order, ms.label AS slot_label
               FROM entries e
               LEFT JOIN measurement_slots ms ON ms.id = e.slot_id
               WHERE e.user_id = $1 ORDER BY e.date DESC, e.metric_id""",
            current_user["id"],
        )

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
        aw_daily_rows = await db.fetch(
            "SELECT date, total_seconds, active_seconds FROM activitywatch_daily_summary WHERE user_id = $1 ORDER BY date",
            current_user["id"],
        )
        if aw_daily_rows:
            aw_daily_csv = StringIO()
            aw_daily_writer = csv.writer(aw_daily_csv)
            aw_daily_writer.writerow(['date', 'total_seconds', 'active_seconds'])
            for r in aw_daily_rows:
                aw_daily_writer.writerow([str(r["date"]), r["total_seconds"], r["active_seconds"]])
            zip_file.writestr('aw_daily.csv', aw_daily_csv.getvalue())

        # Export ActivityWatch app usage
        aw_app_rows = await db.fetch(
            "SELECT date, app_name, source, duration_seconds FROM activitywatch_app_usage WHERE user_id = $1 ORDER BY date, duration_seconds DESC",
            current_user["id"],
        )
        if aw_app_rows:
            aw_apps_csv = StringIO()
            aw_apps_writer = csv.writer(aw_apps_csv)
            aw_apps_writer.writerow(['date', 'app_name', 'source', 'duration_seconds'])
            for r in aw_app_rows:
                aw_apps_writer.writerow([str(r["date"]), r["app_name"], r["source"], r["duration_seconds"]])
            zip_file.writestr('aw_apps.csv', aw_apps_csv.getvalue())

        # Export notes (text metrics)
        notes_rows = await db.fetch(
            """SELECT n.date, md.slug AS metric_slug, n.text, n.created_at
               FROM notes n
               JOIN metric_definitions md ON md.id = n.metric_id
               WHERE n.user_id = $1
               ORDER BY n.date, n.created_at""",
            current_user["id"],
        )
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

            # Helper: find or create category from path string
            async def _resolve_category_path(path_str: str, uid: int) -> int | None:
                path_str = (path_str or '').strip()
                if not path_str:
                    return None
                parts = [p.strip() for p in path_str.split('>')]
                parent_id = None
                cat_id = None
                for part in parts:
                    if not part:
                        continue
                    existing = await db.fetchrow(
                        "SELECT id FROM categories WHERE user_id = $1 AND name = $2 AND parent_id IS NOT DISTINCT FROM $3",
                        uid, part, parent_id,
                    )
                    if existing:
                        cat_id = existing["id"]
                    else:
                        cat_id = await db.fetchval(
                            """INSERT INTO categories (user_id, name, parent_id, sort_order)
                               VALUES ($1, $2, $3, COALESCE((SELECT MAX(sort_order)+1 FROM categories WHERE user_id=$1), 0))
                               RETURNING id""",
                            uid, part, parent_id,
                        )
                    parent_id = cat_id
                return cat_id

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
                        import_cat_id = await _resolve_category_path(csv_category_path, current_user["id"])
                    elif csv_fill_time or csv_category:
                        # Legacy format: build path from fill_time > category
                        if csv_fill_time and csv_category:
                            legacy_path = f"{csv_fill_time} > {csv_category}"
                        elif csv_fill_time:
                            legacy_path = csv_fill_time
                        else:
                            legacy_path = csv_category
                        import_cat_id = await _resolve_category_path(legacy_path, current_user["id"])
                    else:
                        import_cat_id = None

                    existing = await db.fetchrow(
                        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
                        slug, current_user["id"],
                    )

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

                    # Parse scale config from CSV
                    csv_scale_min = row.get('scale_min', '')
                    csv_scale_max = row.get('scale_max', '')
                    csv_scale_step = row.get('scale_step', '')

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
                                        cat_id = await _resolve_category_path(cp, current_user["id"])
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
                        await db.execute(
                            """UPDATE metric_definitions
                               SET name = $1, category_id = $2, enabled = $3, sort_order = $4, icon = $5, private = $6
                               WHERE id = $7 AND user_id = $8""",
                            name, import_cat_id, enabled, sort_order, icon, is_private,
                            existing["id"], current_user["id"],
                        )
                        # Update scale_config if needed
                        if metric_type == 'scale' and csv_scale_min and csv_scale_max and csv_scale_step:
                            s_min, s_max, s_step = int(csv_scale_min), int(csv_scale_max), int(csv_scale_step)
                            existing_cfg = await db.fetchrow(
                                "SELECT metric_id FROM scale_config WHERE metric_id = $1",
                                existing["id"],
                            )
                            if existing_cfg:
                                await db.execute(
                                    "UPDATE scale_config SET scale_min = $1, scale_max = $2, scale_step = $3 WHERE metric_id = $4",
                                    s_min, s_max, s_step, existing["id"],
                                )
                            else:
                                await db.execute(
                                    "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4)",
                                    existing["id"], s_min, s_max, s_step,
                                )
                        # Upsert integration_config if needed
                        if metric_type == 'integration' and csv_provider and csv_metric_key:
                            await db.execute(
                                """INSERT INTO integration_config (metric_id, provider, metric_key, value_type)
                                   VALUES ($1, $2, $3, $4)
                                   ON CONFLICT (metric_id) DO UPDATE
                                   SET provider = EXCLUDED.provider, metric_key = EXCLUDED.metric_key, value_type = EXCLUDED.value_type""",
                                existing["id"], csv_provider, csv_metric_key, csv_value_type or 'number',
                            )
                            if csv_metric_key == 'filter_tasks_count' and csv_filter_name:
                                await db.execute(
                                    """INSERT INTO integration_filter_config (metric_id, filter_name)
                                       VALUES ($1, $2)
                                       ON CONFLICT (metric_id) DO UPDATE SET filter_name = EXCLUDED.filter_name""",
                                    existing["id"], csv_filter_name,
                                )
                            elif csv_metric_key == 'query_tasks_count' and csv_filter_query:
                                await db.execute(
                                    """INSERT INTO integration_query_config (metric_id, filter_query)
                                       VALUES ($1, $2)
                                       ON CONFLICT (metric_id) DO UPDATE SET filter_query = EXCLUDED.filter_query""",
                                    existing["id"], csv_filter_query,
                                )
                        # Upsert enum_config if needed
                        if metric_type == 'enum' and csv_enum_options:
                            await db.execute(
                                """INSERT INTO enum_config (metric_id, multi_select)
                                   VALUES ($1, $2)
                                   ON CONFLICT (metric_id) DO UPDATE SET multi_select = EXCLUDED.multi_select""",
                                existing["id"], multi_select,
                            )
                            await _import_enum_options(db, existing["id"], csv_enum_options)
                        # Import slots if provided
                        if len(csv_slot_configs) >= 2:
                            await _import_slots(db, existing["id"], csv_slot_configs, current_user["id"])
                        metrics_updated += 1
                    else:
                        new_id = await db.fetchval(
                            """INSERT INTO metric_definitions
                               (user_id, slug, name, category_id, icon, type, enabled, sort_order, private)
                               VALUES ($1, $2, $3, $4, $5, $6::metric_type, $7, $8, $9) RETURNING id""",
                            current_user["id"], slug, name, import_cat_id, icon,
                            metric_type, enabled, sort_order, is_private,
                        )
                        # Create scale_config for new scale metrics
                        if metric_type == 'scale':
                            s_min = int(csv_scale_min) if csv_scale_min else 1
                            s_max = int(csv_scale_max) if csv_scale_max else 5
                            s_step = int(csv_scale_step) if csv_scale_step else 1
                            await db.execute(
                                "INSERT INTO scale_config (metric_id, scale_min, scale_max, scale_step) VALUES ($1, $2, $3, $4)",
                                new_id, s_min, s_max, s_step,
                            )
                        # Create integration_config for new integration metrics
                        if metric_type == 'integration' and csv_provider and csv_metric_key:
                            await db.execute(
                                "INSERT INTO integration_config (metric_id, provider, metric_key, value_type) VALUES ($1, $2, $3, $4)",
                                new_id, csv_provider, csv_metric_key, csv_value_type or 'number',
                            )
                            if csv_metric_key == 'filter_tasks_count' and csv_filter_name:
                                await db.execute(
                                    "INSERT INTO integration_filter_config (metric_id, filter_name) VALUES ($1, $2)",
                                    new_id, csv_filter_name,
                                )
                            elif csv_metric_key == 'query_tasks_count' and csv_filter_query:
                                await db.execute(
                                    "INSERT INTO integration_query_config (metric_id, filter_query) VALUES ($1, $2)",
                                    new_id, csv_filter_query,
                                )
                        # Create enum_config for new enum metrics
                        if metric_type == 'enum' and csv_enum_options:
                            await db.execute(
                                "INSERT INTO enum_config (metric_id, multi_select) VALUES ($1, $2)",
                                new_id, multi_select,
                            )
                            for i, label in enumerate(csv_enum_options):
                                await db.execute(
                                    "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                                    new_id, i, label,
                                )
                        # Create slots if provided
                        if len(csv_slot_configs) >= 2:
                            for i, cfg in enumerate(csv_slot_configs):
                                slot_id = await _find_or_create_slot(db, current_user["id"], cfg["label"])
                                await db.execute(
                                    "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4)",
                                    new_id, slot_id, i, cfg.get("category_id"),
                                )
                        metrics_imported += 1

                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            # Build slug->id and slug->type lookups after metric import
            metric_rows = await db.fetch(
                """SELECT md.id, md.slug, md.type, ic.value_type AS ic_value_type
                   FROM metric_definitions md
                   LEFT JOIN integration_config ic ON ic.metric_id = md.id
                   WHERE md.user_id = $1""",
                current_user["id"],
            )
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
                            await db.execute(
                                """INSERT INTO computed_config (metric_id, formula, result_type)
                                   VALUES ($1, $2::jsonb, $3)
                                   ON CONFLICT (metric_id) DO UPDATE
                                   SET formula = EXCLUDED.formula, result_type = EXCLUDED.result_type""",
                                mid, json.dumps(resolved), result_type,
                            )
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
                await db.execute(
                    """INSERT INTO metric_condition (metric_id, depends_on_metric_id, condition_type, condition_value)
                       VALUES ($1, $2, $3, $4::jsonb)
                       ON CONFLICT (metric_id) DO UPDATE
                       SET depends_on_metric_id = EXCLUDED.depends_on_metric_id,
                           condition_type = EXCLUDED.condition_type,
                           condition_value = EXCLUDED.condition_value""",
                    mid, dep_id, cond_type, cond_val,
                )

            # Build metric_id -> {sort_order: slot_id} lookup
            all_metric_ids = list(slug_to_id.values())
            slot_rows = await db.fetch(
                """SELECT msl.metric_id, msl.sort_order, ms.id
                   FROM metric_slots msl
                   JOIN measurement_slots ms ON ms.id = msl.slot_id
                   WHERE msl.metric_id = ANY($1)""",
                all_metric_ids,
            ) if all_metric_ids else []
            slot_lookup: dict[int, dict[int, int]] = defaultdict(dict)
            for sr in slot_rows:
                slot_lookup[sr["metric_id"]][sr["sort_order"]] = sr["id"]

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
                                new_slot_id = await _find_or_create_slot(db, current_user["id"], csv_slot_label or f'Slot {so}')
                                await db.execute(
                                    "INSERT INTO metric_slots (metric_id, slot_id, sort_order) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                                    metric_id, new_slot_id, so,
                                )
                                slot_lookup[metric_id][so] = new_slot_id
                                slot_id = new_slot_id
                        except (ValueError, TypeError):
                            pass

                    # Check for duplicate
                    if slot_id is not None:
                        existing = await db.fetchval(
                            "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND slot_id = $4",
                            metric_id, current_user["id"], d, slot_id,
                        )
                    else:
                        existing = await db.fetchval(
                            "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND slot_id IS NULL",
                            metric_id, current_user["id"], d,
                        )
                    if existing:
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
                        opt_rows = await db.fetch(
                            "SELECT id, label FROM enum_options WHERE metric_id = $1",
                            metric_id,
                        )
                        label_to_opt_id = {r["label"]: r["id"] for r in opt_rows}
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
                        entry_id = await db.fetchval(
                            "INSERT INTO entries (metric_id, user_id, date, slot_id) VALUES ($1, $2, $3, $4) RETURNING id",
                            metric_id, current_user["id"], d, slot_id,
                        )
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
                    await db.execute(
                        """INSERT INTO activitywatch_daily_summary (user_id, date, total_seconds, active_seconds)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (user_id, date) DO UPDATE
                           SET total_seconds = EXCLUDED.total_seconds, active_seconds = EXCLUDED.active_seconds""",
                        current_user["id"], d, int(row['total_seconds']), int(row['active_seconds']),
                    )

            if 'aw_apps.csv' in zip_file.namelist():
                aw_apps_text = zip_file.read('aw_apps.csv').decode('utf-8')
                for row in csv.DictReader(StringIO(aw_apps_text)):
                    d = date_type.fromisoformat(row['date'])
                    await db.execute(
                        """INSERT INTO activitywatch_app_usage (user_id, date, app_name, source, duration_seconds)
                           VALUES ($1, $2, $3, $4, $5)
                           ON CONFLICT (user_id, date, app_name, source) DO UPDATE
                           SET duration_seconds = EXCLUDED.duration_seconds""",
                        current_user["id"], d, row['app_name'], row.get('source', 'window'), int(row['duration_seconds']),
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
                    existing = await db.fetchval(
                        "SELECT id FROM notes WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND text = $4",
                        mid, current_user["id"], d, text,
                    )
                    if not existing:
                        await db.execute(
                            "INSERT INTO notes (metric_id, user_id, date, text) VALUES ($1, $2, $3, $4)",
                            mid, current_user["id"], d, text,
                        )

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


async def _import_enum_options(db, metric_id: int, labels: list[str]):
    """Create or update enum options during import."""
    existing = await db.fetch(
        "SELECT * FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
        metric_id,
    )
    for i, label in enumerate(labels):
        matching = [o for o in existing if o["sort_order"] == i]
        if matching:
            await db.execute(
                "UPDATE enum_options SET label = $1, enabled = TRUE WHERE id = $2",
                label, matching[0]["id"],
            )
        else:
            await db.execute(
                "INSERT INTO enum_options (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                metric_id, i, label,
            )
    for o in existing:
        if o["sort_order"] >= len(labels):
            await db.execute(
                "UPDATE enum_options SET enabled = FALSE WHERE id = $1",
                o["id"],
            )


async def _find_or_create_slot(db, user_id: int, label: str) -> int:
    """Find existing global slot by label or create a new one. Return slot id."""
    existing = await db.fetchrow(
        "SELECT id FROM measurement_slots WHERE user_id = $1 AND LOWER(label) = LOWER($2)",
        user_id, label.strip(),
    )
    if existing:
        return existing["id"]
    max_order = await db.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) FROM measurement_slots WHERE user_id = $1",
        user_id,
    )
    return await db.fetchval(
        "INSERT INTO measurement_slots (user_id, label, sort_order) VALUES ($1, $2, $3) RETURNING id",
        user_id, label.strip(), max_order + 1,
    )


async def _import_slots(db, metric_id: int, configs: list[dict], user_id: int):
    """Create or update metric slot bindings during import.

    configs: list of {label: str, category_id: int | None}
    """
    existing_slots = await db.fetch(
        "SELECT * FROM metric_slots WHERE metric_id = $1 ORDER BY sort_order",
        metric_id,
    )
    existing_by_sort = {s["sort_order"]: s for s in existing_slots}

    for i, cfg in enumerate(configs):
        label = cfg["label"] if isinstance(cfg, dict) else cfg
        cat_id = cfg.get("category_id") if isinstance(cfg, dict) else None
        slot_id = await _find_or_create_slot(db, user_id, label)

        if i in existing_by_sort:
            # Update existing junction row
            await db.execute(
                "UPDATE metric_slots SET slot_id = $1, enabled = TRUE, category_id = $2 WHERE id = $3",
                slot_id, cat_id, existing_by_sort[i]["id"],
            )
        else:
            await db.execute(
                "INSERT INTO metric_slots (metric_id, slot_id, sort_order, category_id) VALUES ($1, $2, $3, $4) ON CONFLICT (metric_id, slot_id) DO UPDATE SET enabled = TRUE, sort_order = EXCLUDED.sort_order, category_id = EXCLUDED.category_id",
                metric_id, slot_id, i, cat_id,
            )

    for s in existing_slots:
        if s["sort_order"] >= len(configs):
            await db.execute(
                "UPDATE metric_slots SET enabled = FALSE WHERE id = $1",
                s["id"],
            )
    # Defensive rule: clear metric category_id when slots have categories
    if any(isinstance(c, dict) and c.get("category_id") for c in configs):
        await db.execute(
            "UPDATE metric_definitions SET category_id = NULL WHERE id = $1",
            metric_id,
        )
