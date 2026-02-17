import json
from datetime import datetime, timedelta
from statistics import mean, stdev
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
import aiosqlite

from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def extract_numeric(value_json: str, metric_type: str) -> float | None:
    val = json.loads(value_json)
    if metric_type == "boolean":
        v = val.get("value")
        if isinstance(v, bool):
            return 1.0 if v else 0.0
    elif metric_type in ("scale", "number", "time"):
        v = val.get("value")
        if isinstance(v, (int, float)):
            return float(v)
    elif metric_type == "compound":
        # Try first numeric field
        for k, v in val.items():
            if isinstance(v, (int, float)):
                return float(v)
    return None


@router.get("/trends")
async def trends(
    metric_id: str = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    metric = await db.execute(
        "SELECT * FROM metric_configs WHERE id = ? AND user_id = ?", (metric_id, current_user["id"])
    )
    metric = await metric.fetchone()
    if not metric:
        return {"error": "Metric not found"}

    rows = await db.execute(
        "SELECT * FROM entries WHERE metric_id = ? AND date >= ? AND date <= ? AND user_id = ? ORDER BY date, timestamp",
        (metric_id, start, end, current_user["id"]),
    )
    entries = await rows.fetchall()

    # Group by date, aggregate
    by_date: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        v = extract_numeric(e["value_json"], metric["type"])
        if v is not None:
            by_date[e["date"]].append(v)

    points = []
    for d in sorted(by_date):
        vals = by_date[d]
        points.append({
            "date": d,
            "avg": round(mean(vals), 2),
            "min": min(vals),
            "max": max(vals),
            "count": len(vals),
        })

    return {
        "metric_id": metric_id,
        "metric_name": metric["name"],
        "start": start,
        "end": end,
        "points": points,
    }


@router.get("/correlations")
async def correlations(
    metric_a: str = Query(...),
    metric_b: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    ma = await db.execute("SELECT * FROM metric_configs WHERE id = ? AND user_id = ?", (metric_a, current_user["id"]))
    ma = await ma.fetchone()
    mb = await db.execute("SELECT * FROM metric_configs WHERE id = ? AND user_id = ?", (metric_b, current_user["id"]))
    mb = await mb.fetchone()
    if not ma or not mb:
        return {"error": "Metric not found"}

    # Get entries for both
    rows_a = await db.execute(
        "SELECT * FROM entries WHERE metric_id = ? AND date >= ? AND date <= ? AND user_id = ?",
        (metric_a, start, end, current_user["id"]),
    )
    rows_b = await db.execute(
        "SELECT * FROM entries WHERE metric_id = ? AND date >= ? AND date <= ? AND user_id = ?",
        (metric_b, start, end, current_user["id"]),
    )

    # Aggregate by date
    def aggregate_by_date(rows, mtype):
        by_date = defaultdict(list)
        for e in rows:
            v = extract_numeric(e["value_json"], mtype)
            if v is not None:
                by_date[e["date"]].append(v)
        return {d: mean(vs) for d, vs in by_date.items()}

    a_by_date = aggregate_by_date(await rows_a.fetchall(), ma["type"])
    b_by_date = aggregate_by_date(await rows_b.fetchall(), mb["type"])

    # Find common dates
    common = sorted(set(a_by_date) & set(b_by_date))
    if len(common) < 3:
        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "correlation": None,
            "message": "Not enough data (need at least 3 common days)",
        }

    xs = [a_by_date[d] for d in common]
    ys = [b_by_date[d] for d in common]

    # Pearson correlation
    n = len(common)
    mean_x, mean_y = mean(xs), mean(ys)
    try:
        std_x, std_y = stdev(xs), stdev(ys)
    except Exception:
        return {"metric_a": metric_a, "metric_b": metric_b, "correlation": None}

    if std_x == 0 or std_y == 0:
        return {"metric_a": metric_a, "metric_b": metric_b, "correlation": 0}

    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / (n - 1)
    r = cov / (std_x * std_y)

    return {
        "metric_a": metric_a,
        "metric_b": metric_b,
        "correlation": round(r, 3),
        "data_points": n,
        "pairs": [{"date": common[i], "a": round(xs[i], 2), "b": round(ys[i], 2)} for i in range(n)],
    }


@router.get("/streaks")
async def streaks(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    # Boolean metrics — consecutive days with value=true
    metrics = await db.execute(
        "SELECT * FROM metric_configs WHERE enabled = 1 AND type IN ('boolean', 'compound') AND user_id = ? ORDER BY sort_order",
        (current_user["id"],)
    )
    metrics = await metrics.fetchall()

    result = []
    for m in metrics:
        rows = await db.execute(
            "SELECT DISTINCT date, value_json FROM entries WHERE metric_id = ? AND user_id = ? ORDER BY date DESC",
            (m["id"], current_user["id"]),
        )
        entries = await rows.fetchall()

        current_streak = 0
        for e in entries:
            val = json.loads(e["value_json"])
            # Check if "positive" — true for boolean, or first boolean field true for compound
            positive = False
            if m["type"] == "boolean":
                positive = val.get("value") is True
            elif m["type"] == "compound":
                for v in val.values():
                    if isinstance(v, bool):
                        positive = v
                        break

            if positive:
                current_streak += 1
            else:
                break

        if current_streak > 0:
            result.append({
                "metric_id": m["id"],
                "metric_name": m["name"],
                "current_streak": current_streak,
            })

    return {"streaks": result}
