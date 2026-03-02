from collections import defaultdict
from datetime import date as date_type
from statistics import mean, stdev

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.auth import get_current_user
from app.metric_helpers import VALUE_TABLE_MAP, _decimal_to_num

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _extract_numeric(metric_type: str, value_row) -> float | None:
    """Extract a numeric value from a typed value row."""
    if not value_row:
        return None
    if metric_type == "bool":
        return 1.0 if value_row["value"] else 0.0
    elif metric_type == "scale":
        return float(value_row["value"])
    elif metric_type == "number":
        nv = value_row.get("number_value")
        if nv is not None:
            return float(nv)
        bv = value_row.get("bool_value")
        if bv is not None:
            return 1.0 if bv else 0.0
        return None
    elif metric_type == "time":
        t = value_row.get("value")
        if t:
            return t.hour * 60 + t.minute
        return None
    return None


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

    metric_type = metric["type"]
    value_table = VALUE_TABLE_MAP[metric_type]

    rows = await db.fetch(
        f"""SELECT e.date, v.*
            FROM entries e
            JOIN {value_table} v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
            ORDER BY e.date""",
        metric_id, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
    )

    by_date: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        v = _extract_numeric(metric_type, r)
        if v is not None:
            by_date[str(r["date"])].append(v)

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

    async def aggregate_by_date(mid, mtype):
        vtable = VALUE_TABLE_MAP[mtype]
        rows = await db.fetch(
            f"""SELECT e.date, v.*
                FROM entries e
                JOIN {vtable} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4""",
            mid, date_type.fromisoformat(start), date_type.fromisoformat(end), current_user["id"],
        )
        by_date = defaultdict(list)
        for r in rows:
            v = _extract_numeric(mtype, r)
            if v is not None:
                by_date[str(r["date"])].append(v)
        return {d: mean(vs) for d, vs in by_date.items()}

    a_by_date = await aggregate_by_date(metric_a, ma["type"])
    b_by_date = await aggregate_by_date(metric_b, mb["type"])

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
    # Bool metrics and number metrics with bool_number display
    metrics = await db.fetch(
        """SELECT md.* FROM metric_definitions md
           WHERE md.enabled = TRUE AND md.user_id = $1
           AND (
               md.type = 'bool'
               OR (md.type = 'number' AND EXISTS (
                   SELECT 1 FROM config_number cn
                   WHERE cn.metric_id = md.id AND cn.display_mode = 'bool_number'
               ))
           )
           ORDER BY md.sort_order""",
        current_user["id"],
    )

    result = []
    for m in metrics:
        metric_type = m["type"]

        if metric_type == "bool":
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

        elif metric_type == "number":
            rows = await db.fetch(
                """SELECT DISTINCT e.date, vn.bool_value
                   FROM entries e
                   JOIN values_number vn ON vn.entry_id = e.id
                   WHERE e.metric_id = $1 AND e.user_id = $2
                   ORDER BY e.date DESC""",
                m["id"], current_user["id"],
            )
            current_streak = 0
            for r in rows:
                if r["bool_value"] is True:
                    current_streak += 1
                else:
                    break

        else:
            continue

        if current_streak > 0:
            result.append({
                "metric_id": m["id"],
                "metric_name": m["name"],
                "current_streak": current_streak,
            })

    return {"streaks": result}
