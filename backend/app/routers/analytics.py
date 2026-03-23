import asyncio
import logging
from datetime import date as date_type, timedelta
from statistics import mean, median

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.database import get_db
from app.auth import get_current_user, get_privacy_mode
from app.metric_helpers import mask_name, mask_icon, is_blocked, PRIVATE_MASK, PRIVATE_ICON
from app.formula import get_referenced_metric_ids
from app.correlation_config import correlation_config
from app.source_key import SourceKey, STREAK_TYPES
from app.timing import QueryTimer
from app.analytics.value_converter import ValueConverter
from app.analytics.time_series import TimeSeriesTransform
from app.analytics.correlation_math import CorrelationCalculator
from app.analytics.pair_formatter import PairFormatter
from app.analytics.value_fetcher import ValueFetcher
from app.analytics.source_reconstructor import SourceReconstructor
from app.analytics.correlation_engine import run_correlation_report


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/trends")
async def trends(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
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

    if is_blocked(metric.get("private", False), privacy_mode):
        return {
            "metric_id": metric_id,
            "metric_name": PRIVATE_MASK,
            "start": start,
            "end": end,
            "points": [],
            "blocked": True,
        }

    mt = metric["type"]
    if mt == "integration":
        mt = metric["ic_value_type"] or "number"
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)

    if metric["type"] == "computed":
        formula = ValueConverter.parse_formula(metric.get("formula"))
        result_type = metric.get("result_type") or "float"
        ref_ids = get_referenced_metric_ids(formula)
        aggregated = await ValueFetcher(db).values_by_date_for_computed( formula, result_type, ref_ids, start_d, end_d, current_user["id"],
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
            series = await ValueFetcher(db).values_by_date_for_enum_option( metric_id, o["id"], start_d, end_d, current_user["id"],
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
        value_table, extra_cols = ValueConverter.get_value_table(mt)
        rows = await db.fetch(
            f"""SELECT e.date, v.value{extra_cols}
                FROM entries e
                JOIN {value_table} v ON v.entry_id = e.id
                WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
                ORDER BY e.date""",
            metric_id, start_d, end_d, current_user["id"],
        )
        aggregated = ValueConverter.aggregate_by_date(rows, mt)
    qt.mark("values")

    points = [{"date": d, "value": v} for d, v in sorted(aggregated.items())]

    # Bool metric with slots: annotate aggregate name
    display_name = metric["name"]
    if mt == "bool":
        has_slots_row = await db.fetchrow(
            "SELECT 1 FROM metric_slots WHERE metric_id = $1 AND enabled = TRUE LIMIT 1",
            metric_id,
        )
        if has_slots_row:
            display_name = f"{display_name} (хоть раз)"
    qt.mark("display_name")
    qt.log()

    return {
        "metric_id": metric_id,
        "metric_name": display_name,
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
        formula_a = ValueConverter.parse_formula(ma.get("formula"))
        ref_ids_a = get_referenced_metric_ids(formula_a)
        a_by_date = await ValueFetcher(db).values_by_date_for_computed( formula_a, ma.get("result_type") or "float", ref_ids_a, start_date, end_date, current_user["id"])
    else:
        a_by_date = await ValueFetcher(db).values_by_date_for_slot( metric_a, ma["type"], start_date, end_date, current_user["id"])

    if mb["type"] == "computed":
        formula_b = ValueConverter.parse_formula(mb.get("formula"))
        ref_ids_b = get_referenced_metric_ids(formula_b)
        b_by_date = await ValueFetcher(db).values_by_date_for_computed( formula_b, mb.get("result_type") or "float", ref_ids_b, start_date, end_date, current_user["id"])
    else:
        b_by_date = await ValueFetcher(db).values_by_date_for_slot( metric_b, mb["type"], start_date, end_date, current_user["id"])

    r, n = CorrelationCalculator(a_by_date, b_by_date).pearson()

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
    privacy_mode: bool = Depends(get_privacy_mode),
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
    if is_blocked(metric.get("private", False), privacy_mode):
        return {"blocked": True}
    qt.mark("metric")

    mt = metric["type"]
    if mt == "integration":
        mt = metric["ic_value_type"] or "number"
    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    total_days = (end_date - start_date).days + 1

    if metric["type"] == "computed":
        formula = ValueConverter.parse_formula(metric.get("formula"))
        rt = metric.get("result_type") or "float"
        ref_ids = get_referenced_metric_ids(formula)
        aggregated = await ValueFetcher(db).values_by_date_for_computed( formula, rt, ref_ids, start_date, end_date, current_user["id"],
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
        result["display_stats"] = PairFormatter.build_display_stats(result, "computed")
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
        text_result["display_stats"] = PairFormatter.build_display_stats(text_result, "text")
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
        enum_result["display_stats"] = PairFormatter.build_display_stats(enum_result, "enum")
        return enum_result

    value_table, extra_cols = ValueConverter.get_value_table(mt)
    rows = await db.fetch(
        f"""SELECT e.date, v.value{extra_cols}
            FROM entries e
            JOIN {value_table} v ON v.entry_id = e.id
            WHERE e.metric_id = $1 AND e.date >= $2 AND e.date <= $3 AND e.user_id = $4
            ORDER BY e.date""",
        metric_id, start_date, end_date, current_user["id"],
    )

    aggregated = ValueConverter.aggregate_by_date(rows, mt)
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
    result["display_stats"] = PairFormatter.build_display_stats(result, mt)

    qt.log()
    return result






# ─── Distribution ─────────────────────────────────────────────

_DISTRIBUTABLE_TYPES = {"number", "duration", "scale", "time", "int", "float"}


@router.get("/metric-distribution")
async def metric_distribution(
    metric_id: int = Query(...),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    from app.distribution import compute_distribution, format_value

    qt = QueryTimer(f"distribution/{metric_id}")
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
    if is_blocked(metric.get("private", False), privacy_mode):
        return {"blocked": True}
    qt.mark("metric")

    mt = metric["type"]
    if mt == "integration":
        mt = metric["ic_value_type"] or "number"
    if mt == "computed":
        mt = metric.get("result_type") or "float"

    if mt not in _DISTRIBUTABLE_TYPES:
        return {"not_applicable": True, "reason": f"Type '{mt}' does not support distribution"}

    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)

    if metric["type"] == "computed":
        formula = ValueConverter.parse_formula(metric.get("formula"))
        ref_ids = get_referenced_metric_ids(formula)
        rt = metric.get("result_type") or "float"
        aggregated = await ValueFetcher(db).values_by_date_for_computed( formula, rt, ref_ids, start_date, end_date, current_user["id"],
        )
    else:
        aggregated = await ValueFetcher(db).values_by_date_for_slot( metric_id, mt, start_date, end_date, current_user["id"],
        )
    qt.mark("values")

    values = list(aggregated.values())
    if len(values) < 3:
        qt.log()
        return {"insufficient_data": True, "n": len(values)}

    result = compute_distribution(values, mt)
    qt.log()

    return {
        "metric_id": metric_id,
        "metric_type": mt,
        "n": result.n,
        "bins": [
            {
                "bin_start": b.bin_start,
                "bin_end": b.bin_end,
                "count": b.count,
                "label": b.label,
            }
            for b in result.bins
        ],
        "kde_x": result.kde_x,
        "kde_y": result.kde_y,
        "stats": {
            "mean": result.stats.mean,
            "median": result.stats.median,
            "variance": result.stats.variance,
            "std_dev": result.stats.std_dev,
            "skewness": result.stats.skewness,
            "kurtosis": result.stats.kurtosis,
        },
        "display_stats": [
            {"label": ds.label, "value": ds.value}
            for ds in result.display_stats
        ],
    }


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
    asyncio.create_task(run_correlation_report(report_id, current_user["id"], body.start, body.end, config=correlation_config))
    return {"report_id": report_id, "status": "running"}







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
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) > 0.7) AS sig_strong,
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) > 0.3
                                    AND ABS(correlation) <= 0.7) AS sig_medium,
                   COUNT(*) FILTER (WHERE quality_issue IS NULL AND ABS(correlation) <= 0.3) AS sig_weak,
                   COUNT(*) FILTER (WHERE quality_issue IN ('wide_ci', 'fisher_exact_high_p')) AS maybe,
                   COUNT(*) FILTER (WHERE quality_issue IS NOT NULL
                                    AND quality_issue NOT IN ('wide_ci', 'fisher_exact_high_p')) AS insig
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
                "maybe": counts_row["maybe"],
                "insig": counts_row["insig"],
            },
        }

    return {"running": running, "report": report}






@router.get("/correlation-report/{report_id}/pairs")
async def get_correlation_pairs(
    report_id: int,
    category: str = "all",
    offset: int = 0,
    limit: int = 50,
    metric_ids: str | None = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
):
    # Verify report belongs to user
    report_row = await db.fetchrow(
        "SELECT id FROM correlation_reports WHERE id = $1 AND user_id = $2",
        report_id, current_user["id"],
    )
    if not report_row:
        return {"pairs": [], "total": 0, "has_more": False}

    cat_filter = PairFormatter.CATEGORY_FILTERS.get(category, "")

    # Optional metric_ids filter
    metric_filter = ""
    args_base: list = [report_id]
    if metric_ids:
        ids_list = [int(x) for x in metric_ids.split(",") if x.strip()]
        if ids_list:
            idx = len(args_base) + 1
            metric_filter = f" AND cp.metric_a_id = ANY(${idx}::int[]) AND cp.metric_b_id = ANY(${idx}::int[])"
            args_base.append(ids_list)

    # Count total for this category
    total_row = await db.fetchrow(
        f"SELECT COUNT(*) AS cnt FROM correlation_pairs cp WHERE cp.report_id = $1 {cat_filter}{metric_filter}",
        *args_base,
    )
    total = total_row["cnt"]

    # Fetch page of pairs
    limit_idx = len(args_base) + 1
    offset_idx = len(args_base) + 2
    pairs = await db.fetch(
        f"""SELECT cp.id AS pair_id,
                   cp.type_a, cp.type_b, cp.correlation, cp.data_points, cp.lag_days, cp.p_value, cp.quality_issue,
                   cp.metric_a_id, cp.metric_b_id, cp.slot_a_id, cp.slot_b_id,
                   cp.source_key_a, cp.source_key_b,
                   ma.name AS name_a, ma.icon AS icon_a, COALESCE(ma.private, FALSE) AS private_a, ma.description AS description_a,
                   mb.name AS name_b, mb.icon AS icon_b, COALESCE(mb.private, FALSE) AS private_b, mb.description AS description_b,
                   sa.label AS slot_label_a,
                   sb.label AS slot_label_b
            FROM correlation_pairs cp
            LEFT JOIN metric_definitions ma ON ma.id = cp.metric_a_id
            LEFT JOIN metric_definitions mb ON mb.id = cp.metric_b_id
            LEFT JOIN measurement_slots sa ON sa.id = cp.slot_a_id
            LEFT JOIN measurement_slots sb ON sb.id = cp.slot_b_id
            WHERE cp.report_id = $1 {cat_filter}{metric_filter}
            ORDER BY ABS(cp.correlation) DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}""",
        *args_base, limit, offset,
    )

    # Collect all referenced IDs from source_keys for batch lookups
    all_parent_metric_ids: set[int] = set()
    all_enum_option_ids: set[int] = set()
    for p in pairs:
        for key_col in ("source_key_a", "source_key_b"):
            sk = SourceKey.parse(p[key_col])
            if sk.auto_parent_metric_id is not None:
                all_parent_metric_ids.add(sk.auto_parent_metric_id)
            if sk.enum_option_id is not None:
                all_enum_option_ids.add(sk.enum_option_id)
            if sk.auto_type in STREAK_TYPES and sk.auto_option_id is not None:
                all_enum_option_ids.add(sk.auto_option_id)

    # Batch: metric icons and names by id (for auto parents + all referenced metrics)
    metric_icons_by_id: dict[int, str] = {}
    parent_names: dict[int, str] = {}
    if all_parent_metric_ids:
        pm_rows = await db.fetch(
            "SELECT id, name, icon FROM metric_definitions WHERE id = ANY($1)",
            list(all_parent_metric_ids),
        )
        for r in pm_rows:
            parent_names[r["id"]] = r["name"]
            if r["icon"]:
                metric_icons_by_id[r["id"]] = r["icon"]

    # Batch: enum option labels
    enum_labels: dict[int, str] = {}
    if all_enum_option_ids:
        eo_rows = await db.fetch(
            "SELECT id, label FROM enum_options WHERE id = ANY($1)",
            list(all_enum_option_ids),
        )
        enum_labels = {r["id"]: r["label"] for r in eo_rows}

    # Batch: metrics with slots (for bool annotation)
    all_metric_ids: set[int] = set()
    for p in pairs:
        if p["metric_a_id"] is not None:
            all_metric_ids.add(p["metric_a_id"])
        if p["metric_b_id"] is not None:
            all_metric_ids.add(p["metric_b_id"])
    metrics_with_slots: set[int] = set()
    if all_metric_ids:
        mws_rows = await db.fetch(
            "SELECT DISTINCT metric_id FROM metric_slots WHERE metric_id = ANY($1) AND enabled = TRUE",
            list(all_metric_ids),
        )
        metrics_with_slots = {r["metric_id"] for r in mws_rows}

    return {
        "pairs": [PairFormatter(
            metric_icons=metric_icons_by_id, enum_labels=enum_labels,
            parent_names=parent_names, privacy_mode=privacy_mode,
            metrics_with_slots=metrics_with_slots,
        ).format_pair(p) for p in pairs],
        "total": total,
        "has_more": offset + limit < total,
    }






@router.get("/correlation-pair-chart")
async def correlation_pair_chart(
    pair_id: int = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    privacy_mode: bool = Depends(get_privacy_mode),
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

    # Check privacy for each side
    priv_a = False
    priv_b = False
    if row["metric_a_id"] is not None:
        ma_row = await db.fetchrow(
            "SELECT private FROM metric_definitions WHERE id = $1", row["metric_a_id"]
        )
        priv_a = ma_row["private"] if ma_row else False
    if row["metric_b_id"] is not None:
        mb_row = await db.fetchrow(
            "SELECT private FROM metric_definitions WHERE id = $1", row["metric_b_id"]
        )
        priv_b = mb_row["private"] if mb_row else False
    blocked_a = is_blocked(priv_a, privacy_mode)
    blocked_b = is_blocked(priv_b, privacy_mode)

    start_date = row["period_start"]
    end_date = row["period_end"]
    uid = current_user["id"]

    data_a = await SourceReconstructor(db).reconstruct( row["source_key_a"], row["type_a"], start_date, end_date, uid,
    )
    data_b = await SourceReconstructor(db).reconstruct( row["source_key_b"], row["type_b"], start_date, end_date, uid,
    )

    lag = row["lag_days"] or 0
    if lag > 0:
        data_b = TimeSeriesTransform.shift_dates(data_b, lag)

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

    # Resolve display labels from source_keys
    sk_a = SourceKey.parse(row["source_key_a"])
    sk_b = SourceKey.parse(row["source_key_b"])

    # Batch-lookup parent metric names for auto sources
    parent_ids = {mid for mid in (sk_a.auto_parent_metric_id, sk_b.auto_parent_metric_id) if mid is not None}
    parent_names: dict[int, str] = {}
    if parent_ids:
        pm_rows = await db.fetch(
            "SELECT id, name FROM metric_definitions WHERE id = ANY($1)",
            list(parent_ids),
        )
        parent_names = {r["id"]: r["name"] for r in pm_rows}

    # Metric names from JOIN (ma/mb)
    ma_name: str | None = None
    mb_name: str | None = None
    if row["metric_a_id"] is not None:
        ma_row = await db.fetchrow("SELECT name FROM metric_definitions WHERE id = $1", row["metric_a_id"])
        ma_name = ma_row["name"] if ma_row else None
    if row["metric_b_id"] is not None:
        mb_row = await db.fetchrow("SELECT name FROM metric_definitions WHERE id = $1", row["metric_b_id"])
        mb_name = mb_row["name"] if mb_row else None

    # Check if metrics have slots (for bool annotation)
    chart_metric_ids = [mid for mid in (row["metric_a_id"], row["metric_b_id"]) if mid is not None]
    chart_mws: set[int] = set()
    if chart_metric_ids:
        mws_rows = await db.fetch(
            "SELECT DISTINCT metric_id FROM metric_slots WHERE metric_id = ANY($1) AND enabled = TRUE",
            chart_metric_ids,
        )
        chart_mws = {r["metric_id"] for r in mws_rows}

    display_label_a = PRIVATE_MASK if blocked_a else PairFormatter.build_display_label(
        row["source_key_a"], ma_name, parent_names.get(sk_a.auto_parent_metric_id),
        metric_type=row["type_a"], has_slots=(row["metric_a_id"] in chart_mws if row["metric_a_id"] else False),
    )
    display_label_b = PRIVATE_MASK if blocked_b else PairFormatter.build_display_label(
        row["source_key_b"], mb_name, parent_names.get(sk_b.auto_parent_metric_id),
        metric_type=row["type_b"], has_slots=(row["metric_b_id"] in chart_mws if row["metric_b_id"] else False),
    )

    return {
        "dates": common if not (blocked_a or blocked_b) else [],
        "values_a": [data_a[d] for d in common] if not blocked_a else [],
        "values_b": [data_b[d] for d in common] if not blocked_b else [],
        "type_a": type_a,
        "type_b": type_b,
        "label_a": display_label_a,
        "label_b": display_label_b,
        "correlation": row["correlation"],
        "lag_days": lag,
        "original_dates_b": original_dates_b if not (blocked_a or blocked_b) else None,
    }


@router.get("/streaks")
async def streaks(db=Depends(get_db), current_user: dict = Depends(get_current_user), privacy_mode: bool = Depends(get_privacy_mode)):
    metrics = await db.fetch(
        """SELECT * FROM metric_definitions
           WHERE enabled = TRUE AND user_id = $1 AND type = 'bool'
           ORDER BY sort_order""",
        current_user["id"],
    )

    result = []
    for m in metrics:
        m_private = m.get("private", False)
        m_blocked = is_blocked(m_private, privacy_mode)
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
                "metric_name": mask_name(m["name"], m_private, privacy_mode),
                "current_streak": 0 if m_blocked else current_streak,
            })

    return {"streaks": result}
