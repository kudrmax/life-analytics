"""API integration tests for analytics trends and metric-stats endpoints."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = "2026-01-10"
_END = "2026-01-14"
_DATES = ["2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13", "2026-01-14"]


async def _trends(
    client: AsyncClient, token: str, metric_id: int,
    start: str = _START, end: str = _END,
) -> dict:
    resp = await client.get(
        "/api/analytics/trends",
        params={"metric_id": metric_id, "start": start, "end": end},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _metric_stats(
    client: AsyncClient, token: str, metric_id: int,
    start: str = _START, end: str = _END,
) -> dict:
    resp = await client.get(
        "/api/analytics/metric-stats",
        params={"metric_id": metric_id, "start": start, "end": end},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _enable_privacy(client: AsyncClient, token: str) -> None:
    resp = await client.put(
        "/api/auth/privacy-mode",
        json={"enabled": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


async def _create_enum_metric(
    client: AsyncClient, token: str, *, name: str = "Mood",
) -> dict:
    resp = await client.post(
        "/api/metrics",
        json={"name": name, "type": "enum", "enum_options": ["Good", "Bad", "Meh"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_computed_metric(
    client: AsyncClient, token: str,
    *, name: str, formula: list[dict], result_type: str = "float",
) -> dict:
    resp = await client.post(
        "/api/metrics",
        json={
            "name": name,
            "type": "computed",
            "formula": formula,
            "result_type": result_type,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

class TestTrendsEmpty:
    """Trends for metric with no entries."""

    async def test_no_entries_returns_empty_points(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Empty", metric_type="bool",
        )
        data = await _trends(client, user_a["token"], metric["id"])
        assert data["metric_id"] == metric["id"]
        assert data["points"] == []


class TestTrendsBool:
    """Trends for bool metric."""

    async def test_bool_values_are_1_or_0(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Exercise", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", False)
        await create_entry(client, token, mid, "2026-01-12", True)

        data = await _trends(client, token, mid)
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 1.0
        assert values["2026-01-11"] == 0.0
        assert values["2026-01-12"] == 1.0


class TestTrendsNumber:
    """Trends for number metric."""

    async def test_number_values_are_floats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Steps", metric_type="number",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", 100)
        await create_entry(client, token, mid, "2026-01-11", 200)
        await create_entry(client, token, mid, "2026-01-12", 300)

        data = await _trends(client, token, mid)
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 100.0
        assert values["2026-01-11"] == 200.0
        assert values["2026-01-12"] == 300.0


class TestTrendsScale:
    """Trends for scale metric — values normalized to 0-100 percentage."""

    async def test_scale_values_normalized(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Energy", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        token = user_a["token"]
        # value=1 → (1-1)/(5-1)*100 = 0.0
        await create_entry(client, token, mid, "2026-01-10", 1)
        # value=3 → (3-1)/(5-1)*100 = 50.0
        await create_entry(client, token, mid, "2026-01-11", 3)
        # value=5 → (5-1)/(5-1)*100 = 100.0
        await create_entry(client, token, mid, "2026-01-12", 5)

        data = await _trends(client, token, mid)
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 0.0
        assert values["2026-01-11"] == 50.0
        assert values["2026-01-12"] == 100.0


class TestTrendsDuration:
    """Trends for duration metric — values are float minutes."""

    async def test_duration_values_are_minutes(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Sleep", metric_type="duration",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", 480)
        await create_entry(client, token, mid, "2026-01-11", 420)

        data = await _trends(client, token, mid)
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 480.0
        assert values["2026-01-11"] == 420.0


class TestTrendsTime:
    """Trends for time metric — values are minutes from midnight."""

    async def test_time_values_are_minutes_from_midnight(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Wake up", metric_type="time",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 07:30 → 450 minutes
        await create_entry(client, token, mid, "2026-01-10", "07:30")
        # 08:15 → 495 minutes
        await create_entry(client, token, mid, "2026-01-11", "08:15")

        data = await _trends(client, token, mid)
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 450.0
        assert values["2026-01-11"] == 495.0


class TestTrendsPrivacy:
    """Trends blocked for private metric when privacy mode is on."""

    async def test_private_metric_blocked(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Secret", "type": "bool", "private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        mid = metric["id"]
        token = user_a["token"]

        await create_entry(client, token, mid, "2026-01-10", True)
        await _enable_privacy(client, token)

        data = await _trends(client, token, mid)
        assert data["blocked"] is True
        assert data["metric_name"] == "***"
        assert data["points"] == []


class TestTrendsDisabledMetric:
    """Disabled metric is still accessible via trends (no enabled filter)."""

    async def test_disabled_metric_still_returns_data(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Toggled", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)

        # Disable metric
        await client.put(
            f"/api/metrics/{mid}",
            json={"enabled": False},
            headers=auth_headers(token),
        )

        data = await _trends(client, token, mid)
        # Still returns data — trends doesn't filter by enabled
        assert len(data["points"]) == 1


class TestTrendsDateFiltering:
    """Entries outside range are excluded."""

    async def test_only_entries_in_range_included(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Filtered", metric_type="number",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-09", 1)   # before range
        await create_entry(client, token, mid, "2026-01-10", 10)  # in range
        await create_entry(client, token, mid, "2026-01-14", 50)  # in range
        await create_entry(client, token, mid, "2026-01-15", 99)  # after range

        data = await _trends(client, token, mid)
        dates = [p["date"] for p in data["points"]]
        assert "2026-01-09" not in dates
        assert "2026-01-15" not in dates
        assert "2026-01-10" in dates
        assert "2026-01-14" in dates
        assert len(data["points"]) == 2


class TestTrendsFilledDays:
    """Correct number of filled days."""

    async def test_filled_days_match_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Count", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-12", False)
        await create_entry(client, token, mid, "2026-01-14", True)

        data = await _trends(client, token, mid)
        assert len(data["points"]) == 3


# ---------------------------------------------------------------------------
# Multi-slot in trends
# ---------------------------------------------------------------------------

class TestTrendsMultiSlot:
    """Metric with slots — values aggregated (averaged) per day."""

    async def test_multi_slot_values_averaged(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"],
            name="Multi", metric_type="number",
            slot_labels=["Morning", "Evening"],
        )
        mid = metric["id"]
        token = user_a["token"]
        slots = metric["slots"]
        slot_morning = slots[0]["id"]
        slot_evening = slots[1]["id"]

        # Morning=100, Evening=200 → avg=150
        await create_entry(client, token, mid, "2026-01-10", 100, slot_id=slot_morning)
        await create_entry(client, token, mid, "2026-01-10", 200, slot_id=slot_evening)

        data = await _trends(client, token, mid)
        assert len(data["points"]) == 1
        assert data["points"][0]["date"] == "2026-01-10"
        assert data["points"][0]["value"] == 150.0


# ---------------------------------------------------------------------------
# Metric-stats: bool
# ---------------------------------------------------------------------------

class TestMetricStatsBool:
    """Stats for bool metric."""

    async def test_bool_stats_yes_percent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="BoolStats", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 3 True, 2 False
        for i, val in enumerate([True, True, True, False, False]):
            await create_entry(client, token, mid, _DATES[i], val)

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_id"] == mid
        assert stats["metric_type"] == "bool"
        assert stats["yes_count"] == 3
        assert stats["no_count"] == 2
        assert stats["yes_percent"] == 60.0
        assert stats["total_entries"] == 5
        assert stats["total_days"] == 5

    async def test_bool_stats_avg_between_0_and_1(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="BoolAvg", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", False)

        stats = await _metric_stats(client, token, mid)
        assert 0 <= stats["yes_percent"] <= 100


# ---------------------------------------------------------------------------
# Metric-stats: number
# ---------------------------------------------------------------------------

class TestMetricStatsNumber:
    """Stats for number metric — avg/min/max/median."""

    async def test_number_stats_correct(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="NumStats", metric_type="number",
        )
        mid = metric["id"]
        token = user_a["token"]
        for i, val in enumerate([10, 20, 30, 40, 50]):
            await create_entry(client, token, mid, _DATES[i], val)

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_type"] == "number"
        assert stats["average"] == 30.0
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["median"] == 30.0
        assert stats["total_entries"] == 5


# ---------------------------------------------------------------------------
# Metric-stats: duration
# ---------------------------------------------------------------------------

class TestMetricStatsDuration:
    """Stats for duration metric."""

    async def test_duration_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="DurStats", metric_type="duration",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 60, 120, 180 minutes
        await create_entry(client, token, mid, "2026-01-10", 60)
        await create_entry(client, token, mid, "2026-01-11", 120)
        await create_entry(client, token, mid, "2026-01-12", 180)

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_type"] == "duration"
        # average = 120 min = 2h 0m
        assert stats["average"] == "2ч 0м"
        assert stats["min"] == "1ч 0м"
        assert stats["max"] == "3ч 0м"
        assert stats["median"] == "2ч 0м"
        assert stats["total_entries"] == 3


# ---------------------------------------------------------------------------
# Metric-stats: scale
# ---------------------------------------------------------------------------

class TestMetricStatsScale:
    """Stats for scale metric — normalized percentages."""

    async def test_scale_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="ScaleStats", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        token = user_a["token"]
        # value=1 → 0%, value=3 → 50%, value=5 → 100%
        await create_entry(client, token, mid, "2026-01-10", 1)
        await create_entry(client, token, mid, "2026-01-11", 3)
        await create_entry(client, token, mid, "2026-01-12", 5)

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_type"] == "scale"
        assert stats["average"] == 50.0
        assert stats["min"] == 0.0
        assert stats["max"] == 100.0
        assert stats["total_entries"] == 3


# ---------------------------------------------------------------------------
# Metric-stats: empty data
# ---------------------------------------------------------------------------

class TestMetricStatsEmpty:
    """Stats with no entries — zeros/defaults."""

    async def test_empty_number_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EmptyNum", metric_type="number",
        )
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        assert stats["total_entries"] == 0
        assert stats["average"] == 0
        assert stats["min"] == 0
        assert stats["max"] == 0
        assert stats["median"] == 0

    async def test_empty_bool_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EmptyBool", metric_type="bool",
        )
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        assert stats["total_entries"] == 0
        assert stats["yes_count"] == 0
        assert stats["no_count"] == 0
        assert stats["yes_percent"] == 0


# ---------------------------------------------------------------------------
# Metric-stats: streaks (bool)
# ---------------------------------------------------------------------------

class TestMetricStatsStreaks:
    """Current and longest streak for bool metrics."""

    async def test_current_streak(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Streak", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        # Pattern: True, False, True, True, True → current streak = 3 (from end)
        for i, val in enumerate([True, False, True, True, True]):
            await create_entry(client, token, mid, _DATES[i], val)

        stats = await _metric_stats(client, token, mid)
        assert stats["current_streak"] == 3

    async def test_longest_streak(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="LStreak", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        # Dates spread wider to allow gaps:
        # True, True, True, False, True → longest=3
        dates = [
            "2026-01-01", "2026-01-02", "2026-01-03",
            "2026-01-04", "2026-01-05",
        ]
        for d, val in zip(dates, [True, True, True, False, True]):
            await create_entry(client, token, mid, d, val)

        stats = await _metric_stats(
            client, token, mid, start="2026-01-01", end="2026-01-05",
        )
        assert stats["longest_streak"] == 3
        assert stats["current_streak"] == 1


# ---------------------------------------------------------------------------
# Metric-stats: filled days
# ---------------------------------------------------------------------------

class TestMetricStatsFilledDays:
    """Correct fill_rate and total_entries."""

    async def test_filled_days_count(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="FillRate", metric_type="number",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 3 entries out of 5 days
        await create_entry(client, token, mid, "2026-01-10", 1)
        await create_entry(client, token, mid, "2026-01-12", 2)
        await create_entry(client, token, mid, "2026-01-14", 3)

        stats = await _metric_stats(client, token, mid)
        assert stats["total_entries"] == 3
        assert stats["total_days"] == 5
        assert stats["fill_rate"] == 60.0


# ---------------------------------------------------------------------------
# Metric-stats: privacy
# ---------------------------------------------------------------------------

class TestMetricStatsPrivacy:
    """Stats blocked for private metric when privacy mode is on."""

    async def test_private_metric_stats_blocked(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "SecretStats", "type": "number", "private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        mid = metric["id"]
        token = user_a["token"]

        await create_entry(client, token, mid, "2026-01-10", 42)
        await _enable_privacy(client, token)

        stats = await _metric_stats(client, token, mid)
        assert stats["blocked"] is True
        # Blocked response should not contain metric data fields
        assert "average" not in stats
        assert "total_entries" not in stats


# ---------------------------------------------------------------------------
# Computed metric in trends
# ---------------------------------------------------------------------------

class TestTrendsComputed:
    """Computed metric values appear in trends."""

    async def test_computed_metric_in_trends(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create a source number metric
        source = await create_metric(
            client, user_a["token"], name="Source", metric_type="number",
        )
        source_id = source["id"]
        token = user_a["token"]

        # Create a computed metric: Source * 2
        computed = await _create_computed_metric(
            client, token,
            name="Double",
            formula=[
                {"type": "metric", "id": source_id},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="float",
        )

        await create_entry(client, token, source_id, "2026-01-10", 10)
        await create_entry(client, token, source_id, "2026-01-11", 25)

        data = await _trends(client, token, computed["id"])
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 20.0
        assert values["2026-01-11"] == 50.0


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestTrendsDataIsolation:
    """user_a cannot see user_b's trends."""

    async def test_user_a_cannot_see_user_b_trends(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        # user_b creates a metric with entries
        metric = await create_metric(
            client, user_b["token"], name="Private", metric_type="number",
        )
        mid = metric["id"]
        await create_entry(client, user_b["token"], mid, "2026-01-10", 42)

        # user_a queries trends for user_b's metric
        data = await _trends(client, user_a["token"], mid)
        assert data.get("error") == "Metric not found"


class TestMetricStatsDataIsolation:
    """user_a cannot see user_b's metric-stats."""

    async def test_user_a_cannot_see_user_b_stats(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_b["token"], name="Secret", metric_type="number",
        )
        mid = metric["id"]
        await create_entry(client, user_b["token"], mid, "2026-01-10", 42)

        stats = await _metric_stats(client, user_a["token"], mid)
        assert stats.get("error") == "Metric not found"


# ---------------------------------------------------------------------------
# Trends: text
# ---------------------------------------------------------------------------

class TestTrendsText:
    """Trends for text metric — note counts per day."""

    async def test_text_trends_note_counts(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        resp = await client.post(
            "/api/metrics",
            json={"name": "Journal", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        mid = resp.json()["id"]

        # 2 notes on date1, 1 note on date2, 0 on date3
        await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-01-10", "text": "hello"},
            headers=auth_headers(token),
        )
        await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-01-10", "text": "world"},
            headers=auth_headers(token),
        )
        await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-01-11", "text": "one note"},
            headers=auth_headers(token),
        )

        data = await _trends(client, token, mid)
        assert data["metric_type"] == "text"
        values = {p["date"]: p["value"] for p in data["points"]}
        assert values["2026-01-10"] == 2
        assert values["2026-01-11"] == 1
        assert "2026-01-12" not in values


# ---------------------------------------------------------------------------
# Trends: enum
# ---------------------------------------------------------------------------

class TestTrendsEnum:
    """Trends for enum metric — per-option boolean series."""

    async def test_enum_trends_option_series(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        metric = await _create_enum_metric(client, token, name="Mood")
        mid = metric["id"]
        opts = metric["enum_options"]
        good_id = opts[0]["id"]
        bad_id = opts[1]["id"]
        meh_id = opts[2]["id"]

        # day1: Good selected, day2: Bad selected, day3: Good+Meh selected
        await create_entry(client, token, mid, "2026-01-10", [good_id])
        await create_entry(client, token, mid, "2026-01-11", [bad_id])
        await create_entry(client, token, mid, "2026-01-12", [good_id, meh_id])

        data = await _trends(client, token, mid)
        assert data["metric_type"] == "enum"
        assert len(data["options"]) == 3
        assert "option_series" in data

        good_series = {p["date"]: p["value"] for p in data["option_series"]["Good"]}
        bad_series = {p["date"]: p["value"] for p in data["option_series"]["Bad"]}
        meh_series = {p["date"]: p["value"] for p in data["option_series"]["Meh"]}

        # day1: Good=1, Bad=0, Meh=0
        assert good_series["2026-01-10"] == 1.0
        assert bad_series["2026-01-10"] == 0.0
        assert meh_series["2026-01-10"] == 0.0

        # day2: Good=0, Bad=1, Meh=0
        assert good_series["2026-01-11"] == 0.0
        assert bad_series["2026-01-11"] == 1.0

        # day3: Good=1, Meh=1
        assert good_series["2026-01-12"] == 1.0
        assert meh_series["2026-01-12"] == 1.0


# ---------------------------------------------------------------------------
# Metric-stats: text
# ---------------------------------------------------------------------------

class TestMetricStatsText:
    """Stats for text metric — note counts and fill rate."""

    async def test_text_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        resp = await client.post(
            "/api/metrics",
            json={"name": "Diary", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        mid = resp.json()["id"]

        # 2 notes on day1, 1 note on day2, 1 note on day3 = 4 total, 3 days
        for date, text in [
            ("2026-01-10", "a"), ("2026-01-10", "b"),
            ("2026-01-11", "c"), ("2026-01-12", "d"),
        ]:
            await client.post(
                "/api/notes",
                json={"metric_id": mid, "date": date, "text": text},
                headers=auth_headers(token),
            )

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_type"] == "text"
        assert stats["total_notes"] == 4
        assert stats["total_entries"] == 3  # days_with_notes
        assert stats["average_per_day"] == round(4 / 3, 1)
        assert stats["fill_rate"] == 60.0  # 3 out of 5 days
        assert "display_stats" in stats


# ---------------------------------------------------------------------------
# Metric-stats: enum
# ---------------------------------------------------------------------------

class TestMetricStatsEnum:
    """Stats for enum metric — option counts and percentages."""

    async def test_enum_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        metric = await _create_enum_metric(client, token, name="Rating")
        mid = metric["id"]
        opts = metric["enum_options"]
        good_id = opts[0]["id"]
        bad_id = opts[1]["id"]

        # 3 entries: Good, Good, Bad
        await create_entry(client, token, mid, "2026-01-10", [good_id])
        await create_entry(client, token, mid, "2026-01-11", [good_id])
        await create_entry(client, token, mid, "2026-01-12", [bad_id])

        stats = await _metric_stats(client, token, mid)
        assert stats["metric_type"] == "enum"
        assert stats["total_entries"] == 3

        option_stats = {o["label"]: o for o in stats["option_stats"]}
        assert option_stats["Good"]["count"] == 2
        assert option_stats["Bad"]["count"] == 1
        assert option_stats["Meh"]["count"] == 0
        assert option_stats["Good"]["percent"] == round(2 / 3 * 100, 1)
        assert stats["most_common"] == "Good"
        assert stats["fill_rate"] == 60.0  # 3 out of 5 days
        assert "display_stats" in stats


# ---------------------------------------------------------------------------
# Metric-stats: time
# ---------------------------------------------------------------------------

class TestMetricStatsTime:
    """Stats for time metric — average, earliest, latest in HH:MM."""

    async def test_time_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="WakeUp", metric_type="time",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 07:30 → 450min, 08:00 → 480min, 08:30 → 510min
        await create_entry(client, token, mid, "2026-01-10", "07:30")
        await create_entry(client, token, mid, "2026-01-11", "08:00")
        await create_entry(client, token, mid, "2026-01-12", "08:30")

        stats = await _metric_stats(client, token, mid)
        # average = (450+480+510)/3 = 480 → "08:00"
        assert stats["average"] == "08:00"
        assert stats["earliest"] == "07:30"
        assert stats["latest"] == "08:30"


# ---------------------------------------------------------------------------
# Metric-stats: time empty
# ---------------------------------------------------------------------------

class TestMetricStatsTimeEmpty:
    """Time metric with no entries — placeholder values."""

    async def test_time_stats_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EmptyTime", metric_type="time",
        )
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        assert stats["average"] == "--:--"
        assert stats["earliest"] == "--:--"
        assert stats["latest"] == "--:--"


# ---------------------------------------------------------------------------
# Metric-stats: duration formatted
# ---------------------------------------------------------------------------

class TestMetricStatsDurationFormatted:
    """Duration metric — values formatted as Xч Yм."""

    async def test_duration_formatted_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="DurFmt", metric_type="duration",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 150min, 90min, 60min
        await create_entry(client, token, mid, "2026-01-10", 150)
        await create_entry(client, token, mid, "2026-01-11", 90)
        await create_entry(client, token, mid, "2026-01-12", 60)

        stats = await _metric_stats(client, token, mid)
        # average = (150+90+60)/3 = 100 → "1ч 40м"
        assert stats["average"] == "1ч 40м"
        assert stats["min"] == "1ч 0м"
        assert stats["max"] == "2ч 30м"
        assert stats["median"] == "1ч 30м"


# ---------------------------------------------------------------------------
# Metric-stats: duration empty
# ---------------------------------------------------------------------------

class TestMetricStatsDurationEmpty:
    """Duration metric with no entries — zero placeholders."""

    async def test_duration_empty_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EmptyDur", metric_type="duration",
        )
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        assert stats["average"] == "0ч 0м"
        assert stats["min"] == "0ч 0м"
        assert stats["max"] == "0ч 0м"
        assert stats["median"] == "0ч 0м"


# ---------------------------------------------------------------------------
# Metric-stats: computed float
# ---------------------------------------------------------------------------

class TestMetricStatsComputedFloat:
    """Stats for computed metric with result_type=float."""

    async def test_computed_float_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        source = await create_metric(
            client, token, name="Src", metric_type="number",
        )
        src_id = source["id"]

        computed = await _create_computed_metric(
            client, token,
            name="Plus1",
            formula=[
                {"type": "metric", "id": src_id},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 1},
            ],
            result_type="float",
        )

        # source values: 10, 20, 30 → computed: 11, 21, 31
        await create_entry(client, token, src_id, "2026-01-10", 10)
        await create_entry(client, token, src_id, "2026-01-11", 20)
        await create_entry(client, token, src_id, "2026-01-12", 30)

        stats = await _metric_stats(client, token, computed["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "float"
        assert stats["average"] == 21.0
        assert stats["min"] == 11.0
        assert stats["max"] == 31.0
        assert stats["total_entries"] == 3


# ---------------------------------------------------------------------------
# Metric-stats: computed bool
# ---------------------------------------------------------------------------

class TestMetricStatsComputedBool:
    """Stats for computed metric with result_type=bool (comparison formula)."""

    async def test_computed_bool_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        source = await create_metric(
            client, token, name="SrcBool", metric_type="number",
        )
        src_id = source["id"]

        computed = await _create_computed_metric(
            client, token,
            name="IsPositive",
            formula=[
                {"type": "metric", "id": src_id},
                {"type": "op", "value": ">"},
                {"type": "number", "value": 0},
            ],
            result_type="bool",
        )

        # source: 5, 0, 10, 0 → bool: True, False, True, False
        await create_entry(client, token, src_id, "2026-01-10", 5)
        await create_entry(client, token, src_id, "2026-01-11", 0)
        await create_entry(client, token, src_id, "2026-01-12", 10)
        await create_entry(client, token, src_id, "2026-01-13", 0)

        stats = await _metric_stats(client, token, computed["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "bool"
        assert stats["yes_count"] == 2
        assert stats["no_count"] == 2
        assert stats["yes_percent"] == 50.0


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

class TestStreaks:
    """GET /api/analytics/streaks — current streak for bool metrics."""

    async def test_streak_count(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Habit", metric_type="bool",
        )
        mid = metric["id"]
        token = user_a["token"]
        # 5 consecutive True entries
        for i in range(5):
            await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", True)

        resp = await client.get(
            "/api/analytics/streaks",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        streaks = data["streaks"]
        entry = next(s for s in streaks if s["metric_id"] == mid)
        assert entry["current_streak"] == 5


# ---------------------------------------------------------------------------
# Streaks: empty
# ---------------------------------------------------------------------------

class TestStreaksEmpty:
    """No bool entries → empty streaks list."""

    async def test_no_streaks(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create a bool metric but add no entries
        await create_metric(
            client, user_a["token"], name="NoStreak", metric_type="bool",
        )

        resp = await client.get(
            "/api/analytics/streaks",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["streaks"] == []


# ---------------------------------------------------------------------------
# Streaks: privacy
# ---------------------------------------------------------------------------

class TestStreaksPrivacy:
    """Private bool metric streak masked when privacy mode is on."""

    async def test_private_streak_masked(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        resp = await client.post(
            "/api/metrics",
            json={"name": "SecretHabit", "type": "bool", "private": True},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        mid = resp.json()["id"]

        # 3 consecutive True entries
        for i in range(3):
            await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", True)

        await _enable_privacy(client, token)

        resp = await client.get(
            "/api/analytics/streaks",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        streaks = resp.json()["streaks"]
        entry = next(s for s in streaks if s["metric_id"] == mid)
        assert entry["current_streak"] == 0


# ---------------------------------------------------------------------------
# Old /correlations endpoint (lines 469-527)
# ---------------------------------------------------------------------------

class TestOldCorrelationsEndpoint:
    """Tests for the legacy GET /api/analytics/correlations endpoint."""

    async def test_correlations_two_number_metrics(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Two number metrics with 15 entries produce correlation results."""
        token = user_a["token"]
        m1 = await create_metric(client, token, name="NumA", metric_type="number")
        m2 = await create_metric(client, token, name="NumB", metric_type="number")
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, m1["id"], date_str, day * 10)
            await create_entry(client, token, m2["id"], date_str, day * 5)
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": m1["id"], "metric_b": m2["id"],
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation"] is not None
        assert data["data_points"] == 15
        assert len(data["pairs"]) == 15

    async def test_correlations_metric_not_found(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Non-existent metric returns error."""
        token = user_a["token"]
        m1 = await create_metric(client, token, name="Real", metric_type="number")
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": m1["id"], "metric_b": 999999,
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "Metric not found"

    async def test_correlations_insufficient_data(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Two metrics with only 1 entry each produce None correlation."""
        token = user_a["token"]
        m1 = await create_metric(client, token, name="Short1", metric_type="number")
        m2 = await create_metric(client, token, name="Short2", metric_type="number")
        await create_entry(client, token, m1["id"], "2026-01-10", 5)
        await create_entry(client, token, m2["id"], "2026-01-10", 10)
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": m1["id"], "metric_b": m2["id"],
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation"] is None
        assert "message" in data

    async def test_correlations_with_computed(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Number + computed (num*2) with 15 entries produces correlation."""
        token = user_a["token"]
        num = await create_metric(client, token, name="Base", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="Times2",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="float",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num["id"], date_str, day * 3)
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": num["id"], "metric_b": comp["id"],
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Perfect correlation between x and 2x
        assert data["correlation"] is not None
        assert data["correlation"] == 1.0

    async def test_correlations_computed_as_metric_b(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metric as metric_b (reversed order covers lines 503-506)."""
        token = user_a["token"]
        num = await create_metric(client, token, name="BaseR", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="DblR",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 3},
            ],
            result_type="float",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num["id"], date_str, day * 2)
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": comp["id"], "metric_b": num["id"],
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation"] is not None
        assert data["correlation"] == 1.0

    async def test_correlations_both_computed(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Both metrics computed covers lines 496-499 and 503-506."""
        token = user_a["token"]
        num = await create_metric(client, token, name="SrcBC", metric_type="number")
        comp_a = await _create_computed_metric(
            client, token,
            name="CompA",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 1},
            ],
            result_type="float",
        )
        comp_b = await _create_computed_metric(
            client, token,
            name="CompB",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="float",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num["id"], date_str, day * 5)
        resp = await client.get(
            "/api/analytics/correlations",
            params={
                "metric_a": comp_a["id"], "metric_b": comp_b["id"],
                "start": "2026-01-01", "end": "2026-01-31",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correlation"] is not None


# ---------------------------------------------------------------------------
# Computed metric stats: duration and int result types (lines 582-598)
# ---------------------------------------------------------------------------

class TestMetricStatsComputedTimeDuration:
    """Stats for computed metrics with time and duration result types."""

    async def test_computed_duration_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed result_type=duration formats stats as Xh Ym."""
        token = user_a["token"]
        num = await create_metric(client, token, name="Mins", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="DoubleMins",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="duration",
        )
        # 60, 90, 120 -> doubled: 120, 180, 240 (avg 180 = 3h 0m)
        await create_entry(client, token, num["id"], "2026-01-10", 60)
        await create_entry(client, token, num["id"], "2026-01-11", 90)
        await create_entry(client, token, num["id"], "2026-01-12", 120)

        stats = await _metric_stats(client, token, comp["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "duration"
        # Check duration formatting
        assert "ч" in stats["average"]
        assert "м" in stats["average"]

    async def test_computed_int_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed result_type=int returns numeric stats."""
        token = user_a["token"]
        num = await create_metric(client, token, name="NumSrc", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="PlusOne",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 1},
            ],
            result_type="int",
        )
        await create_entry(client, token, num["id"], "2026-01-10", 10)
        await create_entry(client, token, num["id"], "2026-01-11", 20)
        await create_entry(client, token, num["id"], "2026-01-12", 30)

        stats = await _metric_stats(client, token, comp["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "int"
        assert stats["average"] == 21.0
        assert stats["min"] == 11.0
        assert stats["max"] == 31.0


# ---------------------------------------------------------------------------
# display_stats verification (lines 796-825)
# ---------------------------------------------------------------------------

class TestDisplayStatsVerification:
    """Verify display_stats content for each metric type."""

    async def test_display_stats_scale_has_percent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Scale metric display_stats includes 'Среднее' with '%' suffix."""
        metric = await create_metric(
            client, user_a["token"], name="ScaleDisp", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-10", 3)
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Среднее" in labels
        assert "%" in labels["Среднее"]

    async def test_display_stats_number_has_range(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Number metric display_stats includes 'Диапазон'."""
        metric = await create_metric(
            client, user_a["token"], name="NumDisp", metric_type="number",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-10", 10)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-11", 50)
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Диапазон" in labels
        assert "Среднее" in labels

    async def test_display_stats_enum_has_most_common(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum metric display_stats includes 'Частый'."""
        token = user_a["token"]
        metric = await _create_enum_metric(client, token, name="EnumDisp")
        opts = metric["enum_options"]
        await create_entry(client, token, metric["id"], "2026-01-10", [opts[0]["id"]])
        await create_entry(client, token, metric["id"], "2026-01-11", [opts[0]["id"]])
        stats = await _metric_stats(client, token, metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Частый" in labels

    async def test_display_stats_text_has_avg_per_day(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Text metric display_stats includes 'Среднее/день'."""
        token = user_a["token"]
        resp = await client.post(
            "/api/metrics",
            json={"name": "TextDisp", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        mid = resp.json()["id"]
        await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-01-10", "text": "note1"},
            headers=auth_headers(token),
        )
        stats = await _metric_stats(client, token, mid)
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Среднее/день" in labels

    async def test_display_stats_duration_has_average(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Duration metric display_stats includes 'Среднее'."""
        metric = await create_metric(
            client, user_a["token"], name="DurDisp", metric_type="duration",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-10", 120)
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Среднее" in labels

    async def test_display_stats_bool_has_yes_percent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric display_stats includes 'Да' with '%'."""
        metric = await create_metric(
            client, user_a["token"], name="BoolDisp", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-10", True)
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Да" in labels
        assert "%" in labels["Да"]

    async def test_display_stats_time_has_average(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Time metric display_stats includes 'Среднее'."""
        metric = await create_metric(
            client, user_a["token"], name="TimeDisp", metric_type="time",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-10", "08:00")
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        labels = {d["label"]: d["value"] for d in stats["display_stats"]}
        assert "Среднее" in labels


# ---------------------------------------------------------------------------
# Computed metric trends: time and duration result types
# ---------------------------------------------------------------------------

class TestTrendsComputedTimeDuration:
    """Computed metrics with time/duration result_type in trends."""

    async def test_computed_time_trends(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metric with result_type=time produces time-based points."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MinsT", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="TimeComp",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 0},
            ],
            result_type="time",
        )
        # 450 minutes = 07:30, 480 minutes = 08:00
        await create_entry(client, token, num["id"], "2026-01-10", 450)
        await create_entry(client, token, num["id"], "2026-01-11", 480)

        data = await _trends(client, token, comp["id"])
        assert len(data["points"]) == 2

    async def test_computed_duration_trends(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metric with result_type=duration produces values."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MinsDur", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="DurComp",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="duration",
        )
        await create_entry(client, token, num["id"], "2026-01-10", 60)
        await create_entry(client, token, num["id"], "2026-01-11", 90)

        data = await _trends(client, token, comp["id"])
        assert len(data["points"]) == 2


# ---------------------------------------------------------------------------
# Computed metric stats with time result type (line 582-584)
# ---------------------------------------------------------------------------

class TestMetricStatsComputedTime:
    """Stats for computed metric with result_type=time."""

    async def test_computed_time_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed time metric stats have average/earliest/latest in HH:MM."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MinsS", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="TimeSt",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 0},
            ],
            result_type="time",
        )
        # 450, 480, 510 minutes -> 07:30, 08:00, 08:30
        await create_entry(client, token, num["id"], "2026-01-10", 450)
        await create_entry(client, token, num["id"], "2026-01-11", 480)
        await create_entry(client, token, num["id"], "2026-01-12", 510)

        stats = await _metric_stats(client, token, comp["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "time"
        assert stats["average"] == "08:00"
        assert stats["earliest"] == "07:30"
        assert stats["latest"] == "08:30"

    async def test_computed_time_stats_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed time metric with no data has no average/earliest/latest."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MinsE", metric_type="number")
        comp = await _create_computed_metric(
            client, token,
            name="TimeE",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 0},
            ],
            result_type="time",
        )
        stats = await _metric_stats(client, token, comp["id"])
        assert stats["metric_type"] == "computed"
        assert stats["result_type"] == "time"
        assert stats["total_entries"] == 0
        assert "average" not in stats


# ---------------------------------------------------------------------------
# Computed metric stats: empty computed (no data, various result types)
# ---------------------------------------------------------------------------

class TestMetricStatsComputedEmpty:
    """Empty computed metrics: no data means no numeric stats fields."""

    async def test_computed_duration_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Empty computed duration has no stats."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MDE", metric_type="number")
        comp = await _create_computed_metric(
            client, token, name="DurE",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "*"},
                {"type": "number", "value": 2},
            ],
            result_type="duration",
        )
        stats = await _metric_stats(client, token, comp["id"])
        assert stats["total_entries"] == 0
        assert "average" not in stats

    async def test_computed_float_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Empty computed float has no stats."""
        token = user_a["token"]
        num = await create_metric(client, token, name="MFE", metric_type="number")
        comp = await _create_computed_metric(
            client, token, name="FloatE",
            formula=[
                {"type": "metric", "id": num["id"]},
                {"type": "op", "value": "+"},
                {"type": "number", "value": 0},
            ],
            result_type="float",
        )
        stats = await _metric_stats(client, token, comp["id"])
        assert stats["total_entries"] == 0
        assert "average" not in stats


# ---------------------------------------------------------------------------
# Streaks: bool metric with no current streak (line 1614)
# ---------------------------------------------------------------------------

class TestStreaksNoCurrent:
    """Bool metric where most recent entries are False -> no streak listed."""

    async def test_no_current_streak_excluded_from_list(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A bool metric with last entry False has 0 current streak -> excluded."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="NoStrk", metric_type="bool",
        )
        mid = metric["id"]
        # Pattern: True, True, False -> current streak = 0
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", True)
        await create_entry(client, token, mid, "2026-01-12", False)

        resp = await client.get(
            "/api/analytics/streaks",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        streaks = resp.json()["streaks"]
        # Should NOT be in the list (current_streak=0 -> excluded)
        matching = [s for s in streaks if s["metric_id"] == mid]
        assert len(matching) == 0


# ---------------------------------------------------------------------------
# Scale metric stats: empty (line 787)
# ---------------------------------------------------------------------------

class TestMetricStatsScaleEmpty:
    """Scale metric with no entries returns zero stats."""

    async def test_scale_empty_stats(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EmptyScale", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        stats = await _metric_stats(client, user_a["token"], metric["id"])
        assert stats["average"] == 0
        assert stats["min"] == 0
        assert stats["max"] == 0
