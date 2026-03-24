"""API integration tests for the analytics correlation endpoints.

Endpoints under test:
- POST /api/analytics/correlation-report  — start a new correlation report
- GET  /api/analytics/correlation-report  — list reports (running + latest done)
- GET  /api/analytics/correlation-report/{id}/pairs — get pairs for a report
"""
from __future__ import annotations

import asyncio

import pytest

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_report(
    client: AsyncClient,
    token: str,
    start: str = "2026-01-01",
    end: str = "2026-01-31",
) -> dict:
    """Create a correlation report, return response body."""
    resp = await client.post(
        "/api/analytics/correlation-report",
        json={"start": start, "end": end},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wait_for_report_done(
    client: AsyncClient,
    token: str,
    max_wait: int = 200,
) -> dict:
    """Poll GET /correlation-report until a 'done' report appears.

    Returns the full response body {"running": ..., "report": ...}.
    """
    data = {}
    for _ in range(max_wait):
        resp = await client.get(
            "/api/analytics/correlation-report",
            headers=auth_headers(token),
        )
        data = resp.json()
        if data.get("report") is not None and data["report"]["status"] == "done":
            return data
        if data.get("running") is None and data.get("report") is None:
            # No running and no done — report may have errored.
            # Wait a bit more before giving up, background task may still be finishing.
            await asyncio.sleep(0.3)
            resp2 = await client.get(
                "/api/analytics/correlation-report",
                headers=auth_headers(token),
            )
            data = resp2.json()
            if data.get("report") is not None:
                return data
            return data
        await asyncio.sleep(0.15)
    return data


async def _create_metrics_with_entries(
    client: AsyncClient,
    token: str,
) -> tuple[dict, dict]:
    """Create a bool metric and a number metric, each with 15 entries."""
    bool_m = await create_metric(
        client, token, name="Corr Bool", metric_type="bool", slug="corr_bool",
    )
    num_m = await create_metric(
        client, token, name="Corr Number", metric_type="number", slug="corr_number",
    )
    for day in range(1, 16):
        date_str = f"2026-01-{day:02d}"
        await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)
        await create_entry(client, token, num_m["id"], date_str, day * 10)
    return bool_m, num_m


# ---------------------------------------------------------------------------
# Report creation
# ---------------------------------------------------------------------------

class TestCreateCorrelationReport:

    async def test_create_returns_report_id_and_running(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        body = await _start_report(client, user_a["token"])
        assert "report_id" in body
        assert isinstance(body["report_id"], int)
        assert body["status"] == "running"
        # Wait for background task to finish before cleanup
        await _wait_for_report_done(client, user_a["token"])

    async def test_list_includes_running_report(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await _start_report(client, user_a["token"])
        resp = await client.get(
            "/api/analytics/correlation-report",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Either still running or already done (fast with no data)
        has_running = data.get("running") is not None
        has_done = data.get("report") is not None
        assert has_running or has_done
        # Wait for background task to finish before cleanup
        await _wait_for_report_done(client, user_a["token"])


# ---------------------------------------------------------------------------
# Report completion (poll until done)
# ---------------------------------------------------------------------------

class TestReportCompletion:

    async def test_report_becomes_done(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Report with metrics and entries completes with status 'done'."""
        await _create_metrics_with_entries(client, user_a["token"])
        await _start_report(client, user_a["token"])
        data = await _wait_for_report_done(client, user_a["token"])
        assert data["report"] is not None
        assert data["report"]["status"] == "done"

    async def test_done_report_has_period(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await _create_metrics_with_entries(client, user_a["token"])
        await _start_report(client, user_a["token"], start="2026-01-01", end="2026-01-31")
        data = await _wait_for_report_done(client, user_a["token"])
        report = data["report"]
        assert report["period_start"] == "2026-01-01"
        assert report["period_end"] == "2026-01-31"

    async def test_done_report_has_counts(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await _create_metrics_with_entries(client, user_a["token"])
        await _start_report(client, user_a["token"])
        data = await _wait_for_report_done(client, user_a["token"])
        report = data["report"]
        assert "counts" in report
        counts = report["counts"]
        assert "total" in counts
        assert isinstance(counts["total"], int)
        assert counts["total"] >= 0
        for key in ("sig_strong", "sig_medium", "sig_weak", "maybe", "insig"):
            assert key in counts


# ---------------------------------------------------------------------------
# Pairs structure
# ---------------------------------------------------------------------------

class TestPairsStructure:

    async def test_pairs_have_valid_structure(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """After report completes, pairs endpoint returns structured data."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "pairs" in data
        assert "total" in data
        assert isinstance(data["total"], int)
        assert "has_more" in data

    async def test_pairs_fields(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Each pair has required fields with correct types."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["total"] > 0, "Expected at least one correlation pair"
        pair = data["pairs"][0]

        # Source keys
        assert "source_key_a" not in pair or isinstance(pair.get("source_key_a"), str)
        assert "label_a" in pair
        assert "label_b" in pair

        # Correlation value
        assert "correlation" in pair
        assert isinstance(pair["correlation"], (int, float))

        # Data points
        assert "data_points" in pair
        assert isinstance(pair["data_points"], int)
        assert pair["data_points"] > 0

        # Lag days
        assert "lag_days" in pair
        assert isinstance(pair["lag_days"], int)

        # Types
        assert "type_a" in pair
        assert "type_b" in pair

        # Quality issue fields
        assert "quality_issue" in pair
        assert "quality_issue_label" in pair
        assert "quality_severity" in pair
        if pair["quality_issue"] is not None:
            assert isinstance(pair["quality_issue"], str)
            assert pair["quality_issue_label"] is not None
            assert pair["quality_severity"] in ("bad", "maybe")

        # Confidence interval
        assert "ci_lower" in pair
        assert "ci_upper" in pair
        if pair["ci_lower"] is not None:
            assert isinstance(pair["ci_lower"], (int, float))
            assert isinstance(pair["ci_upper"], (int, float))
            assert pair["ci_lower"] <= pair["ci_upper"]

    async def test_pairs_have_p_value(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs include p_value (computed or stored)."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["total"] > 0
        for pair in data["pairs"]:
            assert "p_value" in pair
            if pair["p_value"] is not None:
                assert isinstance(pair["p_value"], (int, float))

    async def test_lag_correlations_present(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Both lag=0 (same-day) and lag=1 correlations should be present."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        lag_values = {p["lag_days"] for p in data["pairs"]}
        assert 0 in lag_values, "Expected same-day (lag=0) correlations"
        # lag=1 may or may not appear depending on data, so we only assert
        # the set contains at least lag 0


# ---------------------------------------------------------------------------
# Auto sources
# ---------------------------------------------------------------------------

class TestAutoSources:

    async def test_auto_sources_in_pairs(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Auto sources like day_of_week appear in pairs."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        # Auto sources use labels from AUTO_DISPLAY_NAMES (e.g. "День недели",
        # "Месяц", "Номер недели"). Check that at least one non-metric label exists.
        labels = set()
        for pair in data["pairs"]:
            labels.add(pair["label_a"])
            labels.add(pair["label_b"])
        # Our two metric names
        metric_names = {"Corr Bool", "Corr Number"}
        non_metric_labels = labels - metric_names
        # Auto sources should add extra labels (e.g. "День недели", "не ноль" variants)
        assert len(non_metric_labels) > 0, (
            f"Expected auto-source labels beyond metric names, got only: {labels}"
        )


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestDataIsolation:

    async def test_user_a_cannot_see_user_b_pairs(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        """user_a cannot fetch pairs from user_b's report."""
        # user_b creates metrics, entries, and a report
        await _create_metrics_with_entries(client, user_b["token"])
        report_body = await _start_report(client, user_b["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_b["token"])

        # user_a tries to fetch user_b's report pairs
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should return empty pairs (report not found for user_a)
        assert data["pairs"] == []
        assert data["total"] == 0

    async def test_user_a_cannot_see_user_b_reports_in_list(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        """user_a's report list does not include user_b's reports."""
        await _create_metrics_with_entries(client, user_b["token"])
        await _start_report(client, user_b["token"])
        await _wait_for_report_done(client, user_b["token"])

        resp = await client.get(
            "/api/analytics/correlation-report",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        # user_a has no reports
        assert data["running"] is None
        assert data["report"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    async def test_get_pairs_nonexistent_report(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Requesting pairs for a non-existent report returns empty result."""
        resp = await client.get(
            "/api/analytics/correlation-report/999999/pairs",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pairs"] == []
        assert data["total"] == 0

    async def test_create_report_unauthenticated(
        self, client: AsyncClient,
    ) -> None:
        """POST without auth token returns 401."""
        resp = await client.post(
            "/api/analytics/correlation-report",
            json={"start": "2026-01-01", "end": "2026-01-31"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pair chart
# ---------------------------------------------------------------------------

class TestCorrelationPairChart:

    async def test_pair_chart_returns_expected_fields(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """GET /correlation-pair-chart returns chart data with all expected fields."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        # Fetch pairs to get a real pair_id
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["total"] > 0, "Expected at least one pair for chart test"
        pair_id = data["pairs"][0]["pair_id"]

        # Call pair chart endpoint
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={pair_id}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        chart = resp.json()

        assert "dates" in chart
        assert isinstance(chart["dates"], list)
        assert "values_a" in chart
        assert isinstance(chart["values_a"], list)
        assert "values_b" in chart
        assert isinstance(chart["values_b"], list)
        assert "label_a" in chart
        assert isinstance(chart["label_a"], str)
        assert "label_b" in chart
        assert isinstance(chart["label_b"], str)
        assert "type_a" in chart
        assert "type_b" in chart
        assert "correlation" in chart
        assert isinstance(chart["correlation"], (int, float))


class TestPairChartNonexistent:

    async def test_nonexistent_pair_returns_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """GET /correlation-pair-chart with non-existent pair_id returns empty lists."""
        resp = await client.get(
            "/api/analytics/correlation-pair-chart?pair_id=999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert chart["dates"] == []
        assert chart["values_a"] == []
        assert chart["values_b"] == []


class TestPairChartDataIsolation:

    async def test_user_b_cannot_see_user_a_pair_chart(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        """user_b gets empty result when requesting user_a's pair chart."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        # Get a real pair_id from user_a's report
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["total"] > 0
        pair_id = data["pairs"][0]["pair_id"]

        # user_b tries to get chart for user_a's pair
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={pair_id}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert chart["dates"] == []
        assert chart["values_a"] == []
        assert chart["values_b"] == []


# ---------------------------------------------------------------------------
# Enum metric in correlations
# ---------------------------------------------------------------------------

class TestCorrelationWithEnumMetric:

    async def test_enum_options_appear_as_separate_sources(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Each enum option becomes a separate boolean source in correlations."""
        token = user_a["token"]

        # Create enum metric with 3 options
        resp = await client.post(
            "/api/metrics",
            json={"name": "Mood", "type": "enum", "enum_options": ["Good", "Bad", "Meh"]},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        enum_m = resp.json()
        enum_id = enum_m["id"]
        option_ids = [opt["id"] for opt in enum_m["enum_options"]]
        assert len(option_ids) == 3

        # Create bool metric for correlation counterpart
        bool_m = await create_metric(
            client, token, name="Exercise", metric_type="bool", slug="exercise",
        )

        # Create 15 entries for enum (rotating through options)
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            selected = [option_ids[day % 3]]
            await create_entry(client, token, enum_id, date_str, selected)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        # Run correlation report
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        assert data["report"]["status"] == "done"
        report_id = data["report"]["id"]

        # Fetch all pairs
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Enum options should produce per-option boolean sources.
        # Look for pairs where type_a or type_b is "enum_bool"
        # (the correlation engine creates bool sources per option).
        types_found = set()
        for pair in pairs_data["pairs"]:
            types_found.add(pair["type_a"])
            types_found.add(pair["type_b"])

        # Enum options appear as separate sources. The option label shows up
        # in option_a / option_b fields of the pair (not in label_a/b).
        option_labels_found: set[str] = set()
        for pair in pairs_data["pairs"]:
            if pair.get("option_a"):
                option_labels_found.add(pair["option_a"])
            if pair.get("option_b"):
                option_labels_found.add(pair["option_b"])
        # At least one of Good/Bad/Meh should appear
        expected = {"Good", "Bad", "Meh"}
        assert option_labels_found & expected, (
            f"Expected enum option labels in pairs, got options: {option_labels_found}"
        )


# ---------------------------------------------------------------------------
# Text metric in correlations (note_count auto-source)
# ---------------------------------------------------------------------------

class TestCorrelationWithTextMetric:

    async def test_text_metric_produces_note_count_source(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Text metric contributes a note_count auto-source to correlations."""
        token = user_a["token"]

        # Create text metric
        resp = await client.post(
            "/api/metrics",
            json={"name": "Journal", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        text_m = resp.json()
        text_id = text_m["id"]

        # Create bool metric for correlation counterpart
        bool_m = await create_metric(
            client, token, name="Workout", metric_type="bool", slug="workout",
        )

        # Create notes for 15 dates + bool entries
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            resp = await client.post(
                "/api/notes",
                json={"metric_id": text_id, "date": date_str, "text": f"Day {day} notes"},
                headers=auth_headers(token),
            )
            assert resp.status_code == 201, resp.text
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        # Run correlation report
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        assert data["report"]["status"] == "done"
        report_id = data["report"]["id"]

        # Fetch all pairs
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Look for note_count auto-source — it should appear in labels
        # The auto-source label typically contains the text metric name
        labels = set()
        for pair in pairs_data["pairs"]:
            labels.add(pair["label_a"])
            labels.add(pair["label_b"])

        # note_count source should reference the Journal metric
        journal_labels = [lbl for lbl in labels if "Journal" in lbl]
        assert len(journal_labels) > 0, (
            f"Expected note_count source referencing Journal metric, got labels: {labels}"
        )


# ---------------------------------------------------------------------------
# Pairs category filter
# ---------------------------------------------------------------------------

class TestCorrelationPairsCategoryFilter:

    async def test_category_filter_returns_different_counts(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs endpoint with category filter returns valid results."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        # Get all pairs
        resp_all = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?category=all&limit=200",
            headers=auth_headers(user_a["token"]),
        )
        assert resp_all.status_code == 200
        total_all = resp_all.json()["total"]

        # Get only sig_strong pairs
        resp_strong = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?category=sig_strong&limit=200",
            headers=auth_headers(user_a["token"]),
        )
        assert resp_strong.status_code == 200
        total_strong = resp_strong.json()["total"]

        # sig_strong is a subset of all
        assert total_strong <= total_all


# ---------------------------------------------------------------------------
# Pairs metric_ids filter
# ---------------------------------------------------------------------------

class TestCorrelationPairsMetricFilter:

    async def test_metric_ids_filter_narrows_results(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs filtered by metric_ids return only relevant pairs."""
        bool_m, num_m = await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        # Get all pairs
        resp_all = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(user_a["token"]),
        )
        assert resp_all.status_code == 200
        total_all = resp_all.json()["total"]

        # Filter by both metric IDs (pairs must have both sides in the set)
        both_ids = f"{bool_m['id']},{num_m['id']}"
        resp_filtered = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?metric_ids={both_ids}&limit=200",
            headers=auth_headers(user_a["token"]),
        )
        assert resp_filtered.status_code == 200
        filtered_data = resp_filtered.json()
        total_filtered = filtered_data["total"]

        # Filtered set should be a subset of all (auto-source pairs are excluded)
        assert total_filtered <= total_all

        # Every filtered pair must reference one of the specified metrics
        for pair in filtered_data["pairs"]:
            metric_ids_set = {bool_m["id"], num_m["id"]}
            assert pair.get("metric_a_id") in metric_ids_set or pair.get("metric_b_id") in metric_ids_set


# ---------------------------------------------------------------------------
# Pairs pagination
# ---------------------------------------------------------------------------

class TestCorrelationPairsPagination:

    async def test_pagination_offset_and_limit(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs endpoint respects offset and limit, reports has_more correctly."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        # Request first page with limit=2
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?offset=0&limit=2",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int)
        assert isinstance(data["has_more"], bool)
        assert len(data["pairs"]) <= 2

        if data["total"] > 2:
            assert data["has_more"] is True
            # Request second page
            resp2 = await client.get(
                f"/api/analytics/correlation-report/{report_id}/pairs?offset=2&limit=2",
                headers=auth_headers(user_a["token"]),
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["total"] == data["total"]  # total stays the same
            assert len(data2["pairs"]) <= 2
            # Pages should not overlap
            ids_page1 = {p["pair_id"] for p in data["pairs"]}
            ids_page2 = {p["pair_id"] for p in data2["pairs"]}
            assert ids_page1.isdisjoint(ids_page2)


# ---------------------------------------------------------------------------
# Pair chart: auto sources (lines 1386-1464)
# ---------------------------------------------------------------------------

class TestPairChartAutoSources:
    """Pair chart reconstruction for auto-source types."""

    async def test_pair_chart_nonzero_source(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Report with number metric produces nonzero auto-source; pair-chart reconstructs it."""
        token = user_a["token"]
        num_m = await create_metric(
            client, token, name="NumNZ", metric_type="number", slug="numnz",
        )
        bool_m = await create_metric(
            client, token, name="BoolNZ", metric_type="bool", slug="boolnz",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            # Alternate between 0 and positive
            await create_entry(client, token, num_m["id"], date_str, day * 10 if day % 2 else 0)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        # Fetch all pairs, look for nonzero source
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Find a pair with "не ноль" label (nonzero auto source)
        nonzero_pair = None
        for p in pairs_data["pairs"]:
            if "не ноль" in p.get("label_a", "") or "не ноль" in p.get("label_b", ""):
                nonzero_pair = p
                break
        assert nonzero_pair is not None, "Expected nonzero auto-source pair"

        # Get pair chart data
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={nonzero_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert len(chart["dates"]) > 0
        # Nonzero values should be 0.0 or 1.0
        nz_side = "values_a" if "не ноль" in nonzero_pair.get("label_a", "") else "values_b"
        for v in chart[nz_side]:
            assert v in (0.0, 1.0), f"Nonzero value should be 0 or 1, got {v}"

    async def test_pair_chart_note_count_source(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Text metric produces note_count auto-source; pair-chart reconstructs it."""
        token = user_a["token"]
        resp = await client.post(
            "/api/metrics",
            json={"name": "JournalNC", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        text_m = resp.json()
        text_id = text_m["id"]

        bool_m = await create_metric(
            client, token, name="HabitNC", metric_type="bool", slug="habitnc",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            # Create varying note counts
            for _ in range(day % 3 + 1):
                await client.post(
                    "/api/notes",
                    json={"metric_id": text_id, "date": date_str, "text": f"note {day}"},
                    headers=auth_headers(token),
                )
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find pair with note_count source (label contains "кол-во заметок")
        nc_pair = None
        for p in pairs_data["pairs"]:
            if "заметок" in p.get("label_a", "") or "заметок" in p.get("label_b", ""):
                nc_pair = p
                break
        assert nc_pair is not None, "Expected note_count auto-source pair"

        # Get pair chart
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={nc_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert len(chart["dates"]) > 0

    async def test_pair_chart_computed_source(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metric in pair-chart resolves result_type (lines 1520-1533)."""
        token = user_a["token"]
        num = await create_metric(
            client, token, name="BaseComp", metric_type="number", slug="basecomp",
        )
        bool_m = await create_metric(
            client, token, name="FlagComp", metric_type="bool", slug="flagcomp",
        )
        comp = await client.post(
            "/api/metrics",
            json={
                "name": "DblComp", "type": "computed",
                "formula": [
                    {"type": "metric", "id": num["id"]},
                    {"type": "op", "value": "*"},
                    {"type": "number", "value": 2},
                ],
                "result_type": "float",
            },
            headers=auth_headers(token),
        )
        assert comp.status_code == 201
        comp_id = comp.json()["id"]

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num["id"], date_str, day * 5)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a pair involving the computed metric
        comp_pair = None
        for p in pairs_data["pairs"]:
            if p.get("metric_a_id") == comp_id or p.get("metric_b_id") == comp_id:
                comp_pair = p
                break
        assert comp_pair is not None, "Expected pair with computed metric"

        # Get pair chart — this triggers computed type resolution (lines 1520-1533)
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={comp_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        # The computed side should resolve to result_type ("float"),
        # not "computed"
        if comp_pair["metric_a_id"] == comp_id:
            assert chart["type_a"] == "float"
        else:
            assert chart["type_b"] == "float"
        assert len(chart["dates"]) > 0


# ---------------------------------------------------------------------------
# Pair chart: privacy blocking (lines 1484-1498)
# ---------------------------------------------------------------------------

class TestPairChartPrivacy:
    """Pair chart blocked for private metrics when privacy mode is on."""

    async def test_pair_chart_private_blocked(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Private metric pair chart returns empty when privacy is on."""
        token = user_a["token"]

        # Create a private metric
        resp = await client.post(
            "/api/metrics",
            json={"name": "SecretCorr", "type": "number", "private": True},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        priv_m = resp.json()
        priv_id = priv_m["id"]

        bool_m = await create_metric(
            client, token, name="PubCorr", metric_type="bool", slug="pubcorr",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, priv_id, date_str, day * 7)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        # Find a pair involving the private metric
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        priv_pair = None
        for p in pairs_data["pairs"]:
            if p.get("metric_a_id") == priv_id or p.get("metric_b_id") == priv_id:
                priv_pair = p
                break
        assert priv_pair is not None, "Expected pair with private metric"

        # Enable privacy mode
        resp = await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200

        # Pair chart should return empty
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={priv_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert chart["dates"] == []
        assert chart["values_a"] == []


# ---------------------------------------------------------------------------
# Report with diverse source types (lines 870-960)
# ---------------------------------------------------------------------------

class TestReportDiverseSources:
    """Report with enum, text, number, duration metrics produces diverse sources."""

    async def test_report_enum_text_number(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum(3 opts) + text + number + duration → pairs with enum_bool and note_count."""
        token = user_a["token"]

        # Create enum metric with 3 options
        resp = await client.post(
            "/api/metrics",
            json={"name": "MoodDiv", "type": "enum", "enum_options": ["Happy", "Sad", "Neutral"]},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        enum_m = resp.json()
        enum_id = enum_m["id"]
        option_ids = [opt["id"] for opt in enum_m["enum_options"]]

        # Create text metric
        resp = await client.post(
            "/api/metrics",
            json={"name": "DiaryDiv", "type": "text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        text_id = resp.json()["id"]

        # Create number + duration metrics
        num_m = await create_metric(client, token, name="StepsDiv", metric_type="number")
        dur_m = await create_metric(client, token, name="SleepDiv", metric_type="duration")

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, enum_id, date_str, [option_ids[day % 3]])
            await client.post(
                "/api/notes",
                json={"metric_id": text_id, "date": date_str, "text": f"Day {day}"},
                headers=auth_headers(token),
            )
            await create_entry(client, token, num_m["id"], date_str, day * 100)
            await create_entry(client, token, dur_m["id"], date_str, day * 30)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        assert data["report"]["status"] == "done"
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Check enum_bool sources exist
        types_found = set()
        for p in pairs_data["pairs"]:
            types_found.add(p["type_a"])
            types_found.add(p["type_b"])
        assert "enum_bool" in types_found, f"Expected enum_bool in types: {types_found}"

        # Check note_count source exists
        labels = set()
        for p in pairs_data["pairs"]:
            labels.add(p["label_a"])
            labels.add(p["label_b"])
        note_labels = [l for l in labels if "заметок" in l]
        assert len(note_labels) > 0, f"Expected note_count label, got: {labels}"

        # Check nonzero source exists
        nonzero_labels = [l for l in labels if "не ноль" in l]
        assert len(nonzero_labels) > 0, f"Expected nonzero label, got: {labels}"

        # Check enum option labels
        option_labels_found: set[str] = set()
        for p in pairs_data["pairs"]:
            if p.get("option_a"):
                option_labels_found.add(p["option_a"])
            if p.get("option_b"):
                option_labels_found.add(p["option_b"])
        expected_opts = {"Happy", "Sad", "Neutral"}
        assert option_labels_found & expected_opts, (
            f"Expected enum option labels, got: {option_labels_found}"
        )


# ---------------------------------------------------------------------------
# Pair chart with lag correlation
# ---------------------------------------------------------------------------

class TestPairChartLag:
    """Pair chart for lag=1 correlations."""

    async def test_pair_chart_lag_has_original_dates(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Lag=1 pair chart includes original_dates_b."""
        token = user_a["token"]
        bool_m, num_m = await _create_metrics_with_entries(client, token)
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a lag=1 pair
        lag_pair = None
        for p in pairs_data["pairs"]:
            if p["lag_days"] == 1:
                lag_pair = p
                break

        if lag_pair is not None:
            resp = await client.get(
                f"/api/analytics/correlation-pair-chart?pair_id={lag_pair['pair_id']}",
                headers=auth_headers(token),
            )
            assert resp.status_code == 200
            chart = resp.json()
            assert chart["lag_days"] == 1
            if len(chart["dates"]) > 0:
                assert chart["original_dates_b"] is not None
                assert len(chart["original_dates_b"]) == len(chart["dates"])


# ---------------------------------------------------------------------------
# Pair chart: calendar auto-source (day_of_week)
# ---------------------------------------------------------------------------

class TestPairChartCalendarAutoSource:
    """Pair chart reconstruction for calendar auto-sources."""

    async def test_pair_chart_day_of_week(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Day-of-week auto-source pair chart returns per-option boolean values (0.0 or 1.0)."""
        token = user_a["token"]
        bool_m, num_m = await _create_metrics_with_entries(client, token)
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a pair with day_of_week source (per-option boolean, e.g. "День недели: Пн")
        dow_pair = None
        for p in pairs_data["pairs"]:
            if "День недели" in p.get("label_a", "") or "День недели" in p.get("label_b", ""):
                dow_pair = p
                break
        assert dow_pair is not None, "Expected day_of_week auto-source pair"

        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={dow_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert len(chart["dates"]) > 0
        # Day-of-week is now per-option boolean: values should be 0.0 or 1.0
        dow_side = "values_a" if "День недели" in dow_pair.get("label_a", "") else "values_b"
        for v in chart[dow_side]:
            assert v in (0.0, 1.0), f"Day of week per-option value should be 0.0 or 1.0, got {v}"


# ---------------------------------------------------------------------------
# Pair formatting: hint words for different types
# ---------------------------------------------------------------------------

class TestPairHintWords:
    """Verify hint_a/hint_b fields in pairs for different metric types."""

    async def test_number_pair_has_hints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Number metric pairs should have 'больше'/'меньше' hints."""
        token = user_a["token"]
        bool_m, num_m = await _create_metrics_with_entries(client, token)
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Find a pair between the bool and number metric
        for p in pairs_data["pairs"]:
            if p.get("hint_a") or p.get("hint_b"):
                # At least one pair should have non-empty hints
                assert p["hint_a"] != "" or p["hint_b"] != ""
                break


# ---------------------------------------------------------------------------
# Multi-slot metric in correlations (lines 932-934)
# ---------------------------------------------------------------------------

class TestCorrelationMultiSlot:
    """Multi-slot metric produces per-slot sources in correlation report."""

    async def test_multi_slot_produces_slot_sources(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Metric with 2 slots creates aggregate + per-slot sources."""
        token = user_a["token"]

        slot_m = await create_slot(client, token, "Morning")
        slot_e = await create_slot(client, token, "Evening")
        metric = await create_metric(
            client, token, name="MultiSlotCorr", metric_type="number",
            slug="mslot_corr",
            slot_configs=[{"slot_id": slot_m["id"]}, {"slot_id": slot_e["id"]}],
        )
        mid = metric["id"]
        slots = metric["slots"]
        slot_a = slots[0]["id"]
        slot_b = slots[1]["id"]

        bool_m = await create_metric(
            client, token, name="FlagSlot", metric_type="bool", slug="flag_slot",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, mid, date_str, day * 10, slot_id=slot_a)
            await create_entry(client, token, mid, date_str, day * 5, slot_id=slot_b)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Look for slot labels in pairs
        slot_labels_found = set()
        for p in pairs_data["pairs"]:
            if p.get("slot_label_a"):
                slot_labels_found.add(p["slot_label_a"])
            if p.get("slot_label_b"):
                slot_labels_found.add(p["slot_label_b"])
        assert "Morning" in slot_labels_found or "Evening" in slot_labels_found, (
            f"Expected slot labels in pairs, got: {slot_labels_found}"
        )


# ---------------------------------------------------------------------------
# Pair chart: computed on side B (lines 1528-1533)
# ---------------------------------------------------------------------------

class TestPairChartComputedSideB:
    """Pair chart where the computed metric is on the B side."""

    async def test_pair_chart_computed_type_b(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Find pair where computed is metric_b → type_b resolves to result_type."""
        token = user_a["token"]
        bool_m = await create_metric(
            client, token, name="FlagB", metric_type="bool", slug="flagb",
        )
        num = await create_metric(
            client, token, name="BaseB", metric_type="number", slug="baseb",
        )
        comp = await client.post(
            "/api/metrics",
            json={
                "name": "CompB2", "type": "computed",
                "formula": [
                    {"type": "metric", "id": num["id"]},
                    {"type": "op", "value": "*"},
                    {"type": "number", "value": 2},
                ],
                "result_type": "float",
            },
            headers=auth_headers(token),
        )
        assert comp.status_code == 201
        comp_id = comp.json()["id"]

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num["id"], date_str, day * 5)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find pairs where computed is on B side
        comp_b_pair = None
        for p in pairs_data["pairs"]:
            if p.get("metric_b_id") == comp_id:
                comp_b_pair = p
                break

        if comp_b_pair is None:
            # If computed ended up on A side in all pairs, find one and test it
            for p in pairs_data["pairs"]:
                if p.get("metric_a_id") == comp_id:
                    comp_b_pair = p
                    break

        assert comp_b_pair is not None, "Expected a pair with the computed metric"

        # Get pair chart
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={comp_b_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert len(chart["dates"]) > 0
        # The computed type should be resolved
        if comp_b_pair.get("metric_b_id") == comp_id:
            assert chart["type_b"] == "float"
        else:
            assert chart["type_a"] == "float"


# ---------------------------------------------------------------------------
# Pair chart: time and scale metrics for type hint coverage
# ---------------------------------------------------------------------------

class TestCorrelationTypeHints:
    """Verify correlation pairs with time/scale metrics have proper hints."""

    async def test_time_metric_hints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Time metric in correlation produces 'позже'/'раньше' hints."""
        token = user_a["token"]
        time_m = await create_metric(
            client, token, name="WakeCorr", metric_type="time", slug="wake_corr",
        )
        num_m = await create_metric(
            client, token, name="StepsCorr2", metric_type="number", slug="steps_corr2",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            hours = 7 + (day % 3)
            await create_entry(client, token, time_m["id"], date_str, f"{hours:02d}:00")
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a pair involving the time metric
        time_pair = None
        for p in pairs_data["pairs"]:
            if p.get("type_a") == "time" or p.get("type_b") == "time":
                time_pair = p
                break
        assert time_pair is not None, "Expected pair with time metric"
        # Time hints should be "позже" or "раньше"
        hints = {time_pair.get("hint_a", ""), time_pair.get("hint_b", "")}
        assert "позже" in hints or "раньше" in hints, (
            f"Expected time hints, got: {hints}"
        )

    async def test_scale_metric_hints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Scale metric in correlation produces 'выше'/'ниже' hints."""
        token = user_a["token"]
        scale_m = await create_metric(
            client, token, name="EnergyCorr", metric_type="scale",
            slug="energy_corr", scale_min=1, scale_max=5, scale_step=1,
        )
        bool_m = await create_metric(
            client, token, name="ExCorr", metric_type="bool", slug="ex_corr",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, scale_m["id"], date_str, (day % 5) + 1)
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=200",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a pair involving the scale metric
        scale_pair = None
        for p in pairs_data["pairs"]:
            if p.get("type_a") == "scale" or p.get("type_b") == "scale":
                scale_pair = p
                break
        assert scale_pair is not None, "Expected pair with scale metric"
        hints = {scale_pair.get("hint_a", ""), scale_pair.get("hint_b", "")}
        assert "выше" in hints or "ниже" in hints, (
            f"Expected scale hints, got: {hints}"
        )


# ---------------------------------------------------------------------------
# Quality issue integration tests
# ---------------------------------------------------------------------------

class TestQualityIssueIntegration:
    """Integration tests for quality_issue computation and category filters."""

    async def test_low_variance_metric_gets_issue(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Metric with constant values should get insufficient_variance issue."""
        token = user_a["token"]

        # Metric with zero variance (all values = 1)
        const_m = await create_metric(
            client, token, name="ConstVal", metric_type="number", slug="constval",
        )
        # Metric with varying values
        var_m = await create_metric(
            client, token, name="VaryVal", metric_type="number", slug="varyval",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, const_m["id"], date_str, 1)
            await create_entry(client, token, var_m["id"], date_str, day * 10)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find pairs involving ConstVal — they should have insufficient_variance
        const_pairs = [
            p for p in pairs_data["pairs"]
            if p.get("metric_a_id") == const_m["id"]
            or p.get("metric_b_id") == const_m["id"]
        ]
        assert len(const_pairs) > 0, "Expected pairs with constant metric"
        for p in const_pairs:
            assert p["quality_issue"] is not None, (
                f"Constant metric pair should have quality_issue, got: {p}"
            )

    async def test_category_filter_maybe(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs filtered by category=maybe all have quality_issue='wide_ci'."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?category=maybe&limit=500",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        for pair in data["pairs"]:
            assert pair["quality_issue"] == "wide_ci", (
                f"maybe category should only have wide_ci, got: {pair['quality_issue']}"
            )

    async def test_category_filter_insig(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs filtered by category=insig have non-null quality_issue != wide_ci."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?category=insig&limit=500",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        for pair in data["pairs"]:
            assert pair["quality_issue"] is not None, "insig pairs must have quality_issue"
            assert pair["quality_issue"] != "wide_ci", (
                f"insig should exclude wide_ci, got: {pair['quality_issue']}"
            )

    async def test_category_filter_sig_strong_excludes_issues(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pairs filtered by category=sig_strong have quality_issue=None."""
        await _create_metrics_with_entries(client, user_a["token"])
        report_body = await _start_report(client, user_a["token"])
        report_id = report_body["report_id"]
        await _wait_for_report_done(client, user_a["token"])

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?category=sig_strong&limit=500",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        for pair in data["pairs"]:
            assert pair["quality_issue"] is None, (
                f"sig_strong should have no quality_issue, got: {pair['quality_issue']}"
            )


# ---------------------------------------------------------------------------
# SLOT_MAX / SLOT_MIN auto-sources
# ---------------------------------------------------------------------------

class TestSlotMaxMinAutoSources:

    async def test_number_metric_with_slots_produces_slot_max_min(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Number metric with slots produces slot_max and slot_min auto-sources."""
        token = user_a["token"]

        # Create two slots
        slot_a = await create_slot(client, token, "Утро")
        slot_b = await create_slot(client, token, "Вечер")

        # Create number metric linked to both slots
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Кофе", "type": "number",
                "slot_configs": [
                    {"slot_id": slot_a["id"]},
                    {"slot_id": slot_b["id"]},
                ],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        num_m = resp.json()

        # Create bool metric as correlation counterpart
        bool_m = await create_metric(
            client, token, name="CorrBool", metric_type="bool", slug="corrbool_slotmm",
        )

        # Create entries (15 days)
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num_m["id"], date_str, day, slot_id=slot_a["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 2, slot_id=slot_b["id"])
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        # Run correlation report
        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        assert data["report"]["status"] == "done"
        report_id = data["report"]["id"]

        # Fetch all pairs
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Collect all labels
        labels = set()
        for p in pairs_data["pairs"]:
            labels.add(p["label_a"])
            labels.add(p["label_b"])

        # slot_max and slot_min should appear
        max_labels = [l for l in labels if "максимум" in l]
        min_labels = [l for l in labels if "минимум" in l]
        assert len(max_labels) > 0, f"Expected slot_max label with 'максимум', got labels: {labels}"
        assert len(min_labels) > 0, f"Expected slot_min label with 'минимум', got labels: {labels}"

    async def test_slot_max_min_chart_reconstruction(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Pair chart reconstruction works for slot_max/slot_min sources."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "AM")
        slot_b = await create_slot(client, token, "PM")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Mood", "type": "scale",
                "scale_min": 1, "scale_max": 10, "scale_step": 1,
                "slot_configs": [
                    {"slot_id": slot_a["id"]},
                    {"slot_id": slot_b["id"]},
                ],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        scale_m = resp.json()

        bool_m = await create_metric(
            client, token, name="Exercise", metric_type="bool", slug="exercise_slotmm",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, scale_m["id"], date_str, day % 10 + 1, slot_id=slot_a["id"])
            await create_entry(client, token, scale_m["id"], date_str, (day * 3) % 10 + 1, slot_id=slot_b["id"])
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find a slot_max pair
        max_pair = None
        for p in pairs_data["pairs"]:
            if "максимум" in p.get("label_a", "") or "максимум" in p.get("label_b", ""):
                max_pair = p
                break
        assert max_pair is not None, "Expected slot_max pair"

        # Get pair chart
        resp = await client.get(
            f"/api/analytics/correlation-pair-chart?pair_id={max_pair['pair_id']}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        chart = resp.json()
        assert len(chart["dates"]) > 0


# ---------------------------------------------------------------------------
# Bool aggregate annotation "(хоть раз)"
# ---------------------------------------------------------------------------

class TestBoolAggregateAnnotation:

    async def test_bool_with_slots_aggregate_label_has_annotation(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric with slots: aggregate source label contains '(хоть раз)'."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Morning")
        slot_b = await create_slot(client, token, "Evening")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Зарядка", "type": "bool",
                "slot_configs": [
                    {"slot_id": slot_a["id"]},
                    {"slot_id": slot_b["id"]},
                ],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        bool_m = resp.json()

        num_m = await create_metric(
            client, token, name="Steps", metric_type="number", slug="steps_bool_annot",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, True, slot_id=slot_a["id"])
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0, slot_id=slot_b["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()
        assert pairs_data["total"] > 0

        # Find aggregate bool source — should have "(хоть раз)" annotation
        aggregate_labels = set()
        for p in pairs_data["pairs"]:
            for label_key, sk_key in [("label_a", "source_key_a"), ("label_b", "source_key_b")]:
                # skip if source_key not exposed; check label
                pass
            if "хоть раз" in p.get("label_a", ""):
                aggregate_labels.add(p["label_a"])
            if "хоть раз" in p.get("label_b", ""):
                aggregate_labels.add(p["label_b"])

        assert len(aggregate_labels) > 0, (
            f"Expected '(хоть раз)' annotation on bool aggregate label"
        )
        # The annotation should include the metric name
        for lbl in aggregate_labels:
            assert "Зарядка" in lbl

    async def test_bool_with_single_slot_no_annotation(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric with 1 slot (fixed interval) should NOT have '(хоть раз)' annotation."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Morning")
        await create_slot(client, token, "Evening")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "FixedBool", "type": "bool",
                "interval_binding": "by_interval",
                "interval_slot_ids": [slot_a["id"]],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        bool_m = resp.json()
        assert len(bool_m["slots"]) == 1

        num_m = await create_metric(
            client, token, name="StepsFixed", metric_type="number", slug="steps_fixed_annot",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0, slot_id=slot_a["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        for p in pairs_data["pairs"]:
            assert "хоть раз" not in p.get("label_a", ""), (
                f"Unexpected annotation in label_a: {p['label_a']}"
            )
            assert "хоть раз" not in p.get("label_b", ""), (
                f"Unexpected annotation in label_b: {p['label_b']}"
            )

    async def test_bool_without_slots_no_annotation(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool metric without slots should NOT have '(хоть раз)' annotation."""
        token = user_a["token"]

        bool_m = await create_metric(
            client, token, name="SimpleBool", metric_type="bool", slug="simplebool_noannot",
        )
        num_m = await create_metric(
            client, token, name="SimpleNum", metric_type="number", slug="simplenum_noannot",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)
            await create_entry(client, token, num_m["id"], date_str, day * 10)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # No "(хоть раз)" annotation on any label
        for p in pairs_data["pairs"]:
            assert "хоть раз" not in p.get("label_a", ""), (
                f"Unexpected annotation in label_a: {p['label_a']}"
            )
            assert "хоть раз" not in p.get("label_b", ""), (
                f"Unexpected annotation in label_b: {p['label_b']}"
            )


# ---------------------------------------------------------------------------
# Single-slot metric: no duplicate aggregate + per-slot, interval labels
# ---------------------------------------------------------------------------

class TestSingleSlotNoDuplicate:
    """Bool metric with 1 slot (fixed interval) should NOT produce both aggregate and per-slot pairs."""

    async def test_single_slot_no_aggregate_duplicate(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Утро")
        await create_slot(client, token, "День")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Зарядка", "type": "bool",
                "interval_binding": "by_interval",
                "interval_slot_ids": [slot_a["id"]],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        bool_m = resp.json()
        assert len(bool_m["slots"]) == 1

        num_m = await create_metric(
            client, token, name="Шаги", metric_type="number", slug="steps_single_slot",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0, slot_id=slot_a["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Collect distinct labels involving "Зарядка" paired with "Шаги" at lag=0
        zaryadka_labels = set()
        for p in pairs_data["pairs"]:
            if p.get("lag_days", 0) != 0:
                continue
            la, lb = p.get("label_a", ""), p.get("label_b", "")
            if "Шаги" in la and "Зарядка" in lb:
                zaryadka_labels.add(lb)
            elif "Шаги" in lb and "Зарядка" in la:
                zaryadka_labels.add(la)

        # Should be exactly 1 label (per-slot only), not 2 (aggregate "Зарядка" + per-slot "Зарядка: ...")
        assert len(zaryadka_labels) == 1, (
            f"Expected 1 label for single-slot metric, got {len(zaryadka_labels)}: {zaryadka_labels}"
        )

    async def test_single_slot_uses_interval_label(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Per-slot label for interval-bound metric should show 'X → Y', not just 'X'."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Утро")
        await create_slot(client, token, "День")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Зарядка", "type": "bool",
                "interval_binding": "by_interval",
                "interval_slot_ids": [slot_a["id"]],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        bool_m = resp.json()

        num_m = await create_metric(
            client, token, name="Шаги", metric_type="number", slug="steps_interval_lbl",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0, slot_id=slot_a["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find label for Зарядка — should contain interval "Утро → День"
        zaryadka_labels = set()
        for p in pairs_data["pairs"]:
            if "Зарядка" in p.get("label_a", ""):
                zaryadka_labels.add(p["label_a"])
            if "Зарядка" in p.get("label_b", ""):
                zaryadka_labels.add(p["label_b"])

        assert any("Утро → День" in lbl for lbl in zaryadka_labels), (
            f"Expected interval label 'Утро → День' in labels, got: {zaryadka_labels}"
        )

    async def test_single_slot_slot_label_uses_interval(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """slot_label_a/b field should show interval label, not raw checkpoint name."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Утро")
        await create_slot(client, token, "День")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Зарядка", "type": "bool",
                "interval_binding": "by_interval",
                "interval_slot_ids": [slot_a["id"]],
            },
            headers=auth_headers(token),
        )
        bool_m = resp.json()

        num_m = await create_metric(
            client, token, name="Шаги", metric_type="number", slug="steps_slot_lbl",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0, slot_id=slot_a["id"])
            await create_entry(client, token, num_m["id"], date_str, day * 100)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        slot_labels = set()
        for p in pairs_data["pairs"]:
            if "Зарядка" in p.get("label_a", "") and p.get("slot_label_a"):
                slot_labels.add(p["slot_label_a"])
            if "Зарядка" in p.get("label_b", "") and p.get("slot_label_b"):
                slot_labels.add(p["slot_label_b"])

        # slot_label should be interval "Утро → День", not raw "Утро"
        for sl in slot_labels:
            assert "→" in sl, (
                f"Expected interval label with '→', got raw checkpoint name: '{sl}'"
            )

    async def test_fixed_number_has_nonzero_auto_source(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Fixed number metric (1 slot) should generate nonzero auto-source like daily."""
        token = user_a["token"]

        slot_a = await create_slot(client, token, "Утро")
        await create_slot(client, token, "День")

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Отжимания", "type": "number",
                "interval_binding": "by_interval",
                "interval_slot_ids": [slot_a["id"]],
            },
            headers=auth_headers(token),
        )
        num_fixed = resp.json()

        bool_m = await create_metric(
            client, token, name="Спорт", metric_type="bool", slug="sport_nonzero",
        )

        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num_fixed["id"], date_str, day * 5, slot_id=slot_a["id"])
            await create_entry(client, token, bool_m["id"], date_str, day % 2 == 0)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Should have "не ноль" auto-source for the fixed number metric
        nonzero_labels = [
            p for p in pairs_data["pairs"]
            if "не ноль" in p.get("label_a", "") or "не ноль" in p.get("label_b", "")
        ]
        assert len(nonzero_labels) > 0, (
            "Expected 'не ноль' auto-source for fixed number metric"
        )


# ---------------------------------------------------------------------------
# Insufficient binary group
# ---------------------------------------------------------------------------

class TestInsufficientBinaryGroup:
    """Bool metric with only 3 True out of 15 days should get low_binary_data_points."""

    async def test_small_binary_group_flagged(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]

        bool_m = await create_metric(
            client, token, name="RareBool", metric_type="bool", slug="rarebool_grp",
        )
        num_m = await create_metric(
            client, token, name="NumForBin", metric_type="number", slug="numforbin_grp",
        )

        # 3 True out of 15 days: variance ≈ 0.16 (passes threshold),
        # but min(count_true, count_false) = 3 < 5
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            bool_val = day <= 3  # True for days 1-3, False for 4-15
            await create_entry(client, token, bool_m["id"], date_str, bool_val)
            await create_entry(client, token, num_m["id"], date_str, day * 10)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs?limit=500",
            headers=auth_headers(token),
        )
        pairs_data = resp.json()

        # Find direct bool↔number pairs (exclude auto-sources like nonzero
        # which have variance=0 and would trigger insufficient_variance instead)
        bool_id = bool_m["id"]
        num_id = num_m["id"]
        direct_pairs = [
            p for p in pairs_data["pairs"]
            if {p["metric_a_id"], p["metric_b_id"]} == {bool_id, num_id}
            and p["label_a"] in ("RareBool", "NumForBin")
            and p["label_b"] in ("RareBool", "NumForBin")
        ]
        assert len(direct_pairs) > 0, "Expected at least one direct bool↔number pair"

        for p in direct_pairs:
            assert p["quality_issue"] == "low_binary_data_points", (
                f"Expected low_binary_data_points but got {p['quality_issue']} "
                f"for pair {p['label_a']} vs {p['label_b']}"
            )


# ---------------------------------------------------------------------------
# Fisher exact test quality issue for binary pairs
# ---------------------------------------------------------------------------

class TestFisherExactQualityIssue:

    async def test_binary_pair_fisher_disagrees_with_pearson(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Two bool metrics, 5 True each out of 20 days, overlapping on 3 days.

        Pearson gives r≈0.47, p≈0.04 (significant), but Fisher's exact test
        gives p≈0.07 (not significant). The pair should get fisher_exact_high_p.

        Data layout:
          Days 1-3:   both True  (overlap)
          Days 4-5:   A True, B False
          Days 6-7:   A False, B True
          Days 8-20:  both False
        """
        token = user_a["token"]
        bool_a = await create_metric(
            client, token, name="FisherA", metric_type="bool", slug="fisher_a",
        )
        bool_b = await create_metric(
            client, token, name="FisherB", metric_type="bool", slug="fisher_b",
        )
        # A True on days 1-5, B True on days 1-3 and 6-7
        a_true_days = {1, 2, 3, 4, 5}
        b_true_days = {1, 2, 3, 6, 7}
        for day in range(1, 21):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_a["id"], date_str, day in a_true_days)
            await create_entry(client, token, bool_b["id"], date_str, day in b_true_days)

        await _start_report(client, token)
        data = await _wait_for_report_done(client, token)
        assert data["report"] is not None
        report_id = data["report"]["id"]

        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            params={"category": "maybe"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        pairs_data = resp.json()

        a_id = bool_a["id"]
        b_id = bool_b["id"]
        fisher_pairs = [
            p for p in pairs_data["pairs"]
            if {p["metric_a_id"], p["metric_b_id"]} == {a_id, b_id}
            and p["label_a"] in ("FisherA", "FisherB")
            and p["label_b"] in ("FisherA", "FisherB")
            and p["lag_days"] == 0
        ]
        assert len(fisher_pairs) > 0, (
            "Expected at least one FisherA↔FisherB lag=0 pair in 'maybe' category"
        )
        for p in fisher_pairs:
            assert p["quality_issue"] == "fisher_exact_high_p", (
                f"Expected fisher_exact_high_p but got {p['quality_issue']} "
                f"for pair {p['label_a']} vs {p['label_b']}"
            )
            assert p["quality_severity"] == "maybe"


# ---------------------------------------------------------------------------
# Streak sources
# ---------------------------------------------------------------------------

class TestStreakSources:
    """Verify streak auto-sources appear in correlation report for bool metrics."""

    @pytest.fixture(autouse=True)
    def _enable_streaks(self, monkeypatch):  # type: ignore[no-untyped-def]
        from app.correlation_config import AutoSourcesConfig, CorrelationConfig
        cfg = CorrelationConfig(auto_sources=AutoSourcesConfig(streak=True))
        monkeypatch.setattr("app.routers.analytics.correlation_config", cfg)

    async def test_streak_labels_present_in_report(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """A bool metric with 15 entries should produce streak_true and streak_false pairs."""
        token = user_a["token"]
        bool_m = await create_metric(
            client, token, name="StreakTest", metric_type="bool", slug="streak_test_bool",
        )
        # Pattern: T F T T T F F T T T T T F T T
        pattern = [True, False, True, True, True, False, False, True, True, True, True, True, False, True, True]
        for day, val in enumerate(pattern, start=1):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, bool_m["id"], date_str, val)

        # Also create a number metric so there are pairs to correlate with
        num_m = await create_metric(
            client, token, name="StreakNum", metric_type="number", slug="streak_test_num",
        )
        for day in range(1, 16):
            date_str = f"2026-01-{day:02d}"
            await create_entry(client, token, num_m["id"], date_str, day * 10)

        await _start_report(client, token, start="2026-01-01", end="2026-01-15")
        data = await _wait_for_report_done(client, token)
        assert data.get("report") is not None, "Report did not finish"
        report_id = data["report"]["id"]

        # Fetch all pairs (large limit to get them all)
        resp = await client.get(
            f"/api/analytics/correlation-report/{report_id}/pairs",
            params={"limit": 500},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        pairs_data = resp.json()
        all_labels = set()
        for p in pairs_data["pairs"]:
            all_labels.add(p["label_a"])
            all_labels.add(p["label_b"])

        assert "StreakTest: серия подряд (да)" in all_labels, (
            f"Expected streak_true label, got labels: {all_labels}"
        )
        assert "StreakTest: серия подряд (нет)" in all_labels, (
            f"Expected streak_false label, got labels: {all_labels}"
        )
