"""
ActivityWatch integration service.

Receives raw events from the frontend (which fetches them from localhost:5600),
processes them into per-app summaries, and upserts into dedicated AW tables.
"""
from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from urllib.parse import urlparse

import asyncpg


async def process_and_store(
    conn: asyncpg.Connection,
    user_id: int,
    for_date: date_type,
    window_events: list[dict],
    afk_events: list[dict],
    web_events: list[dict] | None = None,
) -> dict:
    """Process raw AW events and store aggregated summaries.

    Returns:
        {"total_seconds": int, "active_seconds": int, "apps": [...], "domains": [...]}
    """
    active_intervals = _build_active_intervals(afk_events)

    app_durations = _compute_app_durations(window_events, active_intervals)

    total_seconds = sum(int(e.get("duration", 0)) for e in window_events)
    active_seconds = sum(app_durations.values())

    domain_durations = {}
    if web_events:
        domain_durations = _compute_domain_durations(web_events, active_intervals)

    # Compute extended metrics
    first_activity, last_activity = _compute_time_boundaries(active_intervals, for_date)
    afk_seconds = _compute_afk_time(active_intervals, first_activity, last_activity)
    longest_session = _compute_longest_session(active_intervals)
    ctx_switches = _compute_context_switches(window_events, active_intervals)
    breaks = _compute_break_count(afk_events)

    async with conn.transaction():
        await conn.execute(
            """INSERT INTO activitywatch_daily_summary
                   (user_id, date, total_seconds, active_seconds, synced_at,
                    first_activity_time, last_activity_time, afk_seconds,
                    longest_session_seconds, context_switches, break_count)
               VALUES ($1, $2, $3, $4, now(), $5, $6, $7, $8, $9, $10)
               ON CONFLICT (user_id, date) DO UPDATE
               SET total_seconds = EXCLUDED.total_seconds,
                   active_seconds = EXCLUDED.active_seconds,
                   first_activity_time = EXCLUDED.first_activity_time,
                   last_activity_time = EXCLUDED.last_activity_time,
                   afk_seconds = EXCLUDED.afk_seconds,
                   longest_session_seconds = EXCLUDED.longest_session_seconds,
                   context_switches = EXCLUDED.context_switches,
                   break_count = EXCLUDED.break_count,
                   synced_at = now()""",
            user_id, for_date, total_seconds, active_seconds,
            first_activity, last_activity, afk_seconds,
            longest_session, ctx_switches, breaks,
        )

        await conn.execute(
            "DELETE FROM activitywatch_app_usage WHERE user_id = $1 AND date = $2",
            user_id, for_date,
        )

        rows = []
        for app_name, dur in app_durations.items():
            if dur > 0:
                rows.append((user_id, for_date, app_name, "window", dur))
        for domain, dur in domain_durations.items():
            if dur > 0:
                rows.append((user_id, for_date, domain, "web", dur))

        if rows:
            await conn.executemany(
                """INSERT INTO activitywatch_app_usage
                       (user_id, date, app_name, source, duration_seconds)
                   VALUES ($1, $2, $3, $4, $5)""",
                rows,
            )

    apps_list = [
        {"app_name": k, "duration_seconds": v}
        for k, v in sorted(app_durations.items(), key=lambda x: -x[1])
    ]
    domains_list = [
        {"domain": k, "duration_seconds": v}
        for k, v in sorted(domain_durations.items(), key=lambda x: -x[1])
    ]

    # Compute integration metrics for this user/date
    await compute_integration_metrics(conn, user_id, for_date)

    return {
        "total_seconds": total_seconds,
        "active_seconds": active_seconds,
        "apps": apps_list,
        "domains": domains_list,
    }


def _build_active_intervals(afk_events: list[dict]) -> list[tuple[float, float]]:
    """Build sorted, merged list of (start_ts, end_ts) where user is NOT afk."""
    intervals = []
    for e in afk_events:
        if e.get("data", {}).get("status") == "not-afk":
            start = _parse_ts(e["timestamp"])
            end = start + float(e.get("duration", 0))
            intervals.append((start, end))
    intervals.sort()
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _compute_app_durations(
    window_events: list[dict],
    active_intervals: list[tuple[float, float]],
) -> dict[str, int]:
    """Compute per-app active duration in seconds."""
    app_dur: dict[str, float] = defaultdict(float)
    for e in window_events:
        app = e.get("data", {}).get("app", "unknown")
        start = _parse_ts(e["timestamp"])
        duration = float(e.get("duration", 0))
        end = start + duration
        active_dur = _intersect_duration(start, end, active_intervals)
        app_dur[app] += active_dur
    return {k: int(v) for k, v in app_dur.items()}


def _compute_domain_durations(
    web_events: list[dict],
    active_intervals: list[tuple[float, float]],
) -> dict[str, int]:
    """Compute per-domain active duration in seconds."""
    domain_dur: dict[str, float] = defaultdict(float)
    for e in web_events:
        url = e.get("data", {}).get("url", "")
        try:
            domain = urlparse(url).netloc or url
        except Exception:
            domain = url
        start = _parse_ts(e["timestamp"])
        duration = float(e.get("duration", 0))
        end = start + duration
        active_dur = _intersect_duration(start, end, active_intervals)
        domain_dur[domain] += active_dur
    return {k: int(v) for k, v in domain_dur.items()}


def _intersect_duration(
    start: float, end: float, intervals: list[tuple[float, float]]
) -> float:
    """Calculate how much of [start, end] overlaps with the given sorted intervals."""
    total = 0.0
    for i_start, i_end in intervals:
        if i_start >= end:
            break
        if i_end <= start:
            continue
        overlap_start = max(start, i_start)
        overlap_end = min(end, i_end)
        total += max(0, overlap_end - overlap_start)
    return total


def _parse_ts(ts_str: str) -> float:
    """Parse ISO timestamp to Unix timestamp (float seconds)."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return dt.timestamp()


def _compute_time_boundaries(
    active_intervals: list[tuple[float, float]],
    for_date: date_type,
) -> tuple[datetime | None, datetime | None]:
    """Return (first_activity, last_activity) as datetime objects."""
    if not active_intervals:
        return None, None
    first_ts = active_intervals[0][0]
    last_ts = max(end for _, end in active_intervals)
    return (
        datetime.fromtimestamp(first_ts, tz=timezone.utc),
        datetime.fromtimestamp(last_ts, tz=timezone.utc),
    )


def _compute_afk_time(
    active_intervals: list[tuple[float, float]],
    first: datetime | None,
    last: datetime | None,
) -> int:
    """AFK seconds between first and last activity."""
    if not first or not last or not active_intervals:
        return 0
    total_span = last.timestamp() - first.timestamp()
    active_in_span = sum(
        min(end, last.timestamp()) - max(start, first.timestamp())
        for start, end in active_intervals
        if end > first.timestamp() and start < last.timestamp()
    )
    return max(0, int(total_span - active_in_span))


def _compute_longest_session(active_intervals: list[tuple[float, float]]) -> int:
    """Longest continuous active interval in seconds."""
    if not active_intervals:
        return 0
    return int(max(end - start for start, end in active_intervals))


def _compute_context_switches(
    window_events: list[dict],
    active_intervals: list[tuple[float, float]],
) -> int:
    """Count app changes during active time."""
    if not window_events or not active_intervals:
        return 0
    sorted_events = sorted(window_events, key=lambda e: _parse_ts(e["timestamp"]))
    switches = 0
    prev_app = None
    for e in sorted_events:
        start = _parse_ts(e["timestamp"])
        dur = float(e.get("duration", 0))
        end = start + dur
        if _intersect_duration(start, end, active_intervals) <= 0:
            continue
        app = e.get("data", {}).get("app", "unknown")
        if prev_app is not None and app != prev_app:
            switches += 1
        prev_app = app
    return switches


def _compute_break_count(afk_events: list[dict], threshold: int = 300) -> int:
    """Count AFK periods longer than threshold (default 5 min)."""
    count = 0
    for e in afk_events:
        if e.get("data", {}).get("status") == "afk":
            dur = float(e.get("duration", 0))
            if dur >= threshold:
                count += 1
    return count


async def compute_integration_metrics(
    conn: asyncpg.Connection,
    user_id: int,
    for_date: date_type,
):
    """Compute values for all AW integration metrics for this user/date."""
    from app.repositories.entry_repository import EntryRepository
    entry_repo = EntryRepository(conn, user_id)

    rows = await conn.fetch(
        """SELECT md.id AS metric_id, ic.metric_key, ic.value_type,
                  icc.activitywatch_category_id, iac.app_name AS config_app_name
           FROM metric_definitions md
           JOIN integration_config ic ON ic.metric_id = md.id
           LEFT JOIN integration_category_config icc ON icc.metric_id = md.id
           LEFT JOIN integration_app_config iac ON iac.metric_id = md.id
           WHERE md.user_id = $1 AND ic.provider = 'activitywatch' AND md.enabled = TRUE""",
        user_id,
    )
    if not rows:
        return

    # Load daily summary once
    summary = await conn.fetchrow(
        """SELECT total_seconds, active_seconds,
                  first_activity_time, last_activity_time,
                  afk_seconds, longest_session_seconds,
                  context_switches, break_count
           FROM activitywatch_daily_summary
           WHERE user_id = $1 AND date = $2""",
        user_id, for_date,
    )

    # Unique apps count
    unique_apps = None

    for r in rows:
        metric_id = r["metric_id"]
        key = r["metric_key"]
        value_type = r["value_type"]
        value = None

        if key == "active_screen_time":
            value = (summary["active_seconds"] // 60) if summary else 0
        elif key == "total_screen_time":
            value = (summary["total_seconds"] // 60) if summary else 0
        elif key == "first_activity":
            if summary and summary["first_activity_time"]:
                ts = summary["first_activity_time"]
                value = f"{ts.hour:02d}:{ts.minute:02d}"
            else:
                continue  # no data — skip
        elif key == "last_activity":
            if summary and summary["last_activity_time"]:
                ts = summary["last_activity_time"]
                value = f"{ts.hour:02d}:{ts.minute:02d}"
            else:
                continue
        elif key == "afk_time":
            value = (summary["afk_seconds"] // 60) if summary else 0
        elif key == "longest_session":
            value = (summary["longest_session_seconds"] // 60) if summary else 0
        elif key == "context_switches":
            value = summary["context_switches"] if summary else 0
        elif key == "break_count":
            value = summary["break_count"] if summary else 0
        elif key == "unique_apps":
            if unique_apps is None:
                unique_apps = await conn.fetchval(
                    """SELECT COUNT(DISTINCT app_name) FROM activitywatch_app_usage
                       WHERE user_id = $1 AND date = $2 AND source = 'window'""",
                    user_id, for_date,
                )
            value = unique_apps or 0
        elif key == "category_time":
            cat_id = r["activitywatch_category_id"]
            if cat_id:
                secs = await conn.fetchval(
                    """SELECT COALESCE(SUM(au.duration_seconds), 0)
                       FROM activitywatch_app_usage au
                       JOIN activitywatch_app_category_map acm
                           ON acm.app_name = au.app_name AND acm.user_id = au.user_id
                       WHERE au.user_id = $1 AND au.date = $2 AND acm.activitywatch_category_id = $3
                             AND au.source = 'window'""",
                    user_id, for_date, cat_id,
                )
                value = (secs or 0) // 60
            else:
                value = 0
        elif key == "app_time":
            app_name = r["config_app_name"]
            if app_name:
                secs = await conn.fetchval(
                    """SELECT COALESCE(duration_seconds, 0)
                       FROM activitywatch_app_usage
                       WHERE user_id = $1 AND date = $2 AND app_name = $3 AND source = 'window'""",
                    user_id, for_date, app_name,
                )
                value = (secs or 0) // 60
            else:
                value = 0
        else:
            continue

        # Upsert entry + value
        existing = await conn.fetchrow(
            "SELECT id FROM entries WHERE metric_id = $1 AND user_id = $2 AND date = $3 AND slot_id IS NULL",
            metric_id, user_id, for_date,
        )
        if existing:
            await entry_repo.update_value(existing["id"], value, value_type, entry_date=for_date, metric_id=metric_id)
        else:
            entry_id = await conn.fetchval(
                """INSERT INTO entries (metric_id, user_id, date)
                   VALUES ($1, $2, $3) RETURNING id""",
                metric_id, user_id, for_date,
            )
            await entry_repo.insert_value(entry_id, value, value_type, entry_date=for_date, metric_id=metric_id)
