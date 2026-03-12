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
from app.timing import timed_fetch, QueryTimer


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
    elif metric_type == "number" or metric_type == "duration":
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
    elif mt == "duration":
        return "values_duration", ""
    elif mt == "scale":
        return "values_scale", ", v.scale_min, v.scale_max, v.scale_step"
    elif mt == "enum":
        return "values_enum", ""
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
            elif result_type == "duration":
                # raw is "Xч Yм" string — parse back to minutes
                if isinstance(raw, str) and "ч" in raw:
                    parts = raw.replace("м", "").split("ч")
                    result[d] = float(int(parts[0].strip()) * 60 + int(parts[1].strip()))
                else:
                    result[d] = float(raw)
            else:
                result[d] = float(raw)
    return result


async def _values_by_date_for_enum_option(
    conn, metric_id: int, option_id: int,
    start_date, end_date, user_id: int, slot_id: int | None = None,
) -> dict[str, float]:
    """For a single enum option, return 1.0 if selected, 0.0 if entry exists but not selected."""
    slot_filter = ""
    params = [metric_id, start_date, end_date, user_id]
    if slot_id is not None:
        slot_filter = " AND e.slot_id = $5"
        params.append(slot_id)

    rows = await conn.fetch(
        f"""SELECT e.date, ve.selected_option_ids
            FROM entries e
            JOIN values_enum ve ON ve.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3
              AND e.user_id = $4{slot_filter}
            ORDER BY e.date""",
        *params,
    )

    day_values: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        day_values[str(r["date"])].append(option_id in r["selected_option_ids"])

    result = {}
    for d, bools in day_values.items():
        result[d] = 1.0 if any(bools) else 0.0
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
    qt = QueryTimer(f"trends/{metric_id}")
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
    qt.mark("metric")

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
    elif mt == "text":
        # Text metrics: count notes per day
        rows = await db.fetch(
            """SELECT date, COUNT(*) AS cnt FROM notes
               WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
               GROUP BY date ORDER BY date""",
            metric_id, current_user["id"], start_d, end_d,
        )
        points = [{"date": str(r["date"]), "value": r["cnt"]} for r in rows]
        qt.mark("values")
        qt.log()
        return {
            "metric_id": metric_id,
            "metric_name": metric["name"],
            "metric_type": "text",
            "start": start,
            "end": end,
            "points": points,
        }

    elif mt == "enum":
        # Return per-option boolean series
        opts = await db.fetch(
            "SELECT id, label, sort_order FROM enum_options WHERE metric_id = $1 AND enabled = TRUE ORDER BY sort_order",
            metric_id,
        )
        option_series = {}
        for o in opts:
            series = await _values_by_date_for_enum_option(
                db, metric_id, o["id"], start_d, end_d, current_user["id"],
            )
            option_series[o["label"]] = [{"date": d, "value": v} for d, v in sorted(series.items())]
        qt.mark("values")
        qt.log()
        return {
            "metric_id": metric_id,
            "metric_name": metric["name"],
            "metric_type": "enum",
            "start": start,
            "end": end,
            "options": [{"id": o["id"], "label": o["label"]} for o in opts],
            "option_series": option_series,
        }
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
    qt.mark("values")

    points = [{"date": d, "value": v} for d, v in sorted(aggregated.items())]
    qt.log()

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
    qt = QueryTimer(f"metric-stats/{metric_id}")
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
    qt.mark("metric")

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
        elif rt == "duration":
            if values:
                def _fmt_dur(m):
                    m = int(round(m))
                    return f"{m // 60}ч {m % 60}м"
                result.update({
                    "average": _fmt_dur(mean(values)),
                    "min": _fmt_dur(min(values)),
                    "max": _fmt_dur(max(values)),
                })
        else:
            if values:
                result.update({
                    "average": round(mean(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                })
        result["display_stats"] = _build_display_stats(result, "computed")
        return result

    if mt == "text":
        rows = await db.fetch(
            """SELECT date, COUNT(*) AS cnt FROM notes
               WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
               GROUP BY date ORDER BY date""",
            metric_id, current_user["id"], start_date, end_date,
        )
        qt.mark("values")
        total_notes = sum(r["cnt"] for r in rows)
        days_with_notes = len(rows)
        fill_rate = round(days_with_notes / total_days * 100, 1) if total_days > 0 else 0
        counts = [r["cnt"] for r in rows]
        qt.log()
        text_result = {
            "metric_id": metric_id,
            "metric_type": "text",
            "total_entries": days_with_notes,
            "total_days": total_days,
            "fill_rate": fill_rate,
            "total_notes": total_notes,
            "average_per_day": round(total_notes / days_with_notes, 1) if days_with_notes > 0 else 0,
            "max_per_day": max(counts) if counts else 0,
        }
        text_result["display_stats"] = _build_display_stats(text_result, "text")
        return text_result

    if mt == "enum":
        rows = await db.fetch(
            """SELECT e.date, ve.selected_option_ids
               FROM entries e
               JOIN values_enum ve ON ve.entry_id = e.id
               WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
               ORDER BY e.date""",
            metric_id, start_date, end_date, current_user["id"],
        )
        opts = await db.fetch(
            "SELECT id, label FROM enum_options WHERE metric_id = $1 AND enabled = TRUE ORDER BY sort_order",
            metric_id,
        )
        qt.mark("values")
        dates_with_entries = set(str(r["date"]) for r in rows)
        total_entries = len(dates_with_entries)
        fill_rate = round(total_entries / total_days * 100, 1) if total_days > 0 else 0

        option_counts = {o["id"]: 0 for o in opts}
        for r in rows:
            for oid in r["selected_option_ids"]:
                if oid in option_counts:
                    option_counts[oid] += 1

        option_stats = [
            {
                "label": o["label"],
                "count": option_counts[o["id"]],
                "percent": round(option_counts[o["id"]] / total_entries * 100, 1) if total_entries > 0 else 0,
            }
            for o in opts
        ]
        most_common = max(option_stats, key=lambda x: x["count"])["label"] if option_stats else "—"

        qt.log()
        enum_result = {
            "metric_id": metric_id,
            "metric_type": "enum",
            "total_entries": total_entries,
            "total_days": total_days,
            "fill_rate": fill_rate,
            "option_stats": option_stats,
            "most_common": most_common,
        }
        enum_result["display_stats"] = _build_display_stats(enum_result, "enum")
        return enum_result

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
    qt.mark("values")
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

    elif mt == "duration":
        if values:
            def _fmt_dur(m):
                m = int(round(m))
                return f"{m // 60}ч {m % 60}м"
            result.update({
                "average": _fmt_dur(mean(values)),
                "min": _fmt_dur(min(values)),
                "max": _fmt_dur(max(values)),
                "median": _fmt_dur(median(values)),
            })
        else:
            result.update({"average": "0ч 0м", "min": "0ч 0м", "max": "0ч 0м", "median": "0ч 0м"})

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

    # Build display_stats — ready-to-render list of {label, value}
    result["display_stats"] = _build_display_stats(result, mt)

    qt.log()
    return result


def _build_display_stats(stats: dict, mt: str) -> list[dict]:
    """Build a list of {label, value} for UI display based on metric type."""
    rows: list[dict] = []
    rows.append({"label": "Заполнение", "value": f"{stats['fill_rate']}%"})
    rt = stats.get("result_type")
    if mt == "bool" or (mt == "computed" and rt == "bool"):
        if "yes_percent" in stats:
            rows.append({"label": "Да", "value": f"{stats['yes_percent']}%"})
    elif mt == "time" or (mt == "computed" and rt == "time"):
        if stats.get("average"):
            rows.append({"label": "Среднее", "value": str(stats["average"])})
    elif mt == "scale":
        if stats.get("average") is not None:
            rows.append({"label": "Среднее", "value": f"{stats['average']}%"})
    elif mt == "duration" or (mt == "computed" and rt == "duration"):
        if stats.get("average"):
            rows.append({"label": "Среднее", "value": str(stats["average"])})
    elif mt == "text":
        if stats.get("average_per_day") is not None:
            rows.append({"label": "Среднее/день", "value": str(stats["average_per_day"])})
    elif mt == "enum":
        if stats.get("most_common"):
            rows.append({"label": "Частый", "value": str(stats["most_common"])})
    else:
        # number, computed float/int
        if stats.get("average") is not None:
            rows.append({"label": "Среднее", "value": str(stats["average"])})
        if stats.get("min") is not None and stats.get("max") is not None:
            rows.append({"label": "Диапазон", "value": f"{stats['min']} – {stats['max']}"})
    return rows


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
            qt = QueryTimer(f"correlation-report/{report_id}")
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
            qt.mark("load_metrics")
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

            qt.mark("load_slots")
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
            qt.mark("load_computed_cfg")

            # Load enum options for enum metrics
            enum_metric_ids = [m["id"] for m in metrics_rows if m["type"] == "enum"]
            enum_opts_by_metric: dict[int, list] = defaultdict(list)
            if enum_metric_ids:
                eo_rows = await conn.fetch(
                    """SELECT id, metric_id, label FROM enum_options
                       WHERE metric_id = ANY($1) AND enabled = TRUE
                       ORDER BY metric_id, sort_order""",
                    enum_metric_ids,
                )
                for r in eo_rows:
                    enum_opts_by_metric[r["metric_id"]].append(r)

            # Build data sources: (metric_id, slot_id, type, label)
            metric_names = {m["id"]: m["name"] for m in metrics_rows}
            sources = []
            enum_source_info = {}  # source_index -> (option_id, slot_id)
            for m in metrics_rows:
                mid = m["id"]
                mt = m["type"]
                if mt == "text":
                    continue  # text metrics handled via auto note_count source
                if mt == "computed":
                    sources.append((mid, None, mt, m["name"]))
                    continue
                if mt == "enum":
                    # Each enum option is a separate bool source
                    opts = enum_opts_by_metric.get(mid, [])
                    metric_slots = slots_by_metric.get(mid, [])
                    for opt in opts:
                        # Aggregate source (across all slots)
                        idx = len(sources)
                        sources.append((mid, None, "enum_bool", f"{m['name']}: {opt['label']}"))
                        enum_source_info[idx] = (opt["id"], None)
                        if metric_slots:
                            for s in metric_slots:
                                idx = len(sources)
                                sources.append((mid, s["id"], "enum_bool", f"{m['name']}: {opt['label']} — {s['label']}"))
                                enum_source_info[idx] = (opt["id"], s["id"])
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
                if i in enum_source_info:
                    opt_id, slot_id = enum_source_info[i]
                    source_data[i] = await _values_by_date_for_enum_option(
                        conn, mid, opt_id, start_date, end_date, user_id, slot_id=slot_id,
                    )
                elif mt == "computed":
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

            qt.mark(f"fetch_{len(sources)}_sources")
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

                # "nonzero" for number and duration
                if m["type"] in ("number", "duration"):
                    idx = len(sources)
                    sources.append((None, None, "bool", f"{m['name']}: не ноль"))
                    auto_info[idx] = ("nonzero", mid)

            # "note_count" for text metrics (not in main sources)
            for m in metrics_rows:
                if m["type"] == "text":
                    idx = len(sources)
                    sources.append((None, None, "number", f"{m['name']}: кол-во заметок"))
                    auto_info[idx] = ("note_count", m["id"])

            # Calendar auto sources
            for cal_name, cal_type in [("День недели", "day_of_week"), ("Месяц", "month"), ("Неделя года", "week_number")]:
                idx = len(sources)
                sources.append((None, None, "number", cal_name))
                auto_info[idx] = (cal_type, None)

            # ActivityWatch screen time auto source
            aw_rows = await conn.fetch(
                """SELECT date, active_seconds FROM activitywatch_daily_summary
                   WHERE user_id = $1 AND date >= $2 AND date <= $3""",
                user_id, start_date, end_date,
            )
            if aw_rows:
                idx = len(sources)
                sources.append((None, None, "number", "Экранное время (активное)"))
                auto_info[idx] = ("aw_active", None)
                source_data[idx] = {
                    str(r["date"]): r["active_seconds"] / 3600.0
                    for r in aw_rows
                }

            # Compute auto source data
            all_dates = [str(start_date + timedelta(days=i)) for i in range((end_date - start_date).days + 1)]

            for idx, (auto_type, parent_mid) in auto_info.items():
                if auto_type == "nonzero":
                    parent_data = source_data[aggregate_indices[parent_mid]]
                    source_data[idx] = {d: (1.0 if v > 0 else 0.0) for d, v in parent_data.items()}
                elif auto_type == "note_count":
                    nc_rows = await conn.fetch(
                        """SELECT date, COUNT(*) AS cnt FROM notes
                           WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
                           GROUP BY date""",
                        parent_mid, user_id, start_date, end_date,
                    )
                    source_data[idx] = {str(r["date"]): float(r["cnt"]) for r in nc_rows}
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
                    if should_skip_pair(i, j, sources, auto_info, enum_source_info):
                        continue
                    si, sj = sources[i], sources[j]

                    # lag=0: same-day correlation
                    r, n = _compute_pearson(source_data[i], source_data[j])
                    if r is not None:
                        pairs_to_insert.append((
                            report_id,
                            si[0], sj[0], si[1], sj[1],
                            si[3], sj[3], si[2], sj[2],
                            r, n, 0, round(_p_value(r, n), 4),
                        ))

                    # lag=1: yesterday's j → today's i
                    r_lag, n_lag = _compute_pearson(source_data[i], _shift_dates(source_data[j], 1))
                    if r_lag is not None:
                        pairs_to_insert.append((
                            report_id,
                            si[0], sj[0], si[1], sj[1],
                            si[3], sj[3], si[2], sj[2],
                            r_lag, n_lag, 1, round(_p_value(r_lag, n_lag), 4),
                        ))

                    # lag=1: yesterday's i → today's j
                    r_lag2, n_lag2 = _compute_pearson(source_data[j], _shift_dates(source_data[i], 1))
                    if r_lag2 is not None:
                        pairs_to_insert.append((
                            report_id,
                            sj[0], si[0], sj[1], si[1],
                            sj[3], si[3], sj[2], si[2],
                            r_lag2, n_lag2, 1, round(_p_value(r_lag2, n_lag2), 4),
                        ))

            qt.mark(f"compute_{len(pairs_to_insert)}_pairs")
            # Batch insert
            if pairs_to_insert:
                await conn.executemany(
                    """INSERT INTO correlation_pairs
                       (report_id, metric_a_id, metric_b_id, slot_a_id, slot_b_id,
                        label_a, label_b, type_a, type_b, correlation, data_points, lag_days, p_value)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                    pairs_to_insert,
                )

            qt.mark("insert_pairs")
            await conn.execute(
                "UPDATE correlation_reports SET status = 'done', finished_at = now() WHERE id = $1",
                report_id,
            )
            # Keep only this report, delete all others for the user
            await conn.execute(
                "DELETE FROM correlation_reports WHERE user_id = $1 AND id != $2",
                user_id, report_id,
            )
            qt.log()
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
        counts_row = await db.fetchrow(
            """SELECT
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05
                                    AND ABS(correlation) > 0.7) AS sig_strong,
                   COUNT(*) FILTER (WHERE data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05
                                    AND ABS(correlation) > 0.3 AND ABS(correlation) <= 0.7) AS sig_medium,
                   COUNT(*) FILTER (WHERE data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05
                                    AND ABS(correlation) <= 0.3) AS sig_weak,
                   COUNT(*) FILTER (WHERE data_points < 10 OR p_value IS NULL OR p_value >= 0.05) AS insig
               FROM correlation_pairs WHERE report_id = $1""",
            done_row["id"],
        )
        report = {
            "id": done_row["id"],
            "status": "done",
            "period_start": str(done_row["period_start"]),
            "period_end": str(done_row["period_end"]),
            "created_at": done_row["created_at"].isoformat(),
            "counts": {
                "total": counts_row["total"],
                "sig_strong": counts_row["sig_strong"],
                "sig_medium": counts_row["sig_medium"],
                "sig_weak": counts_row["sig_weak"],
                "insig": counts_row["insig"],
            },
        }

    return {"running": running, "report": report}


# ─── Helpers for pair formatting (shared by pairs endpoint) ───

AUTO_CALENDAR_ICONS: dict[str, str] = {"День недели": "📅", "Месяц": "🗓️", "Неделя года": "📆"}


def _resolve_icon(icon: str | None, label: str | None, metric_icons: dict[str, str]) -> str:
    if icon:
        return icon
    if label and label in AUTO_CALENDAR_ICONS:
        return AUTO_CALENDAR_ICONS[label]
    if label and label.endswith(": не ноль"):
        parent_name = label[:-len(": не ноль")]
        return metric_icons.get(parent_name, "")
    return ""


def _pair_label(name: str | None, label: str | None, pair_type: str | None) -> str:
    if pair_type == "enum_bool":
        if name:
            return name
        if label:
            colon_idx = label.find(": ")
            return label[:colon_idx] if colon_idx != -1 else label
        return "Удалённая метрика"
    return name or label or "Удалённая метрика"


def _pair_option(label: str | None, pair_type: str | None, slot_id: int | None) -> str:
    if pair_type != "enum_bool" or not label:
        return ""
    raw = label
    if slot_id:
        dash_idx = raw.rfind(" — ")
        if dash_idx != -1:
            raw = raw[:dash_idx]
    colon_idx = raw.find(": ")
    return raw[colon_idx + 2:] if colon_idx != -1 else ""


def _corr_type_words(type_: str) -> tuple[str, str]:
    """Return (positive_word, negative_word) for a metric type in correlation context."""
    if type_ in ("bool", "enum_bool"):
        return ("да", "нет")
    if type_ == "time":
        return ("позже", "раньше")
    if type_ == "scale":
        return ("выше", "ниже")
    return ("больше", "меньше")


def _corr_hint_words(type_a: str, type_b: str, r: float) -> tuple[str, bool, str, bool]:
    """Return (hint_a, hint_a_positive, hint_b, hint_b_positive)."""
    if not type_a or not type_b:
        return ("", True, "", True)
    pos_a, _ = _corr_type_words(type_a)
    pos_b, neg_b = _corr_type_words(type_b)
    hint_a = pos_a
    hint_b = pos_b if r > 0 else neg_b
    return (hint_a, True, hint_b, r > 0)


def _format_pair(p: dict, metric_icons: dict[str, str]) -> dict:
    corr = p["correlation"]
    if corr is not None:
        hint_a, hint_a_pos, hint_b, hint_b_pos = _corr_hint_words(p["type_a"], p["type_b"], corr)
    else:
        hint_a, hint_a_pos, hint_b, hint_b_pos = "", True, "", True
    return {
        "label_a": _pair_label(p["name_a"], p["label_a"], p["type_a"]),
        "label_b": _pair_label(p["name_b"], p["label_b"], p["type_b"]),
        "option_a": _pair_option(p["label_a"], p["type_a"], p["slot_a_id"]),
        "option_b": _pair_option(p["label_b"], p["type_b"], p["slot_b_id"]),
        "type_a": p["type_a"],
        "type_b": p["type_b"],
        "icon_a": _resolve_icon(p["icon_a"], p["label_a"], metric_icons),
        "icon_b": _resolve_icon(p["icon_b"], p["label_b"], metric_icons),
        "slot_label_a": p["slot_label_a"] or "",
        "slot_label_b": p["slot_label_b"] or "",
        "correlation": corr,
        "data_points": p["data_points"],
        "lag_days": p["lag_days"],
        "p_value": p["p_value"] if p["p_value"] is not None else (round(_p_value(corr, p["data_points"]), 4) if corr is not None else None),
        "metric_a_id": p["metric_a_id"],
        "metric_b_id": p["metric_b_id"],
        "pair_id": p["pair_id"],
        "hint_a": hint_a,
        "hint_b": hint_b,
        "hint_a_positive": hint_a_pos,
        "hint_b_positive": hint_b_pos,
        "private_a": p.get("private_a", False),
        "private_b": p.get("private_b", False),
    }


_CATEGORY_FILTERS: dict[str, str] = {
    "sig_strong": "AND data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05 AND ABS(correlation) > 0.7",
    "sig_medium": "AND data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05 AND ABS(correlation) > 0.3 AND ABS(correlation) <= 0.7",
    "sig_weak": "AND data_points >= 10 AND p_value IS NOT NULL AND p_value < 0.05 AND ABS(correlation) <= 0.3",
    "insig": "AND (data_points < 10 OR p_value IS NULL OR p_value >= 0.05)",
    "all": "",
}


@router.get("/correlation-report/{report_id}/pairs")
async def get_correlation_pairs(
    report_id: int,
    category: str = "all",
    offset: int = 0,
    limit: int = 50,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Verify report belongs to user
    report_row = await db.fetchrow(
        "SELECT id FROM correlation_reports WHERE id = $1 AND user_id = $2",
        report_id, current_user["id"],
    )
    if not report_row:
        return {"pairs": [], "total": 0, "has_more": False}

    cat_filter = _CATEGORY_FILTERS.get(category, "")

    # Count total for this category
    total_row = await db.fetchrow(
        f"SELECT COUNT(*) AS cnt FROM correlation_pairs WHERE report_id = $1 {cat_filter}",
        report_id,
    )
    total = total_row["cnt"]

    # Fetch page of pairs
    pairs = await db.fetch(
        f"""SELECT cp.id AS pair_id,
                   cp.type_a, cp.type_b, cp.correlation, cp.data_points, cp.lag_days, cp.p_value,
                   cp.metric_a_id, cp.metric_b_id, cp.slot_a_id, cp.slot_b_id,
                   cp.label_a, cp.label_b,
                   ma.name AS name_a, ma.icon AS icon_a, COALESCE(ma.private, FALSE) AS private_a,
                   mb.name AS name_b, mb.icon AS icon_b, COALESCE(mb.private, FALSE) AS private_b,
                   sa.label AS slot_label_a,
                   sb.label AS slot_label_b
            FROM correlation_pairs cp
            LEFT JOIN metric_definitions ma ON ma.id = cp.metric_a_id
            LEFT JOIN metric_definitions mb ON mb.id = cp.metric_b_id
            LEFT JOIN measurement_slots sa ON sa.id = cp.slot_a_id
            LEFT JOIN measurement_slots sb ON sb.id = cp.slot_b_id
            WHERE cp.report_id = $1 {cat_filter}
            ORDER BY ABS(cp.correlation) DESC
            LIMIT $2 OFFSET $3""",
        report_id, limit, offset,
    )

    # Resolve icons for auto metrics
    metric_icons: dict[str, str] = {}
    if any(p["metric_a_id"] is None or p["metric_b_id"] is None for p in pairs):
        user_metrics = await db.fetch(
            "SELECT name, icon FROM metric_definitions WHERE user_id = $1",
            current_user["id"],
        )
        metric_icons = {m["name"]: m["icon"] for m in user_metrics if m["icon"]}

    return {
        "pairs": [_format_pair(p, metric_icons) for p in pairs],
        "total": total,
        "has_more": offset + limit < total,
    }


async def _reconstruct_source_data(
    conn,
    metric_id: int | None,
    slot_id: int | None,
    source_type: str,
    label: str,
    start_date: date_type,
    end_date: date_type,
    user_id: int,
) -> dict[str, float]:
    """Reconstruct time-series data for a correlation source from its stored metadata."""
    if source_type == "enum_bool" and metric_id is not None:
        # Parse option label from stored label: "{name}: {opt}" or "{name}: {opt} — {slot}"
        parts = label.split(": ", 1)
        option_label = parts[1].split(" — ")[0] if len(parts) > 1 else ""
        opt_row = await conn.fetchrow(
            "SELECT id FROM enum_options WHERE metric_id = $1 AND label = $2",
            metric_id, option_label,
        )
        if not opt_row:
            return {}
        return await _values_by_date_for_enum_option(
            conn, metric_id, opt_row["id"], start_date, end_date, user_id, slot_id=slot_id,
        )

    if source_type == "computed" and metric_id is not None:
        cfg = await conn.fetchrow(
            "SELECT formula, result_type FROM computed_config WHERE metric_id = $1",
            metric_id,
        )
        if not cfg or not cfg["formula"]:
            return {}
        formula = _parse_formula(cfg["formula"])
        rt = cfg["result_type"] or "float"
        ref_ids = get_referenced_metric_ids(formula)
        return await _values_by_date_for_computed(
            conn, formula, rt, ref_ids, start_date, end_date, user_id,
        )

    if metric_id is None:
        # Auto source — determine from label
        all_dates = [
            str(start_date + timedelta(days=i))
            for i in range((end_date - start_date).days + 1)
        ]
        if label == "День недели":
            return {d: float(date_type.fromisoformat(d).isoweekday()) for d in all_dates}
        if label == "Месяц":
            return {d: float(date_type.fromisoformat(d).month) for d in all_dates}
        if label == "Неделя года":
            return {d: float(date_type.fromisoformat(d).isocalendar()[1]) for d in all_dates}
        if label == "Экранное время (активное)":
            rows = await conn.fetch(
                """SELECT date, active_seconds FROM activitywatch_daily_summary
                   WHERE user_id = $1 AND date >= $2 AND date <= $3""",
                user_id, start_date, end_date,
            )
            return {str(r["date"]): r["active_seconds"] / 3600.0 for r in rows}
        if label.endswith(": не ноль"):
            parent_name = label[: -len(": не ноль")]
            parent = await conn.fetchrow(
                "SELECT id, type FROM metric_definitions WHERE user_id = $1 AND name = $2",
                user_id, parent_name,
            )
            if not parent:
                return {}
            raw = await _values_by_date_for_slot(
                conn, parent["id"], parent["type"], start_date, end_date, user_id,
            )
            return {d: (1.0 if v > 0 else 0.0) for d, v in raw.items()}
        if label.endswith(": кол-во заметок"):
            parent_name = label[: -len(": кол-во заметок")]
            parent = await conn.fetchrow(
                "SELECT id FROM metric_definitions WHERE user_id = $1 AND name = $2",
                user_id, parent_name,
            )
            if not parent:
                return {}
            nc_rows = await conn.fetch(
                """SELECT date, COUNT(*) AS cnt FROM notes
                   WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4
                   GROUP BY date""",
                parent["id"], user_id, start_date, end_date,
            )
            return {str(r["date"]): float(r["cnt"]) for r in nc_rows}
        return {}

    # Regular metric
    return await _values_by_date_for_slot(
        conn, metric_id, source_type, start_date, end_date, user_id, slot_id=slot_id,
    )


@router.get("/correlation-pair-chart")
async def correlation_pair_chart(
    pair_id: int = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.fetchrow(
        """SELECT cp.*, cr.period_start, cr.period_end, cr.user_id
           FROM correlation_pairs cp
           JOIN correlation_reports cr ON cr.id = cp.report_id
           WHERE cp.id = $1""",
        pair_id,
    )
    if not row or row["user_id"] != current_user["id"]:
        return {"dates": [], "values_a": [], "values_b": []}

    start_date = row["period_start"]
    end_date = row["period_end"]
    uid = current_user["id"]

    data_a = await _reconstruct_source_data(
        db, row["metric_a_id"], row["slot_a_id"],
        row["type_a"], row["label_a"], start_date, end_date, uid,
    )
    data_b = await _reconstruct_source_data(
        db, row["metric_b_id"], row["slot_b_id"],
        row["type_b"], row["label_b"], start_date, end_date, uid,
    )

    lag = row["lag_days"] or 0
    if lag > 0:
        data_b = _shift_dates(data_b, lag)

    common = sorted(set(data_a) & set(data_b))

    # Resolve effective display type for computed metrics
    type_a = row["type_a"]
    type_b = row["type_b"]
    if type_a == "computed" and row["metric_a_id"]:
        cfg = await db.fetchrow(
            "SELECT result_type FROM computed_config WHERE metric_id = $1",
            row["metric_a_id"],
        )
        if cfg and cfg["result_type"]:
            type_a = cfg["result_type"]
    if type_b == "computed" and row["metric_b_id"]:
        cfg = await db.fetchrow(
            "SELECT result_type FROM computed_config WHERE metric_id = $1",
            row["metric_b_id"],
        )
        if cfg and cfg["result_type"]:
            type_b = cfg["result_type"]

    original_dates_b = None
    if lag > 0:
        original_dates_b = [
            str(date_type.fromisoformat(d) - timedelta(days=lag)) for d in common
        ]

    return {
        "dates": common,
        "values_a": [data_a[d] for d in common],
        "values_b": [data_b[d] for d in common],
        "type_a": type_a,
        "type_b": type_b,
        "label_a": row["label_a"],
        "label_b": row["label_b"],
        "correlation": row["correlation"],
        "lag_days": lag,
        "original_dates_b": original_dates_b,
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
