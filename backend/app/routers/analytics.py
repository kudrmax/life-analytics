import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import date as date_type, timedelta
from statistics import mean, median, stdev

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import database as _db_module
from app.database import get_db
from app.auth import get_current_user
from app.formula import convert_metric_value, evaluate_formula, get_referenced_metric_ids
from app.correlation_blacklist import should_skip_pair


def _parse_formula(raw):
    """Parse formula from DB — may be JSON string or list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return raw

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


async def _raw_values_by_date(
    conn, metric_id: int, metric_type: str,
    start_date, end_date, user_id: int,
) -> dict[str, float]:
    """Get values by date using convert_metric_value (scale→0..1, not 0..100).

    Used for computed metric evaluation to ensure consistent normalization.
    Multi-slot entries are averaged per day.
    """
    value_table, extra_cols = _get_value_table(metric_type)

    # For scale, we need scale_config for normalization
    scale_min, scale_max = None, None
    if metric_type == "scale":
        cfg = await conn.fetchrow(
            "SELECT scale_min, scale_max FROM scale_config WHERE metric_id = $1",
            metric_id,
        )
        if cfg:
            scale_min, scale_max = cfg["scale_min"], cfg["scale_max"]

    rows = await conn.fetch(
        f"""SELECT e.date, v.value{extra_cols}
            FROM entries e
            JOIN {value_table} v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3
              AND e.user_id = $4
            ORDER BY e.date""",
        metric_id, start_date, end_date, user_id,
    )

    day_values: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        raw = r["value"]
        if metric_type == "time":
            # raw is TIMESTAMPTZ
            cv = raw.hour * 60 + raw.minute if raw else None
        elif metric_type == "bool":
            cv = 1.0 if raw else 0.0
        elif metric_type == "scale":
            # Use per-entry context if available, else scale_config
            s_min = r.get("scale_min", scale_min) if r.get("scale_min") is not None else scale_min
            s_max = r.get("scale_max", scale_max) if r.get("scale_max") is not None else scale_max
            s_min_f = float(s_min) if s_min is not None else 1.0
            s_max_f = float(s_max) if s_max is not None else 5.0
            cv = (float(raw) - s_min_f) / (s_max_f - s_min_f) if s_max_f != s_min_f else 0.0
        else:
            cv = float(raw) if raw is not None else None
        if cv is not None:
            day_values[str(r["date"])].append(cv)

    result = {}
    for d, vals in day_values.items():
        if metric_type == "bool":
            result[d] = 1.0 if any(v == 1.0 for v in vals) else 0.0
        else:
            result[d] = mean(vals) if vals else 0.0
    return result


async def _values_by_date_for_computed(
    conn, formula: list, result_type: str,
    ref_ids: list[int], start_date, end_date, user_id: int,
) -> dict[str, float]:
    """Evaluate a computed metric for each date in range."""
    if not ref_ids:
        return {}

    source_rows = await conn.fetch(
        "SELECT id, type FROM metric_definitions WHERE id = ANY($1) AND user_id = $2",
        ref_ids, user_id,
    )
    source_types = {r["id"]: r["type"] for r in source_rows}

    # Fetch data for each referenced metric (using 0..1 scale normalization)
    source_data: dict[int, dict[str, float]] = {}
    for mid in ref_ids:
        mt = source_types.get(mid)
        if not mt:
            continue
        source_data[mid] = await _raw_values_by_date(
            conn, mid, mt, start_date, end_date, user_id,
        )

    # Union of all dates
    all_dates = set()
    for d in source_data.values():
        all_dates.update(d.keys())

    result = {}
    for d in sorted(all_dates):
        values_for_day = {mid: source_data.get(mid, {}).get(d) for mid in ref_ids}
        raw = evaluate_formula(formula, values_for_day, result_type)
        if raw is not None:
            if result_type == "bool":
                result[d] = 1.0 if raw else 0.0
            elif result_type == "time":
                if isinstance(raw, str) and ":" in raw:
                    h, m = map(int, raw.split(":"))
                    result[d] = float(h * 60 + m)
                else:
                    result[d] = float(raw)
            else:
                result[d] = float(raw)
    return result


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


def _shift_dates(data: dict[str, float], days: int) -> dict[str, float]:
    """Shift date keys forward by N days."""
    return {str(date_type.fromisoformat(d) + timedelta(days=days)): v for d, v in data.items()}


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
        """SELECT md.*, cc.formula, cc.result_type, ic.value_type AS ic_value_type
           FROM metric_definitions md
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_id, current_user["id"],
    )
    if not metric:
        return {"error": "Metric not found"}

    mt = metric["type"]
    if mt == "integration":
        mt = metric["ic_value_type"] or "number"
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)

    if metric["type"] == "computed":
        formula = _parse_formula(metric.get("formula"))
        result_type = metric.get("result_type") or "float"
        ref_ids = get_referenced_metric_ids(formula)
        aggregated = await _values_by_date_for_computed(
            db, formula, result_type, ref_ids, start_d, end_d, current_user["id"],
        )
    else:
        value_table, extra_cols = _get_value_table(mt)
        rows = await db.fetch(
            f"""SELECT e.date, v.value{extra_cols}
                FROM entries e
                JOIN {value_table} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
                ORDER BY e.date""",
            metric_id, start_d, end_d, current_user["id"],
        )
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
        """SELECT md.*, cc.formula, cc.result_type
           FROM metric_definitions md LEFT JOIN computed_config cc ON cc.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_a, current_user["id"],
    )
    mb = await db.fetchrow(
        """SELECT md.*, cc.formula, cc.result_type
           FROM metric_definitions md LEFT JOIN computed_config cc ON cc.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_b, current_user["id"],
    )
    if not ma or not mb:
        return {"error": "Metric not found"}

    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)

    if ma["type"] == "computed":
        formula_a = _parse_formula(ma.get("formula"))
        ref_ids_a = get_referenced_metric_ids(formula_a)
        a_by_date = await _values_by_date_for_computed(db, formula_a, ma.get("result_type") or "float", ref_ids_a, start_date, end_date, current_user["id"])
    else:
        a_by_date = await _values_by_date_for_slot(db, metric_a, ma["type"], start_date, end_date, current_user["id"])

    if mb["type"] == "computed":
        formula_b = _parse_formula(mb.get("formula"))
        ref_ids_b = get_referenced_metric_ids(formula_b)
        b_by_date = await _values_by_date_for_computed(db, formula_b, mb.get("result_type") or "float", ref_ids_b, start_date, end_date, current_user["id"])
    else:
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
        """SELECT md.*, cc.formula, cc.result_type, ic.value_type AS ic_value_type
           FROM metric_definitions md
           LEFT JOIN computed_config cc ON cc.metric_id = md.id
           LEFT JOIN integration_config ic ON ic.metric_id = md.id
           WHERE md.id = $1 AND md.user_id = $2""",
        metric_id, current_user["id"],
    )
    if not metric:
        return {"error": "Metric not found"}

    mt = metric["type"]
    if mt == "integration":
        mt = metric["ic_value_type"] or "number"
    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    total_days = (end_date - start_date).days + 1

    if metric["type"] == "computed":
        formula = _parse_formula(metric.get("formula"))
        rt = metric.get("result_type") or "float"
        ref_ids = get_referenced_metric_ids(formula)
        aggregated = await _values_by_date_for_computed(
            db, formula, rt, ref_ids, start_date, end_date, current_user["id"],
        )
        total_entries = len(aggregated)
        fill_rate = round(total_entries / total_days * 100, 1) if total_days > 0 else 0
        result = {
            "metric_id": metric_id, "metric_type": "computed", "result_type": rt,
            "total_entries": total_entries, "total_days": total_days, "fill_rate": fill_rate,
        }
        values = sorted(aggregated.values())
        if rt == "bool":
            yes_count = sum(1 for v in values if v == 1.0)
            result.update({
                "yes_percent": round(yes_count / total_entries * 100, 1) if total_entries else 0,
                "yes_count": yes_count, "no_count": total_entries - yes_count,
            })
        elif rt == "time":
            if values:
                avg = mean(values)
                result.update({
                    "average": f"{int(avg) // 60:02d}:{int(avg) % 60:02d}",
                    "earliest": f"{int(min(values)) // 60:02d}:{int(min(values)) % 60:02d}",
                    "latest": f"{int(max(values)) // 60:02d}:{int(max(values)) % 60:02d}",
                })
        else:
            if values:
                result.update({
                    "average": round(mean(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                })
        return result

    value_table, extra_cols = _get_value_table(mt)
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

            # Load enabled metrics (resolve integration type via integration_config)
            metrics_rows = await conn.fetch(
                """SELECT md.id, md.name, md.type, ic.value_type AS ic_value_type
                   FROM metric_definitions md
                   LEFT JOIN integration_config ic ON ic.metric_id = md.id
                   WHERE md.user_id = $1 AND md.enabled = TRUE ORDER BY md.sort_order""",
                user_id,
            )
            # Resolve integration types
            for i, m in enumerate(metrics_rows):
                if m["type"] == "integration":
                    metrics_rows[i] = dict(m)
                    metrics_rows[i]["type"] = m["ic_value_type"] or "number"

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

            # Load computed_config for computed metrics
            computed_cfgs = {}
            computed_ids = [m["id"] for m in metrics_rows if m["type"] == "computed"]
            if computed_ids:
                cc_rows = await conn.fetch(
                    "SELECT metric_id, formula, result_type FROM computed_config WHERE metric_id = ANY($1)",
                    computed_ids,
                )
                computed_cfgs = {r["metric_id"]: r for r in cc_rows}

            # Build data sources: (metric_id, slot_id, type, label)
            metric_names = {m["id"]: m["name"] for m in metrics_rows}
            sources = []
            for m in metrics_rows:
                mid = m["id"]
                mt = m["type"]
                if mt == "computed":
                    sources.append((mid, None, mt, m["name"]))
                    continue
                metric_slots = slots_by_metric.get(mid, [])
                if metric_slots:
                    sources.append((mid, None, mt, m["name"]))
                    for s in metric_slots:
                        sources.append((mid, s["id"], mt, f"{m['name']} — {s['label']}"))
                else:
                    sources.append((mid, None, mt, m["name"]))

            # Fetch data for each source
            source_data = {}
            for i, (mid, sid, mt, _label) in enumerate(sources):
                if mt == "computed":
                    cfg = computed_cfgs.get(mid)
                    if cfg and cfg["formula"]:
                        formula = _parse_formula(cfg["formula"])
                        rt = cfg["result_type"] or "float"
                        ref_ids = get_referenced_metric_ids(formula)
                        source_data[i] = await _values_by_date_for_computed(
                            conn, formula, rt, ref_ids, start_date, end_date, user_id,
                        )
                    else:
                        source_data[i] = {}
                else:
                    source_data[i] = await _values_by_date_for_slot(
                        conn, mid, mt, start_date, end_date, user_id, slot_id=sid,
                    )

            # --- Auto sources ---
            auto_info = {}  # source_index -> (auto_type, parent_metric_id)

            # Find aggregate source indices (slot_id=None, not computed)
            aggregate_indices = {}  # metric_id -> source_index
            for i, (mid, sid, mt, _label) in enumerate(sources):
                if sid is None and mt != "computed":
                    aggregate_indices[mid] = i

            # Per-metric auto sources
            for m in metrics_rows:
                if m["type"] == "computed":
                    continue
                mid = m["id"]
                if mid not in aggregate_indices:
                    continue

                # "nonzero" for number
                if m["type"] == "number":
                    idx = len(sources)
                    sources.append((None, None, "bool", f"{m['name']}: не ноль"))
                    auto_info[idx] = ("nonzero", mid)

            # Calendar auto sources
            for cal_name, cal_type in [("День недели", "day_of_week"), ("Месяц", "month"), ("Неделя года", "week_number")]:
                idx = len(sources)
                sources.append((None, None, "number", cal_name))
                auto_info[idx] = (cal_type, None)

            # Compute auto source data
            all_dates = [str(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]

            for idx, (auto_type, parent_mid) in auto_info.items():
                if auto_type == "nonzero":
                    parent_data = source_data[aggregate_indices[parent_mid]]
                    source_data[idx] = {d: (1.0 if v > 0 else 0.0) for d, v in parent_data.items()}
                elif auto_type == "day_of_week":
                    source_data[idx] = {d: float(date_type.fromisoformat(d).isoweekday()) for d in all_dates}
                elif auto_type == "month":
                    source_data[idx] = {d: float(date_type.fromisoformat(d).month) for d in all_dates}
                elif auto_type == "week_number":
                    source_data[idx] = {d: float(date_type.fromisoformat(d).isocalendar()[1]) for d in all_dates}

            # Compute all pairs (i < j, different metrics only)
            pairs_to_insert = []
            for i in range(len(sources)):
                for j in range(i + 1, len(sources)):
                    if should_skip_pair(i, j, sources, auto_info):
                        continue
                    si, sj = sources[i], sources[j]

                    # lag=0: same-day correlation
                    r, n = _compute_pearson(source_data[i], source_data[j])
                    if r is not None:
                        pairs_to_insert.append((
                            report_id,
                            si[0], sj[0], si[1], sj[1],
                            si[3], sj[3], si[2], sj[2],
                            r, n, 0,
                        ))

                    # lag=1: yesterday's j → today's i
                    r_lag, n_lag = _compute_pearson(source_data[i], _shift_dates(source_data[j], 1))
                    if r_lag is not None:
                        pairs_to_insert.append((
                            report_id,
                            si[0], sj[0], si[1], sj[1],
                            si[3], sj[3], si[2], sj[2],
                            r_lag, n_lag, 1,
                        ))

                    # lag=1: yesterday's i → today's j
                    r_lag2, n_lag2 = _compute_pearson(source_data[j], _shift_dates(source_data[i], 1))
                    if r_lag2 is not None:
                        pairs_to_insert.append((
                            report_id,
                            sj[0], si[0], sj[1], si[1],
                            sj[3], si[3], sj[2], si[2],
                            r_lag2, n_lag2, 1,
                        ))

            # Batch insert
            if pairs_to_insert:
                await conn.executemany(
                    """INSERT INTO correlation_pairs
                       (report_id, metric_a_id, metric_b_id, slot_a_id, slot_b_id,
                        label_a, label_b, type_a, type_b, correlation, data_points, lag_days)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                    pairs_to_insert,
                )

            await conn.execute(
                "UPDATE correlation_reports SET status = 'done', finished_at = now() WHERE id = $1",
                report_id,
            )
            # Keep only this report, delete all others for the user
            await conn.execute(
                "DELETE FROM correlation_reports WHERE user_id = $1 AND id != $2",
                user_id, report_id,
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


@router.get("/correlation-report")
async def get_latest_correlation_report(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.fetch(
        """SELECT id, status, period_start, period_end, created_at
           FROM correlation_reports
           WHERE user_id = $1
           ORDER BY created_at DESC""",
        current_user["id"],
    )
    if not rows:
        return {"running": None, "report": None}

    running = None
    done_row = None
    for r in rows:
        if r["status"] == "running" and running is None:
            running = {
                "id": r["id"],
                "status": "running",
                "created_at": r["created_at"].isoformat(),
            }
        elif r["status"] == "done" and done_row is None:
            done_row = r

    report = None
    if done_row:
        pairs = await db.fetch(
            """SELECT cp.type_a, cp.type_b, cp.correlation, cp.data_points, cp.lag_days,
                      cp.metric_a_id, cp.metric_b_id, cp.slot_a_id, cp.slot_b_id,
                      cp.label_a, cp.label_b,
                      ma.name AS name_a, ma.icon AS icon_a,
                      mb.name AS name_b, mb.icon AS icon_b,
                      sa.label AS slot_label_a,
                      sb.label AS slot_label_b
               FROM correlation_pairs cp
               LEFT JOIN metric_definitions ma ON ma.id = cp.metric_a_id
               LEFT JOIN metric_definitions mb ON mb.id = cp.metric_b_id
               LEFT JOIN measurement_slots sa ON sa.id = cp.slot_a_id
               LEFT JOIN measurement_slots sb ON sb.id = cp.slot_b_id
               WHERE cp.report_id = $1
               ORDER BY abs(cp.correlation) DESC""",
            done_row["id"],
        )

        # Resolve icons for auto metrics (metric_id is NULL)
        AUTO_CALENDAR_ICONS = {"День недели": "📅", "Месяц": "🗓️", "Неделя года": "📆"}
        metric_icons = {}
        if any(p["metric_a_id"] is None or p["metric_b_id"] is None for p in pairs):
            user_metrics = await db.fetch(
                "SELECT name, icon FROM metric_definitions WHERE user_id = $1",
                current_user["id"],
            )
            metric_icons = {m["name"]: m["icon"] for m in user_metrics if m["icon"]}

        def _resolve_icon(icon, label):
            if icon:
                return icon
            if label in AUTO_CALENDAR_ICONS:
                return AUTO_CALENDAR_ICONS[label]
            if label and label.endswith(": не ноль"):
                parent_name = label[:-len(": не ноль")]
                return metric_icons.get(parent_name, "")
            return ""

        report = {
            "id": done_row["id"],
            "status": "done",
            "period_start": str(done_row["period_start"]),
            "period_end": str(done_row["period_end"]),
            "created_at": done_row["created_at"].isoformat(),
            "pairs": [
                {
                    "label_a": p["name_a"] or p["label_a"] or "Удалённая метрика",
                    "label_b": p["name_b"] or p["label_b"] or "Удалённая метрика",
                    "type_a": p["type_a"],
                    "type_b": p["type_b"],
                    "icon_a": _resolve_icon(p["icon_a"], p["label_a"]),
                    "icon_b": _resolve_icon(p["icon_b"], p["label_b"]),
                    "slot_label_a": p["slot_label_a"] or "",
                    "slot_label_b": p["slot_label_b"] or "",
                    "correlation": p["correlation"],
                    "data_points": p["data_points"],
                    "lag_days": p["lag_days"],
                    "p_value": round(_p_value(p["correlation"], p["data_points"]), 4) if p["correlation"] is not None else None,
                    "metric_a_id": p["metric_a_id"],
                    "metric_b_id": p["metric_b_id"],
                }
                for p in pairs
            ],
        }

    return {"running": running, "report": report}


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
