"""API tests for interval binding feature."""

import pytest

from tests.conftest import auth_headers, create_entry, create_metric, create_checkpoint


async def _get_intervals(client, token: str) -> list[dict]:
    """Fetch all intervals via GET /api/checkpoints/intervals."""
    resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.anyio
class TestIntervalBindingCreate:
    async def test_create_all_day_default(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        assert metric["interval_binding"] == "all_day"

    async def test_create_by_interval_with_one_interval(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        assert len(intervals) >= 1
        iv1 = intervals[0]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["intervals"]) == 1

    async def test_create_by_interval_with_all_intervals(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        assert len(intervals) >= 2
        iv_ids = [iv["id"] for iv in intervals]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": iv_ids[:2]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["intervals"]) == 2


@pytest.mark.anyio
class TestIntervalBindingUpdate:
    async def test_switch_to_by_interval(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv_ids = [iv["id"] for iv in intervals]

        metric = await create_metric(client, user_a["token"], name="Кофе", metric_type="bool")
        assert metric["interval_binding"] == "all_day"
        assert len(metric["intervals"]) == 0

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": iv_ids[:2]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["intervals"]) == 2

    async def test_switch_back_to_all_day(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["intervals"]) == 1

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["interval_binding"] == "all_day"


@pytest.mark.anyio
class TestIntervalBindingValidation:
    async def test_by_interval_without_interval_ids_returns_400(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestIntervalLabelsInMetricsApi:
    async def test_single_interval_label(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert len(data["intervals"]) == 1
        assert data["intervals"][0]["label"] == "Утро → День"

    async def test_multiple_intervals_have_labels(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv_ids = [iv["id"] for iv in intervals]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": iv_ids[:2]},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        labels = [iv["label"] for iv in data["intervals"]]
        assert "Утро → День" in labels
        assert "День → Вечер" in labels

    async def test_list_metrics_shows_interval_labels(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metrics = resp.json()
        shower = [m for m in metrics if m["name"] == "Душ"][0]
        assert shower["intervals"][0]["label"] == "Утро → День"

    async def test_assessment_keeps_checkpoint_label(self, client, user_a):
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        cp2 = await create_checkpoint(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Настроение", "type": "scale", "scale_min": 1, "scale_max": 5,
                  "is_checkpoint": True,
                  "checkpoint_configs": [{"checkpoint_id": cp1["id"]}, {"checkpoint_id": cp2["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "all_day"
        labels = [cp["label"] for cp in data["checkpoints"]]
        assert "Утро" in labels
        assert "День" in labels
        assert "Утро → День" not in labels


@pytest.mark.anyio
class TestIntervalDailyPage:
    async def test_daily_shows_interval_labels(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv_ids = [iv["id"] for iv in intervals]

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": iv_ids[:2]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert len(coffee) == 2
        labels = [c["intervals"][0]["label"] for c in coffee]
        assert "Утро → День" in labels
        assert "День → Вечер" in labels

    async def test_daily_interval_binding_field(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert coffee[0]["interval_binding"] == "by_interval"


@pytest.mark.anyio
class TestMultiIntervalCreate:
    async def test_create_by_interval_with_multiple_intervals(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")
        await create_checkpoint(client, user_a["token"], "Ночь")

        intervals = await _get_intervals(client, user_a["token"])
        # Pick first and third intervals (non-consecutive)
        iv1, iv3 = intervals[0], intervals[2]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"], iv3["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["intervals"]) == 2
        returned_ids = {iv["id"] for iv in data["intervals"]}
        assert iv1["id"] in returned_ids
        assert iv3["id"] in returned_ids

    async def test_create_by_interval_with_all_intervals(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv_ids = [iv["id"] for iv in intervals]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Шаги", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": iv_ids[:2]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["intervals"]) == 2


@pytest.mark.anyio
class TestMultiIntervalUpdate:
    async def test_update_add_interval(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv1, iv2 = intervals[0], intervals[1]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["intervals"]) == 1

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv1["id"], iv2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["intervals"]) == 2

    async def test_update_remove_interval(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv1, iv2 = intervals[0], intervals[1]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"], iv2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["intervals"]) == 2

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["intervals"]) == 1
        assert data["intervals"][0]["id"] == iv2["id"]

    async def test_update_change_intervals(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv1, iv2 = intervals[0], intervals[1]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["intervals"]) == 1
        assert data["intervals"][0]["id"] == iv2["id"]


@pytest.mark.anyio
class TestMultiIntervalValidation:
    async def test_by_interval_empty_array_returns_400(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": []},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_invalid_id_returns_400(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [99999]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_deleted_checkpoint_returns_400(self, client, user_a):
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        # Soft delete checkpoint — intervals that reference it become invalid
        await client.delete(f"/api/checkpoints/{cp1['id']}", headers=auth_headers(user_a["token"]))

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_duplicate_ids_ignored(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"], iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["intervals"]) == 1


@pytest.mark.anyio
class TestMultiIntervalDailyPage:
    async def test_daily_shows_only_selected_intervals(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert len(coffee) == 1
        assert coffee[0]["intervals"][0]["label"] == "Утро → День"


@pytest.mark.anyio
class TestIntervalBindingChangeMigration:
    """Bug A + Bug B: entry visibility when interval_binding changes."""

    async def test_bug_a_no_entries_by_interval_to_all_day_shows_no_intervals(self, client, user_a):
        """Bug A: after by_interval -> all_day, daily page shows NO interval containers (no entries)."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        # Create metric as by_interval (no entries for the test date)
        resp = await client.post(
            "/api/metrics",
            json={"name": "Спорт", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()

        # Change back to all_day
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Daily page: should show NO interval containers (intervals properly disabled)
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        assert sport[0]["intervals"] is None, "Intervals should be None after switching back to all_day"
        assert sport[0]["entry"] is None

    async def test_bug_b_all_day_entry_visible_after_switch_to_by_interval(self, client, user_a):
        """Bug B: old all_day entry (interval_id=NULL) should remain visible after switching to by_interval."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        # Fill entry as all_day (interval_id=NULL)
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)

        # Change to by_interval -> old entry should migrate to first interval
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Daily page: old entry should be visible (in first interval)
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        assert sport[0]["intervals"] is not None
        assert sport[0]["intervals"][0]["entry"] is not None, "Old all_day entry should be visible in first interval"
        assert sport[0]["intervals"][0]["entry"]["value"] is True

    async def test_full_cycle_all_day_to_by_interval_to_all_day(self, client, user_a):
        """Full cycle: entry remains accessible through all binding changes."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        # Fill entry as all_day
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)

        # all_day -> by_interval (entry migrates to first interval)
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        # by_interval -> all_day
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Daily page: should show no interval containers, but entry still accessible via disabled-interval path
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        # After full cycle: intervals are disabled, entry (now with interval_id=iv1) should show via disabled-interval path
        # The metric renders with intervals=[{interval_id: iv1, entry: {value: True}}]
        # OR as a single entry depending on implementation
        # At minimum: the entry value must be accessible somewhere
        has_entry_in_intervals = (
            sport[0]["intervals"] is not None
            and any(iv["entry"] is not None for iv in sport[0]["intervals"])
        )
        has_single_entry = sport[0]["entry"] is not None
        assert has_entry_in_intervals or has_single_entry, "Entry should be accessible after full cycle"


@pytest.mark.anyio
class TestDisabledIntervalsNoCrossMetricContamination:
    """Bug: disabled metric_intervals picked up entries from OTHER metrics.

    get_disabled_intervals_with_entries JOIN entries was missing e.metric_id filter,
    so any entry with matching interval_id (from any metric) would cause disabled
    intervals to appear for a metric that had switched to all_day.
    """

    async def test_all_day_metric_not_contaminated_by_other_metric_intervals(self, client, user_a):
        """Metric switched to all_day must NOT show intervals from other metrics' entries."""
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        cp2 = await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        # Metric A: by_interval, stays that way
        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric_a = resp.json()

        # Metric B: start as by_interval, then switch to all_day
        resp = await client.post(
            "/api/metrics",
            json={"name": "Читал", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric_b = resp.json()

        # Switch Metric B to all_day (metric_intervals become disabled)
        resp = await client.patch(
            f"/api/metrics/{metric_b['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["interval_binding"] == "all_day"

        # Create entry for Metric A with interval_id (this is the "contaminant")
        date = "2026-03-29"
        await create_entry(client, user_a["token"], metric_a["id"], date, True, interval_id=iv1["id"])

        # Daily page: Metric B must NOT show intervals
        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        read_items = [m for m in metrics if m["name"] == "Читал"]
        assert len(read_items) == 1, f"Expected 1 item for Читал, got {len(read_items)}"
        assert read_items[0]["intervals"] is None, (
            "Metric switched to all_day must not have intervals from other metrics' entries"
        )

    async def test_disabled_checkpoints_no_cross_metric_contamination(self, client, user_a):
        """Metric with disabled checkpoints must NOT pick up entries from other metrics."""
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        cp2 = await create_checkpoint(client, user_a["token"], "День")
        cp3 = await create_checkpoint(client, user_a["token"], "Вечер")

        # Metric A: checkpoint-bound with cp1+cp2, stays that way
        resp = await client.post(
            "/api/metrics",
            json={"name": "Настроение", "type": "scale", "scale_min": 1, "scale_max": 5,
                  "is_checkpoint": True,
                  "checkpoint_configs": [{"checkpoint_id": cp1["id"]}, {"checkpoint_id": cp2["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        metric_a = resp.json()

        # Metric B: checkpoint-bound with cp1+cp2, then narrow to cp2+cp3 (cp1 becomes disabled)
        resp = await client.post(
            "/api/metrics",
            json={"name": "Энергия", "type": "scale", "scale_min": 1, "scale_max": 5,
                  "is_checkpoint": True,
                  "checkpoint_configs": [{"checkpoint_id": cp1["id"]}, {"checkpoint_id": cp2["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        metric_b = resp.json()

        # Narrow Metric B: keep only cp2+cp3 (cp1 becomes disabled)
        resp = await client.patch(
            f"/api/metrics/{metric_b['id']}",
            json={"checkpoint_configs": [{"checkpoint_id": cp2["id"]}, {"checkpoint_id": cp3["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Create entry for Metric A at cp1 (this is the "contaminant")
        date = "2026-03-29"
        await create_entry(client, user_a["token"], metric_a["id"], date, 4, checkpoint_id=cp1["id"])

        # Daily page: Metric B must NOT show cp1 from Metric A's entry
        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        energy_items = [m for m in metrics if m["name"] == "Энергия"]
        # Metric B should have cp2 and cp3 (enabled), but NOT cp1 (disabled, no own entries)
        cp_ids = set()
        for item in energy_items:
            if item.get("checkpoints"):
                for cp in item["checkpoints"]:
                    cp_ids.add(cp["checkpoint_id"])
        assert cp1["id"] not in cp_ids, (
            "Disabled checkpoint must not appear due to other metric's entries"
        )


@pytest.mark.anyio
class TestIntervalBindingUpdateNoMigration:
    async def test_update_category_does_not_remigrate_entries(self, client, user_a):
        """Bug: PATCH with same interval_ids on already-by_interval metric caused 500
        when null-interval and interval entries existed for same date (UniqueViolationError)."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        iv1 = intervals[0]

        cat_resp = await client.post(
            "/api/categories",
            json={"name": "Тест"},
            headers=auth_headers(user_a["token"]),
        )
        cat = cat_resp.json()

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        # Step 1: create all_day entry for date D
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)
        # Step 2: switch to by_interval -> null entry migrated to iv1 (interval_id=iv1 now)
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_ids": [iv1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        # Step 3: switch back to all_day
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        # Step 4: create a new all_day entry for same date D (interval_id=NULL)
        # Now DB has BOTH (date=D, interval_id=iv1) AND (date=D, interval_id=NULL) for this metric
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", False)
        # Step 5: PATCH to by_interval again + category — frontend sends full form.
        # DB now has both (date=D, interval_id=iv1) and (date=D, interval_id=NULL).
        # Before fix: migrate_null_interval_entries tries to move interval=NULL entry to iv1,
        # but (date=D, interval_id=iv1) already exists -> 500 UniqueViolationError
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "category_id": cat["id"],
                "interval_binding": "by_interval",
                "interval_ids": [iv1["id"]],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200


@pytest.mark.anyio
class TestIntervalMetricInListRegression:
    """Факт-метрика с interval_ids корректно возвращается в GET /api/metrics.

    Регрессия: SQL JOIN intervals ссылался на несуществующие колонки
    i.sort_order и i.deleted вместо mi.sort_order и cs.deleted/ce.deleted.
    """

    async def test_metric_with_intervals_appears_in_list(self, client, user_a):
        """Создаём факт с интервалом → GET /api/metrics возвращает его с intervals."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        assert len(intervals) >= 1
        iv = intervals[0]

        metric = await client.post(
            "/api/metrics",
            json={"name": "Продуктивность", "type": "number",
                  "interval_binding": "by_interval", "interval_ids": [iv["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert metric.status_code == 201
        mid = metric.json()["id"]

        # GET /api/metrics должен вернуть метрику с intervals и лейблами
        resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        found = next((m for m in resp.json() if m["id"] == mid), None)
        assert found is not None
        assert len(found["intervals"]) == 1
        assert "→" in found["intervals"][0]["label"]

    async def test_interval_metric_entry_round_trip(self, client, user_a):
        """Создаём entry с interval_id → она возвращается в GET /api/entries."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "Вечер")

        intervals = await _get_intervals(client, user_a["token"])
        iv = intervals[0]

        metric = await client.post(
            "/api/metrics",
            json={"name": "Работа", "type": "duration",
                  "interval_binding": "by_interval", "interval_ids": [iv["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert metric.status_code == 201
        mid = metric.json()["id"]

        entry = await create_entry(
            client, user_a["token"], mid, "2026-03-01", 120,
            interval_id=iv["id"],
        )
        assert entry["interval_id"] == iv["id"]

        # Verify via GET entries
        resp = await client.get(
            f"/api/entries?date=2026-03-01&metric_id={mid}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["interval_id"] == iv["id"]
