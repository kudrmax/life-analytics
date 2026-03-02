"""
Export and import data in ZIP format (metrics + entries).
"""
import csv
import json
import zipfile
from io import StringIO, BytesIO
from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import (
    get_config_for_metric, get_measurement_labels,
    insert_config, update_config,
    insert_measurement_labels, replace_measurement_labels,
    insert_value, VALUE_TABLE_MAP, _decimal_to_num,
)

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_data(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export metrics
        metrics_csv = StringIO()
        metrics_writer = csv.writer(metrics_csv)
        metrics_writer.writerow([
            'id', 'slug', 'name', 'category', 'type',
            'enabled', 'sort_order', 'measurements_per_day',
            'measurement_labels_json', 'config_json',
        ])

        metrics = await db.fetch(
            "SELECT * FROM metric_definitions WHERE user_id = $1 ORDER BY sort_order, id",
            current_user["id"],
        )

        for m in metrics:
            config = await get_config_for_metric(db, m["id"], m["type"])
            labels = await get_measurement_labels(db, m["id"])
            metrics_writer.writerow([
                m["id"], m["slug"], m["name"], m["category"], m["type"],
                1 if m["enabled"] else 0, m["sort_order"], m["measurements_per_day"],
                json.dumps(labels, ensure_ascii=False),
                json.dumps(config, ensure_ascii=False),
            ])

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())

        # Export entries
        entries_csv = StringIO()
        entries_writer = csv.writer(entries_csv)
        entries_writer.writerow(['date', 'metric_slug', 'measurement_number', 'value_json'])

        # Build slug lookup
        slug_lookup = {m["id"]: m["slug"] for m in metrics}
        type_lookup = {m["id"]: m["type"] for m in metrics}

        entries = await db.fetch(
            "SELECT * FROM entries WHERE user_id = $1 ORDER BY date DESC, metric_id",
            current_user["id"],
        )

        for e in entries:
            metric_type = type_lookup.get(e["metric_id"])
            slug = slug_lookup.get(e["metric_id"])
            if not metric_type or not slug:
                continue

            vtable = VALUE_TABLE_MAP[metric_type]
            val_row = await db.fetchrow(f"SELECT * FROM {vtable} WHERE entry_id = $1", e["id"])

            if metric_type == "bool" and val_row:
                value = {"value": val_row["value"]}
            elif metric_type == "number" and val_row:
                value = {
                    "bool_value": val_row["bool_value"],
                    "number_value": _decimal_to_num(val_row["number_value"]),
                }
            elif metric_type == "scale" and val_row:
                value = {"value": val_row["value"]}
            elif metric_type == "time" and val_row:
                value = {"value": val_row["value"].strftime("%H:%M") if val_row["value"] else None}
            else:
                value = {}

            entries_writer.writerow([
                str(e["date"]), slug, e["measurement_number"],
                json.dumps(value, ensure_ascii=False),
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

            # Detect format (new vs old)
            metrics_csv_text = zip_file.read('metrics.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(metrics_csv_text))
            fieldnames = reader.fieldnames or []
            is_new_format = 'slug' in fieldnames

            # Import metrics
            reader = csv.DictReader(StringIO(metrics_csv_text))

            for row_num, row in enumerate(reader, start=2):
                try:
                    # Check if metric exists BEFORE import to track insert vs update
                    slug = row.get('slug') or row.get('id', '')
                    existing_before = await db.fetchval(
                        "SELECT COUNT(*) FROM metric_definitions WHERE slug = $1 AND user_id = $2",
                        slug, current_user["id"],
                    )

                    if is_new_format:
                        await _import_metric_new_format(db, row, current_user["id"])
                    else:
                        await _import_metric_old_format(db, row, current_user["id"])

                    if existing_before > 0:
                        metrics_updated += 1
                    else:
                        metrics_imported += 1

                except KeyError as e:
                    metrics_errors.append(f"Row {row_num}: Missing column {e}")
                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            # Build slug→id lookup after metric import
            metric_rows = await db.fetch(
                "SELECT id, slug, type FROM metric_definitions WHERE user_id = $1",
                current_user["id"],
            )
            slug_to_info = {r["slug"]: {"id": r["id"], "type": r["type"]} for r in metric_rows}

            # Import entries
            entries_csv_text = zip_file.read('entries.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(entries_csv_text))
            entry_fieldnames = reader.fieldnames or []
            is_new_entry_format = 'metric_slug' in entry_fieldnames

            reader = csv.DictReader(StringIO(entries_csv_text))

            for row_num, row in enumerate(reader, start=2):
                try:
                    if is_new_entry_format:
                        slug = row['metric_slug']
                        measurement_number = int(row.get('measurement_number', 1))
                    else:
                        # Old format: metric_id is slug
                        slug = row['metric_id']
                        measurement_number = 1
                        # Try to extract period from old value_json
                        old_value = json.loads(row.get('value_json', '{}'))
                        period = old_value.get('period')
                        if period:
                            period_map = {'morning': 1, 'day': 2, 'evening': 3}
                            measurement_number = period_map.get(period, 1)

                    info = slug_to_info.get(slug)
                    if not info:
                        entries_skipped += 1
                        continue

                    metric_id = info["id"]
                    metric_type = info["type"]
                    date = row['date']

                    # Check for duplicate
                    d = date_type.fromisoformat(date)
                    existing = await db.fetchval(
                        """SELECT id FROM entries
                           WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND measurement_number = $4""",
                        metric_id, current_user["id"], d, measurement_number,
                    )
                    if existing:
                        entries_skipped += 1
                        continue

                    value_json = json.loads(row.get('value_json', '{}'))

                    # Transform old value format if needed
                    if not is_new_entry_format:
                        value_json = _transform_old_value(metric_type, value_json)

                    async with db.transaction():
                        entry_id = await db.fetchval(
                            """INSERT INTO entries (metric_id, user_id, date, measurement_number)
                               VALUES ($1, $2, $3, $4) RETURNING id""",
                            metric_id, current_user["id"], d, measurement_number,
                        )
                        await insert_value(db, entry_id, metric_type, value_json)

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


async def _import_metric_new_format(conn, row: dict, user_id: int):
    slug = row['slug']
    config = json.loads(row.get('config_json', '{}'))
    labels = json.loads(row.get('measurement_labels_json', '[]'))
    metric_type = row['type']

    existing = await conn.fetchrow(
        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
        slug, user_id,
    )

    if existing:
        async with conn.transaction():
            await conn.execute(
                """UPDATE metric_definitions
                   SET name = $1, category = $2, enabled = $3, sort_order = $4,
                       measurements_per_day = $5
                   WHERE id = $6 AND user_id = $7""",
                row['name'], row.get('category', ''),
                row.get('enabled', '1') in ('1', 'True', 'true', True),
                int(row.get('sort_order', 0)),
                int(row.get('measurements_per_day', 1)),
                existing["id"], user_id,
            )
            await update_config(conn, existing["id"], metric_type, config)
            await replace_measurement_labels(conn, existing["id"], labels)
    else:
        async with conn.transaction():
            metric_id = await conn.fetchval(
                """INSERT INTO metric_definitions
                   (user_id, slug, name, category, type, enabled, sort_order, measurements_per_day)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                user_id, slug, row['name'], row.get('category', ''),
                metric_type,
                row.get('enabled', '1') in ('1', 'True', 'true', True),
                int(row.get('sort_order', 0)),
                int(row.get('measurements_per_day', 1)),
            )
            await insert_config(conn, metric_id, metric_type, config)
            if labels:
                await insert_measurement_labels(conn, metric_id, labels)


async def _import_metric_old_format(conn, row: dict, user_id: int):
    """Import from old SQLite-based ZIP format."""
    old_id = row['id']  # This becomes the slug
    old_type = row['type']
    old_config = json.loads(row.get('config_json', '{}'))
    old_frequency = row.get('frequency', 'daily')

    # Map old types to new
    type_map = {'boolean': 'bool', 'scale': 'scale', 'number': 'number', 'time': 'time'}
    new_type = type_map.get(old_type)

    measurements_per_day = 1
    labels = []

    if old_type == 'compound':
        new_type = 'number'
        new_config = _transform_compound_config(old_config)
    elif old_type == 'enum':
        new_type = 'bool'
        new_config = {}
    else:
        new_config = _transform_old_config(old_type, old_config)

    if not new_type:
        new_type = 'bool'
        new_config = {}

    if old_frequency == 'multiple':
        measurements_per_day = 3
        labels = ["Утро", "День", "Вечер"]

    existing = await conn.fetchrow(
        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
        old_id, user_id,
    )

    if existing:
        async with conn.transaction():
            await conn.execute(
                """UPDATE metric_definitions
                   SET name = $1, category = $2, enabled = $3, sort_order = $4,
                       measurements_per_day = $5
                   WHERE id = $6 AND user_id = $7""",
                row['name'], row.get('category', ''),
                int(row.get('enabled', 1)) == 1,
                int(row.get('sort_order', 0)),
                measurements_per_day,
                existing["id"], user_id,
            )
            await update_config(conn, existing["id"], new_type, new_config)
            await replace_measurement_labels(conn, existing["id"], labels)
    else:
        async with conn.transaction():
            metric_id = await conn.fetchval(
                """INSERT INTO metric_definitions
                   (user_id, slug, name, category, type, enabled, sort_order, measurements_per_day)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                user_id, old_id, row['name'], row.get('category', ''),
                new_type,
                int(row.get('enabled', 1)) == 1,
                int(row.get('sort_order', 0)),
                measurements_per_day,
            )
            await insert_config(conn, metric_id, new_type, new_config)
            if labels:
                await insert_measurement_labels(conn, metric_id, labels)


def _transform_compound_config(old_config: dict) -> dict:
    fields = old_config.get('fields', [])
    bool_field = next((f for f in fields if f.get('type') == 'boolean'), None)
    num_field = next((f for f in fields if f.get('type') == 'number'), None)

    return {
        "display_mode": "bool_number",
        "bool_label": bool_field.get("label", "") if bool_field else "",
        "number_label": num_field.get("label", "") if num_field else "",
        "min_value": 0,
        "max_value": 100,
        "step": 1,
    }


def _transform_old_config(old_type: str, old_config: dict) -> dict:
    if old_type == 'scale':
        return {
            "min_value": old_config.get("min", 1),
            "max_value": old_config.get("max", 5),
            "step": old_config.get("step", 1),
        }
    elif old_type == 'number':
        return {
            "min_value": old_config.get("min", 0),
            "max_value": old_config.get("max", 999),
            "step": old_config.get("step", 1),
            "unit_label": old_config.get("label", ""),
            "display_mode": "number_only",
        }
    elif old_type == 'time':
        return {"placeholder": ""}
    elif old_type == 'boolean':
        return {}
    return {}


def _transform_old_value(metric_type: str, old_value: dict) -> dict:
    """Transform old value_json format to new format."""
    if metric_type == "bool":
        v = old_value.get("value")
        if isinstance(v, bool):
            return {"value": v}
        # Compound that was mapped to bool
        for val in old_value.values():
            if isinstance(val, bool):
                return {"value": val}
        return {"value": False}

    elif metric_type == "number":
        # Could be old number {value: X} or old compound {had_coffee: true, cups: 2}
        if "value" in old_value and not any(isinstance(v, bool) for k, v in old_value.items() if k != "period"):
            return {"bool_value": None, "number_value": old_value.get("value")}
        # Compound format
        bool_val = None
        num_val = None
        for k, v in old_value.items():
            if k == "period":
                continue
            if isinstance(v, bool):
                bool_val = v
            elif isinstance(v, (int, float)):
                num_val = v
        return {"bool_value": bool_val, "number_value": num_val}

    elif metric_type == "scale":
        return {"value": old_value.get("value", 0)}

    elif metric_type == "time":
        return {"value": old_value.get("value", "00:00")}

    return old_value
