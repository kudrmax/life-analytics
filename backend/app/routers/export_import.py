"""
Export and import data in CSV format.
"""
import csv
import json
from io import StringIO
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/csv")
async def export_csv(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Export all user data (entries) to CSV format.

    CSV format:
    date,metric_id,metric_name,timestamp,value_json
    """
    # Get all entries for user with metric names
    query = """
        SELECT
            e.date,
            e.metric_id,
            m.name as metric_name,
            e.timestamp,
            e.value_json
        FROM entries e
        JOIN metric_configs m ON e.metric_id = m.id AND e.user_id = m.user_id
        WHERE e.user_id = ?
        ORDER BY e.date DESC, e.timestamp DESC
    """
    cursor = await db.execute(query, (current_user["id"],))
    rows = await cursor.fetchall()

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(["date", "metric_id", "metric_name", "timestamp", "value_json"])

    # Write data
    for row in rows:
        writer.writerow([
            row[0],  # date
            row[1],  # metric_id
            row[2],  # metric_name
            row[3],  # timestamp
            row[4]   # value_json
        ])

    # Prepare response
    output.seek(0)
    filename = f"life_analytics_{current_user['username']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.post("/import")
async def import_csv(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Import entries from CSV file.

    Expected CSV format:
    date,metric_id,metric_name,timestamp,value_json

    - Skips entries that already exist (same metric_id, date, and value)
    - Only imports metrics that exist for the user
    - Returns summary of imported/skipped entries
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(400, "File must be a CSV")

    # Read and parse CSV
    content = await file.read()
    csv_text = content.decode('utf-8')
    reader = csv.DictReader(StringIO(csv_text))

    imported = 0
    skipped = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
        try:
            metric_id = row['metric_id']
            date = row['date']
            timestamp = row.get('timestamp', datetime.now().isoformat())
            value_json = row['value_json']

            # Check if metric exists for user
            metric_check = await db.execute(
                "SELECT id FROM metric_configs WHERE id = ? AND user_id = ?",
                (metric_id, current_user["id"])
            )
            if not await metric_check.fetchone():
                skipped += 1
                errors.append(f"Row {row_num}: Metric '{metric_id}' not found for user")
                continue

            # Check if entry already exists (same metric, date, and value)
            existing = await db.execute(
                "SELECT id FROM entries WHERE metric_id = ? AND date = ? AND value_json = ? AND user_id = ?",
                (metric_id, date, value_json, current_user["id"])
            )
            if await existing.fetchone():
                skipped += 1
                continue

            # Insert entry
            await db.execute(
                "INSERT INTO entries (metric_id, date, timestamp, value_json, user_id) VALUES (?, ?, ?, ?, ?)",
                (metric_id, date, timestamp, value_json, current_user["id"])
            )
            imported += 1

        except KeyError as e:
            errors.append(f"Row {row_num}: Missing column {e}")
            skipped += 1
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
            skipped += 1

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10] if errors else []  # Limit to first 10 errors
    }
