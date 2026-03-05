"""
ActivityWatch integration service.

Receives raw events from the frontend (which fetches them from localhost:5600),
processes them into per-app summaries, and upserts into dedicated AW tables.
"""
from collections import defaultdict
from datetime import date as date_type, datetime
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

    async with conn.transaction():
        await conn.execute(
            """INSERT INTO activitywatch_daily_summary
                   (user_id, date, total_seconds, active_seconds, synced_at)
               VALUES ($1, $2, $3, $4, now())
               ON CONFLICT (user_id, date) DO UPDATE
               SET total_seconds = EXCLUDED.total_seconds,
                   active_seconds = EXCLUDED.active_seconds,
                   synced_at = now()""",
            user_id, for_date, total_seconds, active_seconds,
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
