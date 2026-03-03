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
            'id', 'slug', 'name', 'category', 'type',
            'enabled', 'sort_order',
        ])

        metrics = await db.fetch(
            "SELECT * FROM metric_definitions WHERE user_id = $1 ORDER BY sort_order, id",
            current_user["id"],
        )

        for m in metrics:
            metrics_writer.writerow([
                m["id"], m["slug"], m["name"], m["category"], m["type"],
                1 if m["enabled"] else 0, m["sort_order"],
            ])

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())

        # Export entries
        entries_csv = StringIO()
        entries_writer = csv.writer(entries_csv)
        entries_writer.writerow(['date', 'metric_slug', 'value'])

        slug_lookup = {m["id"]: m["slug"] for m in metrics}
        type_lookup = {m["id"]: m["type"] for m in metrics}

        entries = await db.fetch(
            "SELECT * FROM entries WHERE user_id = $1 ORDER BY date DESC, metric_id",
            current_user["id"],
        )

        for e in entries:
            slug = slug_lookup.get(e["metric_id"])
            if not slug:
                continue

            mt = type_lookup.get(e["metric_id"], "bool")
            value = await get_entry_value(db, e["id"], mt)
            entries_writer.writerow([
                str(e["date"]), slug,
                json.dumps(value),
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
                    enabled = row.get('enabled', '1') in ('1', 'True', 'true', True)
                    sort_order = int(row.get('sort_order', 0))

                    existing = await db.fetchrow(
                        "SELECT id FROM metric_definitions WHERE slug = $1 AND user_id = $2",
                        slug, current_user["id"],
                    )

                    metric_type = row.get('type', 'bool')
                    if metric_type not in ('bool', 'time', 'number'):
                        metric_type = 'bool'

                    if existing:
                        await db.execute(
                            """UPDATE metric_definitions
                               SET name = $1, category = $2, enabled = $3, sort_order = $4
                               WHERE id = $5 AND user_id = $6""",
                            name, category, enabled, sort_order,
                            existing["id"], current_user["id"],
                        )
                        metrics_updated += 1
                    else:
                        await db.fetchval(
                            """INSERT INTO metric_definitions
                               (user_id, slug, name, category, type, enabled, sort_order)
                               VALUES ($1, $2, $3, $4, $5::metric_type, $6, $7) RETURNING id""",
                            current_user["id"], slug, name, category,
                            metric_type, enabled, sort_order,
                        )
                        metrics_imported += 1

                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            # Build slug→id and slug→type lookups after metric import
            metric_rows = await db.fetch(
                "SELECT id, slug, type FROM metric_definitions WHERE user_id = $1",
                current_user["id"],
            )
            slug_to_id = {r["slug"]: r["id"] for r in metric_rows}
            slug_to_type = {r["slug"]: r["type"] for r in metric_rows}

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

                    date = row['date']
                    d = date_type.fromisoformat(date)

                    existing = await db.fetchval(
                        "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3",
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
                    elif mt == "number":
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
                            "INSERT INTO entries (metric_id, user_id, date) VALUES ($1, $2, $3) RETURNING id",
                            metric_id, current_user["id"], d,
                        )
                        await insert_value(db, entry_id, value, mt, entry_date=d)

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
