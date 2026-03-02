from collections import defaultdict
from datetime import date as date_type
from statistics import mean, stdev

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _extract_numeric(value_row) -> float | None:
    """Extract a numeric value from a bool value row (True=1, False=0)."""
    if not value_row:
        return None
    return 1.0 if value_row["value"] else 0.0


@router.get("/trends")
async def trends(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    metric = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_id, current_user["id"],
    )
    if not metric:
        return {"error": "Metric not found"}

    rows = await db.fetch(
        """SELECT e.date, v.value
            FROM entries e
            JOIN values_bool v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
            ORDER BY e.date""",
        metric_id, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
    )

    points = []
    for r in rows:
        v = _extract_numeric(r)
        if v is not None:
            points.append({
                "date": str(r["date"]),
                "value": v,
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
    metric_a: int = Query(...),
    metric_b: int = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    ma = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_a, current_user["id"],
    )
    mb = await db.fetchrow(
        "SELECT * FROM metric_definitions WHERE id = $1 AND user_id = $2",
        metric_b, current_user["id"],
    )
    if not ma or not mb:
        return {"error": "Metric not found"}

    async def values_by_date(mid):
        rows = await db.fetch(
            """SELECT e.date, v.value
                FROM entries e
                JOIN values_bool v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4""",
            mid, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
        )
        return {str(r["date"]): (1.0 if r["value"] else 0.0) for r in rows}

    a_by_date = await values_by_date(metric_a)
    b_by_date = await values_by_date(metric_b)

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
    metrics = await db.fetch(
        """SELECT * FROM metric_definitions
           WHERE enabled = TRUE AND user_id = $1 AND type = 'bool'
           ORDER BY sort_order""",
        current_user["id"],
    )

    result = []
    for m in metrics:
        rows = await db.fetch(
            """SELECT DISTINCT e.date, vb.value
               FROM entries e
               JOIN values_bool vb ON vb.entry_id = e.id
               WHERE e.metric_id = $1 AND e.user_id = $2
               ORDER BY e.date DESC""",
            m["id"], current_user["id"],
        )
        current_streak = 0
        for r in rows:
            if r["value"] is True:
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
