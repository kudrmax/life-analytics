"""Tests for free_checkpoints feature — multiple entries per day at arbitrary times."""

from httpx import AsyncClient

from tests.conftest import auth_headers, create_entry, create_metric, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_free_cp_metric(
    client: AsyncClient, token: str, *, name: str = "Mood", metric_type: str = "scale",
    scale_min: int = 1, scale_max: int = 10, scale_step: int = 1,
) -> dict:
    payload: dict = {
        "name": name, "type": metric_type, "interval_binding": "free_checkpoints",
        "scale_min": scale_min, "scale_max": scale_max, "scale_step": scale_step,
    }
    resp = await client.post("/api/metrics", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create metric
# ---------------------------------------------------------------------------

class TestCreateFreeCheckpointMetric:
    async def test_create_scale_metric(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        assert m["interval_binding"] == "free_checkpoints"
        assert m["is_checkpoint"] is False

    async def test_create_bool_metric(self, client: AsyncClient, user_a: dict) -> None:
        payload = {"name": "Bool FC", "type": "bool", "interval_binding": "free_checkpoints"}
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201

    async def test_incompatible_with_is_checkpoint(self, client: AsyncClient, user_a: dict) -> None:
        payload = {
            "name": "Bad", "type": "scale", "interval_binding": "free_checkpoints",
            "is_checkpoint": True, "scale_min": 1, "scale_max": 10, "scale_step": 1,
        }
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_incompatible_with_computed(self, client: AsyncClient, user_a: dict) -> None:
        payload = {"name": "Bad", "type": "computed", "interval_binding": "free_checkpoints"}
        resp = await client.post("/api/metrics", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------

class TestFreeCheckpointEntries:
    async def test_create_multiple_entries_per_day(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        e1 = await create_entry(client, token, mid, date, 7)
        e2 = await create_entry(client, token, mid, date, 5)
        e3 = await create_entry(client, token, mid, date, 8)

        assert e1["id"] != e2["id"] != e3["id"]
        assert e1["is_free_checkpoint"] is True
        assert e2["is_free_checkpoint"] is True

    async def test_recorded_at_is_set(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        e = await create_entry(client, user_a["token"], m["id"], "2026-04-04", 5)
        assert e["recorded_at"] is not None
        assert e["recorded_at"] != ""

    async def test_checkpoint_id_forbidden(self, client: AsyncClient, user_a: dict) -> None:
        """Free checkpoint entries cannot have checkpoint_id."""
        m = await _create_free_cp_metric(client, user_a["token"])
        payload = {"metric_id": m["id"], "date": "2026-04-04", "value": 5, "checkpoint_id": 999}
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400


class TestFreeCheckpointEntryEdit:
    async def test_update_value(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        e = await create_entry(client, user_a["token"], m["id"], "2026-04-04", 7)

        resp = await client.put(
            f"/api/entries/{e['id']}", json={"value": 3},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == 3

    async def test_update_time(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        e = await create_entry(client, user_a["token"], m["id"], "2026-04-04", 7)

        resp = await client.patch(
            f"/api/entries/{e['id']}/time", json={"recorded_at": "14:30"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert "14:30" in resp.json()["recorded_at"]

    async def test_update_time_non_free_cp_fails(self, client: AsyncClient, user_a: dict) -> None:
        """Cannot update time for non-free_checkpoint entries."""
        m = await create_metric(client, user_a["token"], name="Normal", metric_type="scale",
                                scale_min=1, scale_max=10, scale_step=1)
        e = await create_entry(client, user_a["token"], m["id"], "2026-04-04", 5)

        resp = await client.patch(
            f"/api/entries/{e['id']}/time", json={"recorded_at": "14:30"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


class TestFreeCheckpointEntryDelete:
    async def test_delete_individual_entry(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]

        e1 = await create_entry(client, token, mid, "2026-04-04", 7)
        e2 = await create_entry(client, token, mid, "2026-04-04", 5)

        resp = await client.delete(f"/api/entries/{e1['id']}", headers=auth_headers(token))
        assert resp.status_code == 204

        # e2 still exists
        entries_resp = await client.get(
            "/api/entries", params={"date": "2026-04-04", "metric_id": mid},
            headers=auth_headers(token),
        )
        assert len(entries_resp.json()) == 1
        assert entries_resp.json()[0]["id"] == e2["id"]


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

class TestFreeCheckpointDaily:
    async def test_daily_contains_free_entries(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        await create_entry(client, token, mid, date, 7)
        await create_entry(client, token, mid, date, 5)

        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        assert resp.status_code == 200
        data = resp.json()

        metric_item = next(item for item in data["metrics"] if item["metric_id"] == mid)
        assert metric_item["free_entries"] is not None
        assert len(metric_item["free_entries"]) == 2
        assert metric_item["entry"] is None

    async def test_free_entries_sorted_by_time(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        token = user_a["token"]
        mid = m["id"]
        date = "2026-04-04"

        e1 = await create_entry(client, token, mid, date, 7)
        e2 = await create_entry(client, token, mid, date, 5)

        # Update time so e1 is after e2
        await client.patch(f"/api/entries/{e1['id']}/time", json={"recorded_at": "18:00"},
                           headers=auth_headers(token))
        await client.patch(f"/api/entries/{e2['id']}/time", json={"recorded_at": "14:00"},
                           headers=auth_headers(token))

        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        metric_item = next(item for item in resp.json()["metrics"] if item["metric_id"] == mid)
        fe = metric_item["free_entries"]
        assert fe[0]["id"] == e2["id"]  # 14:00 first
        assert fe[1]["id"] == e1["id"]  # 18:00 second


class TestFreeCheckpointProgress:
    async def test_filled_with_at_least_one_entry(self, client: AsyncClient, user_a: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        token = user_a["token"]
        date = "2026-04-04"

        # No entries yet — not filled
        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        progress = resp.json()["progress"]
        assert progress["filled"] == 0

        # Add one entry
        await create_entry(client, token, m["id"], date, 7)
        resp = await client.get(f"/api/daily/{date}", headers=auth_headers(token))
        progress = resp.json()["progress"]
        assert progress["filled"] >= 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestFreeCheckpointValidation:
    async def test_regular_metric_still_unique_per_day(self, client: AsyncClient, user_a: dict) -> None:
        """Non-free_checkpoint metrics should still prevent duplicates."""
        m = await create_metric(client, user_a["token"], name="Regular", metric_type="scale",
                                scale_min=1, scale_max=10, scale_step=1)
        token = user_a["token"]
        await create_entry(client, token, m["id"], "2026-04-04", 5)

        # Second entry same day should fail
        payload = {"metric_id": m["id"], "date": "2026-04-04", "value": 7}
        resp = await client.post("/api/entries", json=payload, headers=auth_headers(token))
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestFreeCheckpointDataIsolation:
    async def test_entries_not_visible_to_other_user(self, client: AsyncClient, user_a: dict, user_b: dict) -> None:
        m = await _create_free_cp_metric(client, user_a["token"])
        await create_entry(client, user_a["token"], m["id"], "2026-04-04", 7)

        # user_b should not see user_a's entries
        resp = await client.get(
            "/api/entries", params={"date": "2026-04-04", "metric_id": m["id"]},
            headers=auth_headers(user_b["token"]),
        )
        assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# Auto-sources (unit test for registry)
# ---------------------------------------------------------------------------

class TestFreeCheckpointAutoSources:
    def test_free_cp_max(self) -> None:
        from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
        from app.source_key import AutoSourceType

        inp = AutoSourceInput(
            all_dates=["2026-04-04", "2026-04-05"],
            raw_data={"2026-04-04": [3.0, 7.0, 5.0], "2026-04-05": [2.0, 9.0]},
        )
        result = compute_auto_source(AutoSourceType.FREE_CP_MAX, inp)
        assert result["2026-04-04"] == 7.0
        assert result["2026-04-05"] == 9.0

    def test_free_cp_min(self) -> None:
        from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
        from app.source_key import AutoSourceType

        inp = AutoSourceInput(
            all_dates=["2026-04-04"],
            raw_data={"2026-04-04": [3.0, 7.0, 5.0]},
        )
        result = compute_auto_source(AutoSourceType.FREE_CP_MIN, inp)
        assert result["2026-04-04"] == 3.0

    def test_free_cp_range(self) -> None:
        from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
        from app.source_key import AutoSourceType

        inp = AutoSourceInput(
            all_dates=["2026-04-04", "2026-04-05"],
            raw_data={
                "2026-04-04": [3.0, 7.0, 5.0],  # range = 4.0
                "2026-04-05": [2.0],  # only 1 entry, no range
            },
        )
        result = compute_auto_source(AutoSourceType.FREE_CP_RANGE, inp)
        assert result["2026-04-04"] == 4.0
        assert "2026-04-05" not in result  # need >= 2 entries

    def test_free_cp_max_empty(self) -> None:
        from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
        from app.source_key import AutoSourceType

        inp = AutoSourceInput(all_dates=[], raw_data=None)
        result = compute_auto_source(AutoSourceType.FREE_CP_MAX, inp)
        assert result == {}
