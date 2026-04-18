"""Tests for free_intervals feature — multiple entries per day with time ranges."""

from httpx import AsyncClient

from tests.conftest import auth_headers, create_entry, create_metric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_free_iv_metric(
    client: AsyncClient, token: str, *, name: str = "Coffee", metric_type: str = "number",
) -> dict:
    payload: dict = {"name": name, "type": metric_type, "interval_binding": "free_intervals"}
    resp = await client.post("/api/metrics", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_free_iv_entry(
    client: AsyncClient, token: str, metric_id: int, date: str,
    value: bool | int | str | list[int],
    time_start: str = "10:00", time_end: str = "11:00",
) -> dict:
    return await create_entry(
        client, token, metric_id, date, value,
        time_start=time_start, time_end=time_end,
    )


# ---------------------------------------------------------------------------
# Create metric
# ---------------------------------------------------------------------------

class TestCreateFreeIntervalMetric:
    async def test_create_number_metric(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        assert m["interval_binding"] == "free_intervals"
        assert m["is_checkpoint"] is False

    async def test_create_bool_metric(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"], name="Friends", metric_type="bool")
        assert m["interval_binding"] == "free_intervals"

    async def test_incompatible_with_is_checkpoint(self, client: AsyncClient, user_a: dict) -> None:
        payload = {
            "name": "Bad", "type": "number", "interval_binding": "free_intervals",
            "is_checkpoint": True,
        }
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_incompatible_with_computed(self, client: AsyncClient, user_a: dict) -> None:
        payload = {"name": "Bad", "type": "computed", "interval_binding": "free_intervals"}
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_incompatible_with_text(self, client: AsyncClient, user_a: dict) -> None:
        payload = {"name": "Bad", "type": "text", "interval_binding": "free_intervals"}
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_incompatible_with_integration(self, client: AsyncClient, user_a: dict) -> None:
        payload = {"name": "Bad", "type": "integration", "interval_binding": "free_intervals"}
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------

class TestFreeIntervalEntries:
    async def test_create_multiple_entries_per_day(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        e1 = await _create_free_iv_entry(client, token, mid, date, 2, "10:00", "11:00")
        e2 = await _create_free_iv_entry(client, token, mid, date, 1, "15:00", "16:30")

        assert e1["id"] != e2["id"]
        assert e1["is_free_interval"] is True
        assert e1["time_start"] == "10:00"
        assert e1["time_end"] == "11:00"
        assert e2["time_start"] == "15:00"
        assert e2["time_end"] == "16:30"

    async def test_time_required(self, client: AsyncClient, user_a: dict) -> None:
        """Free interval entries must have time_start and time_end."""
        m = await _create_free_iv_metric(client, user_a["token"])
        payload = {"metric_id": m["id"], "date": "2026-04-04", "value": 2}
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_checkpoint_id_forbidden(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        payload = {
            "metric_id": m["id"], "date": "2026-04-04", "value": 2,
            "checkpoint_id": 999, "time_start": "10:00", "time_end": "11:00",
        }
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_duplicate_exact_range_rejected(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "11:00")

        payload = {
            "metric_id": mid, "date": "2026-04-04", "value": 3,
            "time_start": "10:00", "time_end": "11:00",
        }
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(token))
        assert resp.status_code == 409


class TestFreeIntervalOverlap:
    async def test_overlapping_ranges_rejected(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "12:00")

        payload = {
            "metric_id": mid, "date": "2026-04-04", "value": 1,
            "time_start": "11:00", "time_end": "13:00",
        }
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(token))
        assert resp.status_code == 409

    async def test_adjacent_ranges_allowed(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "12:00")
        e2 = await _create_free_iv_entry(client, token, mid, "2026-04-04", 1, "12:00", "14:00")
        assert e2["time_start"] == "12:00"

    async def test_non_overlapping_ranges_allowed(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "11:00")
        e2 = await _create_free_iv_entry(client, token, mid, "2026-04-04", 1, "15:00", "16:00")
        assert e2["id"] is not None


class TestFreeIntervalValidation:
    async def test_end_must_be_after_start(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        payload = {
            "metric_id": m["id"], "date": "2026-04-04", "value": 2,
            "time_start": "14:00", "time_end": "10:00",
        }
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_arbitrary_time_accepted(self, client: AsyncClient, user_a: dict) -> None:
        """Backend accepts any time, not just 30-min increments."""
        m = await _create_free_iv_metric(client, user_a["token"])
        e = await _create_free_iv_entry(client, user_a["token"], m["id"], "2026-04-04", 1, "10:17", "11:43")
        assert e["time_start"] == "10:17"
        assert e["time_end"] == "11:43"


class TestFreeIntervalEntryEdit:
    async def test_update_value(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        e = await _create_free_iv_entry(client, user_a["token"], m["id"], "2026-04-04", 2)

        resp = await client.put(
            f"/api/entries/{e['id']}", json={"value": 5},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == 5

    async def test_update_time_range(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        e = await _create_free_iv_entry(client, user_a["token"], m["id"], "2026-04-04", 2, "10:00", "11:00")

        resp = await client.patch(
            f"/api/entries/{e['id']}/time-range",
            json={"time_start": "14:00", "time_end": "15:30"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["time_start"] == "14:00"
        assert resp.json()["time_end"] == "15:30"

    async def test_update_time_range_non_free_iv_fails(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="Regular", metric_type="number")
        e = await create_entry(client, user_a["token"], m["id"], "2026-04-04", 5)

        resp = await client.patch(
            f"/api/entries/{e['id']}/time-range",
            json={"time_start": "14:00", "time_end": "15:30"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_update_time_range_overlap_rejected(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "12:00")
        e2 = await _create_free_iv_entry(client, token, mid, "2026-04-04", 1, "14:00", "16:00")

        # Try to move e2 to overlap with first entry
        resp = await client.patch(
            f"/api/entries/{e2['id']}/time-range",
            json={"time_start": "11:00", "time_end": "13:00"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 409


class TestFreeIntervalEntryDelete:
    async def test_delete_individual_entry(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        e1 = await _create_free_iv_entry(client, token, mid, "2026-04-04", 2, "10:00", "11:00")
        e2 = await _create_free_iv_entry(client, token, mid, "2026-04-04", 1, "15:00", "16:00")

        resp = await client.delete(f"/api/entries/{e1['id']}", headers=auth_headers(token))
        assert resp.status_code == 204

        entries_resp = await client.get(
            "/api/entries", params={"date": "2026-04-04", "metric_id": mid},
            headers=auth_headers(token),
        )
        assert len(entries_resp.json()) == 1
        assert entries_resp.json()[0]["id"] == e2["id"]


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

class TestFreeIntervalDaily:
    async def test_daily_contains_free_interval_entries(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        await _create_free_iv_entry(client, token, mid, date, 2, "10:00", "11:00")
        await _create_free_iv_entry(client, token, mid, date, 1, "15:00", "16:00")

        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()

        metric_item = next(item for item in data["metrics"] if item["metric_id"] == mid)
        assert metric_item["free_interval_entries"] is not None
        assert len(metric_item["free_interval_entries"]) == 2
        assert metric_item["entry"] is None

    async def test_free_interval_entries_sorted_by_time_start(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        e2 = await _create_free_iv_entry(client, token, mid, date, 1, "15:00", "16:00")
        e1 = await _create_free_iv_entry(client, token, mid, date, 2, "10:00", "11:00")

        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        metric_item = next(item for item in resp.json()["metrics"] if item["metric_id"] == mid)
        fie = metric_item["free_interval_entries"]
        assert fie[0]["id"] == e1["id"]  # 10:00 first
        assert fie[1]["id"] == e2["id"]  # 15:00 second


class TestFreeIntervalProgress:
    async def test_filled_with_at_least_one_entry(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        token = user_a["token"]
        date = "2026-04-04"

        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        progress = resp.json()["progress"]
        assert progress["filled"] == 0

        await _create_free_iv_entry(client, token, m["id"], date, 2, "10:00", "11:00")
        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        progress = resp.json()["progress"]
        assert progress["filled"] >= 1


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestFreeIntervalDataIsolation:
    async def test_entries_not_visible_to_other_user(self, client: AsyncClient, user_a: dict, user_b: dict) -> None:
        m = await _create_free_iv_metric(client, user_a["token"])
        await _create_free_iv_entry(client, user_a["token"], m["id"], "2026-04-04", 2, "10:00", "11:00")

        resp = await client.get(
            "/api/entries", params={"date": "2026-04-04", "metric_id": m["id"]},
            headers=auth_headers(user_b["token"]),
        )
        assert len(resp.json()) == 0
