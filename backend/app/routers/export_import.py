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
            'id', 'slug', 'name', 'category', 'icon', 'type',
            'enabled', 'sort_order', 'scale_min', 'scale_max', 'scale_step',
            'slot_labels', 'formula', 'result_type', 'provider', 'metric_key',
        ])

        metrics = await db.fetch(
            """SELECT md.*, sc.scale_min, sc.scale_max, sc.scale_step,
                      ic.provider, ic.metric_key
               FROM metric_definitions md
               LEFT JOIN scale_config sc ON sc.metric_id = md.id
               LEFT JOIN integration_config ic ON ic.metric_id = md.id
               WHERE md.user_id = $1 ORDER BY md.sort_order, md.id""",
            current_user["id"],
        )

        # Get slots for all metrics
        metric_ids = [m["id"] for m in metrics]
        all_slots_rows = await db.fetch(
            """SELECT metric_id, label, sort_order FROM measurement_slots
               WHERE metric_id = ANY($1) AND enabled = TRUE
               ORDER BY metric_id, sort_order""",
            metric_ids,
        ) if metric_ids else []

        slots_by_metric: dict[int, list[str]] = defaultdict(list)
        for r in all_slots_rows:
            slots_by_metric[r["metric_id"]].append(r["label"])

        # Load computed_config for all metrics
        computed_cfg_rows = await db.fetch(
            "SELECT metric_id, formula, result_type FROM computed_config WHERE metric_id = ANY($1)",
            metric_ids,
        ) if metric_ids else []
        computed_cfgs = {r["metric_id"]: r for r in computed_cfg_rows}

        for m in metrics:
            slot_labels = slots_by_metric.get(m["id"], [])
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
            metrics_writer.writerow([
                m["id"], m["slug"], m["name"], m["category"], m.get("icon", ""), m["type"],
                1 if m["enabled"] else 0, m["sort_order"],
                m["scale_min"] if m["scale_min"] is not None else '',
                m["scale_max"] if m["scale_max"] is not None else '',
                m["scale_step"] if m["scale_step"] is not None else '',
                json.dumps(slot_labels) if slot_labels else '',
                formula_export, result_type_export,
                m.get("provider") or '', m.get("metric_key") or '',
            ])

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())

        # Export entries
        entries_csv = StringIO()
        entries_writer = csv.writer(entries_csv)
        entries_writer.writerow(['date', 'metric_slug', 'value', 'slot_sort_order', 'slot_label'])

        slug_lookup = {m["id"]: m["slug"] for m in metrics}
        type_lookup = {m["id"]: m["type"] for m in metrics}

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
            if mt == "computed":
                continue  # computed metrics have no stored entries
            value = await get_entry_value(db, e["id"], mt)
            entries_writer.writerow([
                str(e["date"]), slug,
                json.dumps(value),
                e["slot_sort_order"] if e["slot_sort_order"] is not None else '',
                e["slot_label"] or '',
            ])

        zip_file.writestr('entries.csv', entries_csv.getvalue())

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
                    category = row.get('category', '')
                    icon = row.get('icon', '')
                    enabled = row.get('enabled', '1') in ('1', 'True', 'true', True)
                    sort_order = int(row.get('sort_order', 0))

                    existing = await db.fetchrow(
                        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
                        slug, current_user["id"],
                    )

                    metric_type = row.get('type', 'bool')
                    if metric_type not in ('bool', 'time', 'number', 'scale', 'computed', 'integration'):
                        metric_type = 'bool'

                    # Parse scale config from CSV
                    csv_scale_min = row.get('scale_min', '')
                    csv_scale_max = row.get('scale_max', '')
                    csv_scale_step = row.get('scale_step', '')

                    # Parse slot_labels from CSV
                    csv_slot_labels_raw = row.get('slot_labels', '')
                    csv_slot_labels = []
                    if csv_slot_labels_raw:
                        try:
                            csv_slot_labels = json.loads(csv_slot_labels_raw)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if existing:
                        await db.execute(
                            """UPDATE metric_definitions
                               SET name = $1, category = $2, enabled = $3, sort_order = $4, icon = $5
                               WHERE id = $6 AND user_id = $7""",
                            name, category, enabled, sort_order, icon,
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
                        # Import slots if provided
                        if len(csv_slot_labels) >= 2:
                            await _import_slots(db, existing["id"], csv_slot_labels)
                        metrics_updated += 1
                    else:
                        new_id = await db.fetchval(
                            """INSERT INTO metric_definitions
                               (user_id, slug, name, category, icon, type, enabled, sort_order)
                               VALUES ($1, $2, $3, $4, $5, $6::metric_type, $7, $8) RETURNING id""",
                            current_user["id"], slug, name, category, icon,
                            metric_type, enabled, sort_order,
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
                        # Create slots if provided
                        if len(csv_slot_labels) >= 2:
                            for i, label in enumerate(csv_slot_labels):
                                await db.execute(
                                    "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                                    new_id, i, label,
                                )
                        metrics_imported += 1

                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            # Build slug->id and slug->type lookups after metric import
            metric_rows = await db.fetch(
                "SELECT id, slug, type FROM metric_definitions WHERE user_id = $1",
                current_user["id"],
            )
            slug_to_id = {r["slug"]: r["id"] for r in metric_rows}
            slug_to_type = {r["slug"]: r["type"] for r in metric_rows}

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

            # Build metric_id -> {sort_order: slot_id} lookup
            all_metric_ids = list(slug_to_id.values())
            slot_rows = await db.fetch(
                """SELECT id, metric_id, sort_order FROM measurement_slots
                   WHERE metric_id = ANY($1)""",
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
                    if slug_to_type.get(slug) == "computed":
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
                                new_slot_id = await db.fetchval(
                                    "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3) RETURNING id",
                                    metric_id, so, csv_slot_label or '',
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

                    if mt == "time":
                        # value should be "HH:MM" string
                        if not isinstance(value, str):
                            entries_skipped += 1
                            continue
                    elif mt in ("number", "integration"):
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


async def _import_slots(db, metric_id: int, labels: list[str]):
    """Create or update slots during import (same logic as update_metric)."""
    existing_slots = await db.fetch(
        "SELECT * FROM measurement_slots WHERE metric_id = $1 ORDER BY sort_order",
        metric_id,
    )
    for i, label in enumerate(labels):
        matching = [s for s in existing_slots if s["sort_order"] == i]
        if matching:
            await db.execute(
                "UPDATE measurement_slots SET label = $1, enabled = TRUE WHERE id = $2",
                label, matching[0]["id"],
            )
        else:
            await db.execute(
                "INSERT INTO measurement_slots (metric_id, sort_order, label) VALUES ($1, $2, $3)",
                metric_id, i, label,
            )
    for s in existing_slots:
        if s["sort_order"] >= len(labels):
            await db.execute(
                "UPDATE measurement_slots SET enabled = FALSE WHERE id = $1",
                s["id"],
            )
