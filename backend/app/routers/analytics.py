import asyncio
import logging
import math
from collections import defaultdict
from datetime import date as date_type
from statistics import mean, median, stdev

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import database as _db_module
from app.database import get_db
from app.auth import get_current_user

logger = logging.getLogger(__name__)

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


def _get_value_table(mt: str) -> tuple[str, str]:
    """Return (table_name, extra_cols) for a metric type."""
    if mt == "time":
        return "values_time", ""
    elif mt == "number":
        return "values_number", ""
    elif mt == "scale":
        return "values_scale", ", v.scale_min, v.scale_max, v.scale_step"
    return "values_bool", ""


async def _values_by_date_for_slot(
    conn, metric_id: int, metric_type: str,
    start_date, end_date, user_id: int, slot_id: int | None = None,
) -> dict[str, float]:
    """Get values by date for a metric, optionally filtered by slot."""
    value_table, extra_cols = _get_value_table(metric_type)
    slot_filter = ""
    params = [metric_id, start_date, end_date, user_id]
    if slot_id is not None:
        slot_filter = " AND e.slot_id = $5"
        params.append(slot_id)

    rows = await conn.fetch(
        f"""SELECT e.date, v.value{extra_cols}
            FROM entries e
            JOIN {value_table} v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3
              AND e.user_id = $4{slot_filter}
            ORDER BY e.date""",
        *params,
    )
    return _aggregate_by_date(rows, metric_type)


def _compute_pearson(
    a_by_date: dict[str, float], b_by_date: dict[str, float],
) -> tuple[float | None, int]:
    """Compute Pearson r between two date→value dicts. Returns (r, n)."""
    common = sorted(set(a_by_date) & set(b_by_date))
    n = len(common)
    if n < 3:
        return None, n

    xs = [a_by_date[d] for d in common]
    ys = [b_by_date[d] for d in common]

    mean_x, mean_y = mean(xs), mean(ys)
    try:
        std_x, std_y = stdev(xs), stdev(ys)
    except Exception:
        return None, n
    if std_x == 0 or std_y == 0:
        return 0.0, n

    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / (n - 1)
    r = cov / (std_x * std_y)
    return round(r, 3), n


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for regularized incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - ln_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _p_value(r: float, n: int) -> float:
    """Two-tailed p-value for Pearson correlation coefficient."""
    if n <= 2:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t_sq = r * r * df / (1.0 - r * r)
    return _betai(df / 2.0, 0.5, df / (df + t_sq))


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

    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    a_by_date = await _values_by_date_for_slot(db, metric_a, ma["type"], start_date, end_date, current_user["id"])
    b_by_date = await _values_by_date_for_slot(db, metric_b, mb["type"], start_date, end_date, current_user["id"])

    r, n = _compute_pearson(a_by_date, b_by_date)

    if r is None:
        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "correlation": None,
            "message": "Not enough data (need at least 3 common days)",
        }

    common = sorted(set(a_by_date) & set(b_by_date))
    return {
        "metric_a": metric_a,
        "metric_b": metric_b,
        "correlation": r,
        "data_points": n,
        "pairs": [{"date": d, "a": round(a_by_date[d], 2), "b": round(b_by_date[d], 2)} for d in common],
    }


@router.get("/metric-stats")
async def metric_stats(
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
    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    total_days = (end_date - start_date).days + 1

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
        metric_id, start_date, end_date, current_user["id"],
    )

    aggregated = _aggregate_by_date(rows, mt)
    total_entries = len(aggregated)
    fill_rate = round(total_entries / total_days * 100, 1) if total_days > 0 else 0

    result = {
        "metric_id": metric_id,
        "metric_type": mt,
        "total_entries": total_entries,
        "total_days": total_days,
        "fill_rate": fill_rate,
    }

    values = sorted(aggregated.values())

    if mt == "bool":
        yes_count = sum(1 for v in aggregated.values() if v == 1.0)
        no_count = total_entries - yes_count
        yes_percent = round(yes_count / total_entries * 100, 1) if total_entries > 0 else 0
        # Streaks — reuse logic from /streaks
        streak_rows = await db.fetch(
            """SELECT e.date, bool_and(vb.value) AS day_value
               FROM entries e
               JOIN values_bool vb ON vb.entry_id = e.id
               WHERE e.metric_id = $1 AND e.user_id = $2
               GROUP BY e.date
               ORDER BY e.date DESC""",
            metric_id, current_user["id"],
        )
        current_streak = 0
        for r in streak_rows:
            if r["day_value"] is True:
                current_streak += 1
            else:
                break
        longest_streak = 0
        running = 0
        for r in reversed(streak_rows):
            if r["day_value"] is True:
                running += 1
                longest_streak = max(longest_streak, running)
            else:
                running = 0
        result.update({
            "yes_percent": yes_percent,
            "yes_count": yes_count,
            "no_count": no_count,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        })

    elif mt == "time":
        if values:
            avg_minutes = mean(values)
            result.update({
                "average": f"{int(avg_minutes) // 60:02d}:{int(avg_minutes) % 60:02d}",
                "earliest": f"{int(min(values)) // 60:02d}:{int(min(values)) % 60:02d}",
                "latest": f"{int(max(values)) // 60:02d}:{int(max(values)) % 60:02d}",
            })
        else:
            result.update({"average": "--:--", "earliest": "--:--", "latest": "--:--"})

    elif mt == "number":
        if values:
            result.update({
                "average": round(mean(values), 1),
                "min": round(min(values), 1),
                "max": round(max(values), 1),
                "median": round(median(values), 1),
            })
        else:
            result.update({"average": 0, "min": 0, "max": 0, "median": 0})

    elif mt == "scale":
        if values:
            result.update({
                "average": round(mean(values), 1),
                "min": round(min(values), 1),
                "max": round(max(values), 1),
            })
        else:
            result.update({"average": 0, "min": 0, "max": 0})

    return result


class CorrelationReportRequest(BaseModel):
    start: str
    end: str


@router.post("/correlation-report")
async def create_correlation_report(
    body: CorrelationReportRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    start_date = date_type.fromisoformat(body.start)
    end_date = date_type.fromisoformat(body.end)
    report_id = await db.fetchval(
        """INSERT INTO correlation_reports (user_id, status, period_start, period_end)
           VALUES ($1, 'running', $2, $3) RETURNING id""",
        current_user["id"], start_date, end_date,
    )
    asyncio.create_task(_compute_report(report_id, current_user["id"], body.start, body.end))
    return {"report_id": report_id, "status": "running"}


async def _compute_report(report_id: int, user_id: int, start: str, end: str):
    try:
        async with _db_module.pool.acquire() as conn:
            start_date = date_type.fromisoformat(start)
            end_date = date_type.fromisoformat(end)

            # Load enabled metrics
            metrics_rows = await conn.fetch(
                """SELECT id, name, icon, type FROM metric_definitions
                   WHERE user_id = $1 AND enabled = TRUE ORDER BY sort_order""",
                user_id,
            )

            # Load enabled slots for all metrics
            metric_ids = [m["id"] for m in metrics_rows]
            slots_rows = await conn.fetch(
                """SELECT id, metric_id, label FROM measurement_slots
                   WHERE metric_id = ANY($1) AND enabled = TRUE
                   ORDER BY metric_id, sort_order""",
                metric_ids,
            ) if metric_ids else []

            slots_by_metric: dict[int, list] = defaultdict(list)
            for s in slots_rows:
                slots_by_metric[s["metric_id"]].append(s)

            # Build data sources: (metric_id, slot_id, name, type, icon, slot_label)
            sources = []
            for m in metrics_rows:
                mid = m["id"]
                name = m["name"]
                mt = m["type"]
                icon = m["icon"] or ""
                metric_slots = slots_by_metric.get(mid, [])
                if metric_slots:
                    sources.append((mid, None, name, mt, icon, ""))
                    for s in metric_slots:
                        sources.append((mid, s["id"], name, mt, icon, s["label"]))
                else:
                    sources.append((mid, None, name, mt, icon, ""))

            # Fetch data for each source
            source_data = {}
            for i, (mid, sid, name, mt, icon, sl) in enumerate(sources):
                source_data[i] = await _values_by_date_for_slot(
                    conn, mid, mt, start_date, end_date, user_id, slot_id=sid,
                )

            # Compute all pairs (i < j, different metrics only)
            pairs_to_insert = []
            for i in range(len(sources)):
                for j in range(i + 1, len(sources)):
                    if sources[i][0] == sources[j][0]:
                        continue  # same metric — skip
                    r, n = _compute_pearson(source_data[i], source_data[j])
                    if r is not None:
                        si, sj = sources[i], sources[j]
                        pairs_to_insert.append((
                            report_id,
                            si[0], sj[0],       # metric_a_id, metric_b_id
                            si[1], sj[1],       # slot_a_id, slot_b_id
                            si[2], sj[2],       # label_a, label_b (metric name)
                            si[3], sj[3],       # type_a, type_b
                            si[4], sj[4],       # icon_a, icon_b
                            si[5], sj[5],       # slot_label_a, slot_label_b
                            r, n,
                        ))

            # Batch insert
            if pairs_to_insert:
                await conn.executemany(
                    """INSERT INTO correlation_pairs
                       (report_id, metric_a_id, metric_b_id, slot_a_id, slot_b_id,
                        label_a, label_b, type_a, type_b, icon_a, icon_b,
                        slot_label_a, slot_label_b, correlation, data_points)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)""",
                    pairs_to_insert,
                )

            await conn.execute(
                "UPDATE correlation_reports SET status = 'done', finished_at = now() WHERE id = $1",
                report_id,
            )
    except Exception:
        logger.exception("Error computing correlation report %s", report_id)
        try:
            async with _db_module.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE correlation_reports SET status = 'error', finished_at = now() WHERE id = $1",
                    report_id,
                )
        except Exception:
            logger.exception("Failed to update report status to error")


@router.get("/correlation-reports")
async def list_correlation_reports(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        """SELECT id, status, period_start, period_end, created_at, finished_at
           FROM correlation_reports
           WHERE user_id = $1
           ORDER BY created_at DESC""",
        current_user["id"],
    )
    return {
        "reports": [
            {
                "id": r["id"],
                "status": r["status"],
                "period_start": str(r["period_start"]),
                "period_end": str(r["period_end"]),
                "created_at": r["created_at"].isoformat(),
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in rows
        ]
    }


@router.get("/correlation-report/{report_id}")
async def get_correlation_report(
    report_id: int,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    report = await db.fetchrow(
        "SELECT * FROM correlation_reports WHERE id = $1 AND user_id = $2",
        report_id, current_user["id"],
    )
    if not report:
        return {"error": "Report not found"}

    pairs = await db.fetch(
        """SELECT label_a, label_b, type_a, type_b,
                  icon_a, icon_b, slot_label_a, slot_label_b,
                  correlation, data_points
           FROM correlation_pairs
           WHERE report_id = $1
           ORDER BY abs(correlation) DESC""",
        report_id,
    )

    return {
        "id": report["id"],
        "status": report["status"],
        "period_start": str(report["period_start"]),
        "period_end": str(report["period_end"]),
        "created_at": report["created_at"].isoformat(),
        "pairs": [
            {
                "label_a": p["label_a"],
                "label_b": p["label_b"],
                "type_a": p["type_a"],
                "type_b": p["type_b"],
                "icon_a": p["icon_a"],
                "icon_b": p["icon_b"],
                "slot_label_a": p["slot_label_a"],
                "slot_label_b": p["slot_label_b"],
                "correlation": p["correlation"],
                "data_points": p["data_points"],
                "p_value": round(_p_value(p["correlation"], p["data_points"]), 4) if p["correlation"] is not None else None,
            }
            for p in pairs
        ],
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
