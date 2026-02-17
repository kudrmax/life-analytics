"""
Export and import data in ZIP format (metrics + entries).
"""
import csv
import json
import zipfile
from io import StringIO, BytesIO
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_data(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Export all user data (metrics + entries) as a ZIP archive with two CSV files.

    ZIP contains:
    - metrics.csv: metric configurations
    - entries.csv: metric values
    """
    # Create ZIP in memory
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export metrics
        metrics_csv = StringIO()
        metrics_writer = csv.writer(metrics_csv)
        metrics_writer.writerow(['id', 'name', 'category', 'type', 'frequency', 'source', 'config_json', 'enabled', 'sort_order'])

        cursor = await db.execute(
            "SELECT id, name, category, type, frequency, source, config_json, enabled, sort_order FROM metric_configs WHERE user_id = ? ORDER BY sort_order, rowid",
            (current_user["id"],)
        )
        metrics = await cursor.fetchall()

        for m in metrics:
            metrics_writer.writerow(m)

        zip_file.writestr('metrics.csv', metrics_csv.getvalue())

        # Export entries
        entries_csv = StringIO()
        entries_writer = csv.writer(entries_csv)
        entries_writer.writerow(['date', 'metric_id', 'timestamp', 'value_json'])

        cursor = await db.execute(
            "SELECT date, metric_id, timestamp, value_json FROM entries WHERE user_id = ? ORDER BY date DESC, timestamp DESC",
            (current_user["id"],)
        )
        entries = await cursor.fetchall()

        for e in entries:
            entries_writer.writerow(e)

        zip_file.writestr('entries.csv', entries_csv.getvalue())

    # Prepare response
    zip_buffer.seek(0)
    filename = f"life_analytics_{current_user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Import data from ZIP archive containing metrics.csv and entries.csv.

    Steps:
    1. Import metrics (creates missing metrics, updates existing)
    2. Import entries (skips duplicates)

    Returns summary of imported/skipped/errors for both metrics and entries.
    """
    if not file.filename.endswith('.zip'):
        raise HTTPException(400, "File must be a ZIP archive")

    # Read ZIP file
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
            # Check required files
            if 'metrics.csv' not in zip_file.namelist():
                raise HTTPException(400, "ZIP must contain metrics.csv")
            if 'entries.csv' not in zip_file.namelist():
                raise HTTPException(400, "ZIP must contain entries.csv")

            # Import metrics first
            metrics_csv = zip_file.read('metrics.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(metrics_csv))

            for row_num, row in enumerate(reader, start=2):
                try:
                    metric_id = row['id']

                    # Check if metric exists
                    cursor = await db.execute(
                        "SELECT id FROM metric_configs WHERE id = ? AND user_id = ?",
                        (metric_id, current_user["id"])
                    )
                    existing = await cursor.fetchone()

                    if existing:
                        # Update existing metric
                        await db.execute(
                            """UPDATE metric_configs
                               SET name = ?, category = ?, type = ?, frequency = ?, source = ?,
                                   config_json = ?, enabled = ?, sort_order = ?
                               WHERE id = ? AND user_id = ?""",
                            (row['name'], row['category'], row['type'], row['frequency'],
                             row['source'], row['config_json'], int(row['enabled']),
                             int(row['sort_order']), metric_id, current_user["id"])
                        )
                        metrics_updated += 1
                    else:
                        # Create new metric
                        await db.execute(
                            """INSERT INTO metric_configs
                               (id, name, category, type, frequency, source, config_json, enabled, sort_order, user_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (metric_id, row['name'], row['category'], row['type'],
                             row['frequency'], row['source'], row['config_json'],
                             int(row['enabled']), int(row['sort_order']), current_user["id"])
                        )
                        metrics_imported += 1

                except KeyError as e:
                    metrics_errors.append(f"Row {row_num}: Missing column {e}")
                except Exception as e:
                    metrics_errors.append(f"Row {row_num}: {str(e)}")

            await db.commit()

            # Import entries
            entries_csv = zip_file.read('entries.csv').decode('utf-8')
            reader = csv.DictReader(StringIO(entries_csv))

            for row_num, row in enumerate(reader, start=2):
                try:
                    metric_id = row['metric_id']
                    date = row['date']
                    timestamp = row.get('timestamp', datetime.now().isoformat())
                    value_json = row['value_json']

                    # Check if metric exists for user
                    cursor = await db.execute(
                        "SELECT id FROM metric_configs WHERE id = ? AND user_id = ?",
                        (metric_id, current_user["id"])
                    )
                    if not await cursor.fetchone():
                        entries_skipped += 1
                        entries_errors.append(f"Row {row_num}: Metric '{metric_id}' not found")
                        continue

                    # Check if entry already exists
                    cursor = await db.execute(
                        "SELECT id FROM entries WHERE metric_id = ? AND date = ? AND value_json = ? AND user_id = ?",
                        (metric_id, date, value_json, current_user["id"])
                    )
                    if await cursor.fetchone():
                        entries_skipped += 1
                        continue

                    # Insert entry
                    await db.execute(
                        "INSERT INTO entries (metric_id, date, timestamp, value_json, user_id) VALUES (?, ?, ?, ?, ?)",
                        (metric_id, date, timestamp, value_json, current_user["id"])
                    )
                    entries_imported += 1

                except KeyError as e:
                    entries_errors.append(f"Row {row_num}: Missing column {e}")
                    entries_skipped += 1
                except Exception as e:
                    entries_errors.append(f"Row {row_num}: {str(e)}")
                    entries_skipped += 1

            await db.commit()

    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    except Exception as e:
        raise HTTPException(500, f"Import failed: {str(e)}")

    return {
        "metrics": {
            "imported": metrics_imported,
            "updated": metrics_updated,
            "errors": metrics_errors[:10] if metrics_errors else []
        },
        "entries": {
            "imported": entries_imported,
            "skipped": entries_skipped,
            "errors": entries_errors[:10] if entries_errors else []
        }
    }
