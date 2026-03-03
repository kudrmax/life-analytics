from collections import defaultdict
from datetime import date as date_type
from statistics import mean, stdev

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _extract_numeric(value_row, metric_type: str = "bool") -> float | None:
    """Extract a numeric value from a value row.

    For bool: True=1, False=0.
    For time: minutes from midnight (e.g. 23:30 -> 1410).
    """
    if not value_row:
        return None
    v = value_row["value"]
    if metric_type == "time":
        # v is a datetime (TIMESTAMPTZ)
        return v.hour * 60 + v.minute
    elif metric_type == "number":
        return float(v)
    elif metric_type == "scale":
        v_min = value_row["scale_min"]
        v_max = value_row["scale_max"]
        if v_max == v_min:
            return 0.0
        return (float(v) - v_min) / (v_max - v_min) * 100
    return 1.0 if v else 0.0


def _aggregate_by_date(rows, metric_type: str) -> dict[str, float]:
    """Group rows by date, aggregate multiple entries per day (multi-slot).

    For number/scale/time: mean of values per day.
    For bool: 1.0 if any True, else 0.0.
    """
    day_values: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = _extract_numeric(r, metric_type)
        if v is not None:
            day_values[str(r["date"])].append(v)

    result = {}
    for d, vals in day_values.items():
        if metric_type == "bool":
            result[d] = 1.0 if any(v == 1.0 for v in vals) else 0.0
        else:
            result[d] = mean(vals)
    return result


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

    mt = metric["type"]
    if mt == "time":
        value_table = "values_time"
    elif mt == "number":
        value_table = "values_number"
    elif mt == "scale":
        value_table = "values_scale"
    else:
        value_table = "values_bool"

    extra_cols = ", v.scale_min, v.scale_max, v.scale_step" if mt == "scale" else ""
    rows = await db.fetch(
        f"""SELECT e.date, v.value{extra_cols}
            FROM entries e
            JOIN {value_table} v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
            ORDER BY e.date""",
        metric_id, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
    )

    # Aggregate multi-slot entries by date
    aggregated = _aggregate_by_date(rows, mt)
    points = [{"date": d, "value": v} for d, v in sorted(aggregated.items())]

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

    async def values_by_date(mid, mt):
        if mt == "time":
            value_table = "values_time"
        elif mt == "number":
            value_table = "values_number"
        elif mt == "scale":
            value_table = "values_scale"
        else:
            value_table = "values_bool"
        extra_cols = ", v.scale_min, v.scale_max, v.scale_step" if mt == "scale" else ""
        rows = await db.fetch(
            f"""SELECT e.date, v.value{extra_cols}
                FROM entries e
                JOIN {value_table} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4""",
            mid, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
        )
        return _aggregate_by_date(rows, mt)

    a_by_date = await values_by_date(metric_a, ma["type"])
    b_by_date = await values_by_date(metric_b, mb["type"])

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
        # Group by date: day counts as True only if ALL slot entries are True
        rows = await db.fetch(
            """SELECT e.date, bool_and(vb.value) AS day_value
               FROM entries e
               JOIN values_bool vb ON vb.entry_id = e.id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY e.date
               ORDER BY e.date DESC""",
            m["id"], current_user["id"],
        )
        current_streak = 0
        for r in rows:
            if r["day_value"] is True:
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
