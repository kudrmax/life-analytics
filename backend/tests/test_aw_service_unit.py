"""Unit tests for pure functions in activitywatch/service.py (no DB)."""

from datetime import date, datetime, timezone

import pytest

from app.integrations.activitywatch.service import (
    _build_active_intervals,
    _compute_afk_time,
    _compute_app_durations,
    _compute_break_count,
    _compute_context_switches,
    _compute_longest_session,
    _compute_time_boundaries,
    _intersect_duration,
    _parse_ts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BASE_TS = "2026-01-10T10:00:00+00:00"
BASE_UNIX = _parse_ts(BASE_TS)


def _afk_event(
    offset: float,
    duration: float,
    status: str = "not-afk",
) -> dict:
    """Build an AFK event shifted by *offset* seconds from BASE_TS."""
    dt = datetime.fromtimestamp(BASE_UNIX + offset, tz=timezone.utc)
    return {
        "timestamp": dt.isoformat(),
        "duration": duration,
        "data": {"status": status},
    }


def _window_event(offset: float, duration: float, app: str = "Firefox") -> dict:
    dt = datetime.fromtimestamp(BASE_UNIX + offset, tz=timezone.utc)
    return {
        "timestamp": dt.isoformat(),
        "duration": duration,
        "data": {"app": app},
    }


# =========================================================================
# _build_active_intervals
# =========================================================================
class TestBuildActiveIntervals:
    """Tests for _build_active_intervals."""

    def test_empty_events(self) -> None:
        assert _build_active_intervals([]) == []

    def test_single_not_afk_event(self) -> None:
        events = [_afk_event(0, 300)]
        result = _build_active_intervals(events)
        assert len(result) == 1
        start, end = result[0]
        assert end - start == pytest.approx(300)

    def test_overlapping_events_merged(self) -> None:
        # Two events: 0..300 and 200..500 -> merged into 0..500
        events = [
            _afk_event(0, 300),
            _afk_event(200, 300),
        ]
        result = _build_active_intervals(events)
        assert len(result) == 1
        start, end = result[0]
        assert end - start == pytest.approx(500)

    def test_non_overlapping_events(self) -> None:
        # Two events: 0..100 and 200..300 -> two intervals
        events = [
            _afk_event(0, 100),
            _afk_event(200, 100),
        ]
        result = _build_active_intervals(events)
        assert len(result) == 2

    def test_afk_events_ignored(self) -> None:
        events = [
            _afk_event(0, 300, status="afk"),
            _afk_event(400, 300, status="afk"),
        ]
        assert _build_active_intervals(events) == []


# =========================================================================
# _compute_app_durations
# =========================================================================
class TestComputeAppDurations:
    """Tests for _compute_app_durations."""

    def test_single_app_full_overlap(self) -> None:
        active = [(BASE_UNIX, BASE_UNIX + 600)]
        events = [_window_event(0, 300)]
        result = _compute_app_durations(events, active)
        assert result["Firefox"] == 300

    def test_single_app_partial_overlap(self) -> None:
        # Active: 100..400, event: 0..300 -> overlap 100..300 = 200s
        active = [(BASE_UNIX + 100, BASE_UNIX + 400)]
        events = [_window_event(0, 300)]
        result = _compute_app_durations(events, active)
        assert result["Firefox"] == 200

    def test_single_app_no_overlap(self) -> None:
        # Active: 500..600, event: 0..100 -> no overlap
        active = [(BASE_UNIX + 500, BASE_UNIX + 600)]
        events = [_window_event(0, 100)]
        result = _compute_app_durations(events, active)
        assert result["Firefox"] == 0

    def test_multiple_apps(self) -> None:
        active = [(BASE_UNIX, BASE_UNIX + 600)]
        events = [
            _window_event(0, 200, app="Firefox"),
            _window_event(200, 100, app="VSCode"),
            _window_event(300, 150, app="Firefox"),
        ]
        result = _compute_app_durations(events, active)
        assert result["Firefox"] == 350
        assert result["VSCode"] == 100


# =========================================================================
# _intersect_duration
# =========================================================================
class TestIntersectDuration:
    """Tests for _intersect_duration."""

    def test_no_overlap(self) -> None:
        intervals = [(100.0, 200.0)]
        assert _intersect_duration(300.0, 400.0, intervals) == pytest.approx(0)

    def test_full_overlap(self) -> None:
        # Interval fully contains the segment
        intervals = [(0.0, 500.0)]
        assert _intersect_duration(100.0, 200.0, intervals) == pytest.approx(100)

    def test_partial_overlap(self) -> None:
        # Segment 50..150 with interval 100..200 -> overlap 100..150 = 50
        intervals = [(100.0, 200.0)]
        assert _intersect_duration(50.0, 150.0, intervals) == pytest.approx(50)

    def test_multiple_intervals(self) -> None:
        # Segment 0..500, intervals 100..200 and 300..400 -> 100 + 100 = 200
        intervals = [(100.0, 200.0), (300.0, 400.0)]
        assert _intersect_duration(0.0, 500.0, intervals) == pytest.approx(200)


# =========================================================================
# _parse_ts
# =========================================================================
class TestParseTs:
    """Tests for _parse_ts."""

    def test_iso_with_offset(self) -> None:
        result = _parse_ts("2026-01-10T10:00:00+00:00")
        expected = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        assert result == pytest.approx(expected)

    def test_iso_with_z(self) -> None:
        result = _parse_ts("2026-01-10T10:00:00Z")
        expected = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        assert result == pytest.approx(expected)


# =========================================================================
# _compute_break_count
# =========================================================================
class TestComputeBreakCount:
    """Tests for _compute_break_count."""

    def test_no_afk_events(self) -> None:
        assert _compute_break_count([]) == 0

    def test_afk_above_threshold(self) -> None:
        events = [
            _afk_event(0, 600, status="afk"),   # 10 min >= 5 min threshold
            _afk_event(700, 400, status="afk"),  # 6.7 min >= threshold
        ]
        assert _compute_break_count(events) == 2

    def test_afk_below_threshold(self) -> None:
        events = [
            _afk_event(0, 100, status="afk"),  # 100s < 300s threshold
            _afk_event(200, 60, status="afk"),  # 60s < 300s threshold
        ]
        assert _compute_break_count(events) == 0


# =========================================================================
# _compute_context_switches
# =========================================================================
class TestComputeContextSwitches:
    """Tests for _compute_context_switches."""

    def test_empty_events(self) -> None:
        assert _compute_context_switches([], []) == 0

    def test_same_app_repeated(self) -> None:
        active = [(BASE_UNIX, BASE_UNIX + 600)]
        events = [
            _window_event(0, 100, app="Firefox"),
            _window_event(100, 100, app="Firefox"),
            _window_event(200, 100, app="Firefox"),
        ]
        assert _compute_context_switches(events, active) == 0

    def test_different_apps(self) -> None:
        active = [(BASE_UNIX, BASE_UNIX + 600)]
        events = [
            _window_event(0, 100, app="Firefox"),
            _window_event(100, 100, app="VSCode"),
            _window_event(200, 100, app="Terminal"),
        ]
        # Firefox->VSCode, VSCode->Terminal = 2 switches
        assert _compute_context_switches(events, active) == 2


# =========================================================================
# _compute_longest_session
# =========================================================================
class TestComputeLongestSession:
    """Tests for _compute_longest_session."""

    def test_empty(self) -> None:
        assert _compute_longest_session([]) == 0

    def test_multiple_intervals(self) -> None:
        intervals = [
            (0.0, 100.0),   # 100s
            (200.0, 500.0), # 300s  <- longest
            (600.0, 700.0), # 100s
        ]
        assert _compute_longest_session(intervals) == 300


# =========================================================================
# _compute_time_boundaries
# =========================================================================
class TestComputeTimeBoundaries:
    """Tests for _compute_time_boundaries."""

    def test_empty_intervals(self) -> None:
        first, last = _compute_time_boundaries([], date(2026, 1, 10))
        assert first is None
        assert last is None

    def test_multiple_intervals(self) -> None:
        ts_start = BASE_UNIX
        intervals = [
            (ts_start, ts_start + 100),
            (ts_start + 200, ts_start + 500),
        ]
        first, last = _compute_time_boundaries(intervals, date(2026, 1, 10))
        assert first == datetime.fromtimestamp(ts_start, tz=timezone.utc)
        assert last == datetime.fromtimestamp(ts_start + 500, tz=timezone.utc)


# =========================================================================
# _compute_afk_time
# =========================================================================
class TestComputeAfkTime:
    """Tests for _compute_afk_time."""

    def test_no_intervals(self) -> None:
        assert _compute_afk_time([], None, None) == 0

    def test_some_active_time(self) -> None:
        ts = BASE_UNIX
        # Span: 0..1000 = 1000s total
        # Active: 0..200 + 400..600 = 400s active => 600s AFK
        intervals = [
            (ts, ts + 200),
            (ts + 400, ts + 600),
        ]
        first = datetime.fromtimestamp(ts, tz=timezone.utc)
        last = datetime.fromtimestamp(ts + 1000, tz=timezone.utc)
        assert _compute_afk_time(intervals, first, last) == 600
