"""API integration tests for the entries router (CRUD on /api/entries)."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_checkpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_enum_metric(
    client: AsyncClient, token: str, *, name: str = "Mood",
) -> dict:
    """Create an enum metric with options, return full metric dict."""
    resp = await client.post(
        "/api/metrics",
        json={"name": name, "type": "enum", "enum_options": ["Good", "Bad", "Meh"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create entry
# ---------------------------------------------------------------------------

class TestCreateEntry:

    async def test_create_bool_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Bool", metric_type="bool",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", True,
        )
        assert entry["metric_id"] == metric["id"]
        assert entry["date"] == "2026-03-01"
        assert entry["value"] is True

    async def test_create_number_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Steps", metric_type="number",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", 42,
        )
        assert entry["value"] == 42

    async def test_create_time_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Wake up", metric_type="time",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", "14:30",
        )
        # Time values come back as ISO timestamps; verify the time portion
        assert "14:30" in entry["value"]

    async def test_create_scale_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Energy", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=1,
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", 7,
        )
        assert entry["value"] == 7

    async def test_create_duration_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Sleep", metric_type="duration",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", 90,
        )
        assert entry["value"] == 90

    async def test_create_enum_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await _create_enum_metric(client, user_a["token"])
        options = metric["enum_options"]
        assert len(options) >= 2
        option_id = options[0]["id"]

        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", [option_id],
        )
        assert entry["value"] == [option_id]

    async def test_create_entry_with_checkpoint(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        cp_m = await create_checkpoint(client, user_a["token"], "Morning")
        cp_e = await create_checkpoint(client, user_a["token"], "Evening")
        metric = await create_metric(
            client, user_a["token"], name="Mood Checkpoints", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_m["id"]}, {"checkpoint_id": cp_e["id"]}],
        )
        checkpoints = metric["checkpoints"]
        assert len(checkpoints) == 2

        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", True,
            checkpoint_id=checkpoints[0]["id"],
        )
        assert entry["checkpoint_id"] == checkpoints[0]["id"]
        assert entry["value"] is True

    async def test_duplicate_entry_conflict(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Dup", metric_type="bool",
        )
        await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", True,
        )
        resp = await client.post(
            "/api/entries",
            json={"metric_id": metric["id"], "date": "2026-03-01", "value": False},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_create_entry_nonexistent_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/entries",
            json={"metric_id": 999999, "date": "2026-03-01", "value": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List entries
# ---------------------------------------------------------------------------

class TestListEntries:

    async def test_list_by_date(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(
            client, user_a["token"], name="M1", metric_type="bool",
        )
        m2 = await create_metric(
            client, user_a["token"], name="M2", metric_type="number",
        )
        await create_entry(client, user_a["token"], m1["id"], "2026-03-10", True)
        await create_entry(client, user_a["token"], m2["id"], "2026-03-10", 5)
        # Entry on a different date — must not appear
        await create_entry(client, user_a["token"], m1["id"], "2026-03-11", False)

        resp = await client.get(
            "/api/entries",
            params={"date": "2026-03-10"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        metric_ids = {e["metric_id"] for e in data}
        assert metric_ids == {m1["id"], m2["id"]}

    async def test_list_by_date_and_metric_id(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(
            client, user_a["token"], name="Filtered1", metric_type="bool",
        )
        m2 = await create_metric(
            client, user_a["token"], name="Filtered2", metric_type="bool",
        )
        await create_entry(client, user_a["token"], m1["id"], "2026-03-10", True)
        await create_entry(client, user_a["token"], m2["id"], "2026-03-10", False)

        resp = await client.get(
            "/api/entries",
            params={"date": "2026-03-10", "metric_id": m1["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["metric_id"] == m1["id"]


# ---------------------------------------------------------------------------
# Update entry
# ---------------------------------------------------------------------------

class TestUpdateEntry:

    async def test_update_value(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Upd", metric_type="number",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", 10,
        )
        resp = await client.put(
            f"/api/entries/{entry['id']}",
            json={"value": 99},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == 99

    async def test_update_nonexistent_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.put(
            "/api/entries/999999",
            json={"value": 1},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete entry
# ---------------------------------------------------------------------------

class TestDeleteEntry:

    async def test_delete_existing(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Del", metric_type="bool",
        )
        entry = await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", True,
        )
        resp = await client.delete(
            f"/api/entries/{entry['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp2 = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp2.status_code == 200
        assert all(e["id"] != entry["id"] for e in resp2.json())

    async def test_delete_nonexistent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.delete(
            "/api/entries/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Data isolation between users
# ---------------------------------------------------------------------------

class TestDataIsolation:

    async def test_user_cannot_see_other_entries(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="Private", metric_type="bool",
        )
        await create_entry(
            client, user_a["token"], metric_a["id"], "2026-03-01", True,
        )

        # user_b listing the same date must not see user_a's entry
        resp = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    async def test_user_cannot_update_other_entry(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="IsoUpd", metric_type="number",
        )
        entry = await create_entry(
            client, user_a["token"], metric_a["id"], "2026-03-01", 10,
        )

        resp = await client.put(
            f"/api/entries/{entry['id']}",
            json={"value": 999},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_user_cannot_delete_other_entry(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="IsoDel", metric_type="bool",
        )
        entry = await create_entry(
            client, user_a["token"], metric_a["id"], "2026-03-01", True,
        )

        resp = await client.delete(
            f"/api/entries/{entry['id']}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

        # Verify entry still exists for user_a
        resp2 = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp2.status_code == 200
        ids = [e["id"] for e in resp2.json()]
        assert entry["id"] in ids


class TestEntryExclusiveConstraint:
    """Entry не может иметь одновременно checkpoint_id и interval_id."""

    async def test_entry_with_both_checkpoint_and_interval_rejected(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Попытка создать entry с обоими binding даёт ошибку."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        # Get interval
        iv_resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(user_a["token"]))
        iv = iv_resp.json()[0]

        metric = await create_metric(
            client, user_a["token"], name="Test", metric_type="number",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}],
        )
        resp = await client.post(
            "/api/entries",
            json={"metric_id": metric["id"], "date": "2026-03-01", "value": 42,
                  "checkpoint_id": cp_a["id"], "interval_id": iv["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code in (400, 422), f"Expected 400/422, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------

class TestDateRange:

    async def test_date_range_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.get(
            "/api/entries/date-range",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["min_date"] is None
        assert data["max_date"] is None

    async def test_date_range_with_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="DR", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2025-06-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-15", True)
        await create_entry(client, user_a["token"], metric["id"], "2025-09-10", True)

        resp = await client.get(
            "/api/entries/date-range",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["min_date"] == "2025-06-01"
        assert data["max_date"] == "2026-01-15"

    async def test_date_range_isolation(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="DR-A", metric_type="bool",
        )
        metric_b = await create_metric(
            client, user_b["token"], name="DR-B", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric_a["id"], "2025-03-01", True)
        await create_entry(client, user_b["token"], metric_b["id"], "2024-01-01", True)

        resp = await client.get(
            "/api/entries/date-range",
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["min_date"] == "2025-03-01"
        assert data["max_date"] == "2025-03-01"
