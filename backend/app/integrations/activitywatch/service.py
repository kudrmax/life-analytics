"""
ActivityWatch integration service.

Receives raw events from the frontend (which fetches them from localhost:5600),
processes them into per-app summaries, and upserts into dedicated AW tables.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.repositories.integrations_repository import IntegrationsRepository


async def process_and_store(
    repo: IntegrationsRepository,
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

    async with repo.conn.transaction():
        await repo.upsert_aw_daily_summary(
            for_date, total_seconds, active_seconds,
            first_activity, last_activity, afk_seconds,
            longest_session, ctx_switches, breaks,
        )

        await repo.delete_aw_app_usage_for_date(for_date)

        rows = []
        for app_name, dur in app_durations.items():
            if dur > 0:
                rows.append((repo.user_id, for_date, app_name, "window", dur))
        for domain, dur in domain_durations.items():
            if dur > 0:
                rows.append((repo.user_id, for_date, domain, "web", dur))

        await repo.insert_aw_app_usage_batch(rows)

    apps_list = [
        {"app_name": k, "duration_seconds": v}
        for k, v in sorted(app_durations.items(), key=lambda x: -x[1])
    ]
    domains_list = [
        {"domain": k, "duration_seconds": v}
        for k, v in sorted(domain_durations.items(), key=lambda x: -x[1])
    ]

    # Compute integration metrics for this user/date
    await compute_integration_metrics(repo, for_date)

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
    repo: IntegrationsRepository,
    for_date: date_type,
) -> None:
    """Compute values for all AW integration metrics for this user/date."""
    from app.repositories.entry_repository import EntryRepository
    entry_repo = EntryRepository(repo.conn, repo.user_id)

    rows = await repo.get_aw_integration_metrics()
    if not rows:
        return

    # Load daily summary once
    summary = await repo.get_aw_summary_full(for_date)

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
                unique_apps = await repo.get_unique_apps_count(for_date)
            value = unique_apps
        elif key == "category_time":
            cat_id = r["activitywatch_category_id"]
            if cat_id:
                secs = await repo.get_category_time_seconds(for_date, cat_id)
                value = secs // 60
            else:
                value = 0
        elif key == "app_time":
            app_name = r["config_app_name"]
            if app_name:
                secs = await repo.get_app_time_seconds(for_date, app_name)
                value = secs // 60
            else:
                value = 0
        else:
            continue

        # Upsert entry + value
        existing = await repo.get_entry_by_metric_date(metric_id, for_date)
        if existing:
            await entry_repo.update_value(existing["id"], value, value_type, entry_date=for_date, metric_id=metric_id)
        else:
            entry_id = await repo.create_entry(metric_id, for_date)
            await entry_repo.insert_value(entry_id, value, value_type, entry_date=for_date, metric_id=metric_id)
