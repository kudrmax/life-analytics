"""
Tests for /api/checkpoints — global measurement checkpoints CRUD.
"""
import pytest

from tests.conftest import auth_headers, register_user, create_checkpoint, create_metric, create_entry


@pytest.mark.asyncio
class TestListCheckpoints:
    async def test_list_empty(self, client, user_a):
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_returns_sorted(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Вечер")
        await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["label"] == "Вечер"
        assert data[1]["label"] == "Утро"

    async def test_list_returns_usage_count_zero(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        data = resp.json()
        assert data[0]["usage_count"] == 0

    async def test_list_returns_usage_count_with_metrics(self, client, user_a):
        checkpoint = await create_checkpoint(client, user_a["token"], "Утро")
        checkpoint2 = await create_checkpoint(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": checkpoint["id"]}, {"checkpoint_id": checkpoint2["id"]}],
        )
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        data = resp.json()
        usage = {c["label"]: c["usage_count"] for c in data}
        assert usage["Утро"] == 1
        assert usage["Вечер"] == 1

    async def test_list_returns_usage_metric_names(self, client, user_a):
        checkpoint = await create_checkpoint(client, user_a["token"], "Утро")
        checkpoint2 = await create_checkpoint(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="Настроение", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": checkpoint["id"]}, {"checkpoint_id": checkpoint2["id"]}],
        )
        await create_metric(
            client, user_a["token"],
            name="Энергия", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": checkpoint["id"]}, {"checkpoint_id": checkpoint2["id"]}],
        )
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        data = resp.json()
        names = {c["label"]: c["usage_metric_names"] for c in data}
        assert names["Утро"] == ["Настроение", "Энергия"]

    async def test_list_returns_empty_usage_metric_names(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        data = resp.json()
        assert data[0]["usage_metric_names"] == []

    async def test_list_disabled_checkpoint_not_counted_as_usage(self, client, user_a):
        """Disabled metric_checkpoints rows should not count as usage."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        cp_c = await create_checkpoint(client, user_a["token"], "Ночь")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}, {"checkpoint_id": cp_c["id"]}],
        )
        # Remove cp_c from metric (sets enabled=FALSE in metric_checkpoints)
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"checkpoint_configs": [{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        data = resp.json()
        usage = {c["label"]: c["usage_count"] for c in data}
        assert usage["Утро"] == 1
        assert usage["Вечер"] == 1
        assert usage["Ночь"] == 0  # disabled, should not count


@pytest.mark.asyncio
class TestCreateCheckpoint:
    async def test_create_success(self, client, user_a):
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "Утро"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Утро"
        assert "id" in data

    async def test_create_duplicate_label_conflict(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "утро"},  # case-insensitive
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_create_empty_label_fails(self, client, user_a):
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "  "},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestUpdateCheckpoint:
    async def test_rename_checkpoint(self, client, user_a):
        checkpoint = await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.patch(
            f"/api/checkpoints/{checkpoint['id']}",
            json={"label": "Рано утром"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "Рано утром"

    async def test_rename_to_duplicate_fails(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        resp = await client.patch(
            f"/api/checkpoints/{cp_b['id']}",
            json={"label": "Утро"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_rename_nonexistent(self, client, user_a):
        resp = await client.patch(
            "/api/checkpoints/99999",
            json={"label": "X"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDeleteCheckpoint:
    async def test_delete_unused_checkpoint(self, client, user_a):
        checkpoint = await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.delete(
            f"/api/checkpoints/{checkpoint['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        assert len(resp.json()) == 0

    async def test_delete_used_checkpoint_fails(self, client, user_a):
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}],
        )
        resp = await client.delete(
            f"/api/checkpoints/{cp_a['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409
        assert "используется" in resp.json()["detail"]

    async def test_delete_disabled_checkpoint_succeeds(self, client, user_a):
        """Checkpoint with only disabled metric_checkpoints rows should be deletable."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        cp_c = await create_checkpoint(client, user_a["token"], "Ночь")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}, {"checkpoint_id": cp_c["id"]}],
        )
        # Remove cp_c by updating metric with only cp_a and cp_b
        # This disables cp_c in metric_checkpoints (enabled=FALSE)
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"checkpoint_configs": [{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        # Now cp_c should be deletable (only has disabled metric_checkpoints row)
        resp = await client.delete(
            f"/api/checkpoints/{cp_c['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

    async def test_delete_checkpoint_with_old_entries(self, client, user_a):
        """Checkpoint with old entries should be soft-deletable (hidden but data preserved)."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")
        m = await create_metric(
            client, user_a["token"],
            name="Настроение", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}],
        )
        # Create entries with checkpoint references
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, checkpoint_id=cp_a["id"])
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", False, checkpoint_id=cp_b["id"])

        # Delete metric — metric_checkpoints cascade-deleted, but entries remain with checkpoint_id
        await client.delete(
            f"/api/metrics/{m['id']}",
            headers=auth_headers(user_a["token"]),
        )

        # Delete checkpoint — should succeed (soft delete, entries preserved)
        resp = await client.delete(
            f"/api/checkpoints/{cp_a['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Checkpoint should not appear in list
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        checkpoint_ids = [c["id"] for c in resp.json()]
        assert cp_a["id"] not in checkpoint_ids

    async def test_deleted_checkpoint_not_on_daily_page(self, client, user_a):
        """Soft-deleted checkpoint should not appear in daily page checkpoints."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")

        # Soft-delete cp_a
        resp = await client.delete(
            f"/api/checkpoints/{cp_a['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        checkpoints = resp.json().get("checkpoints", [])
        cp_ids = [c["id"] for c in checkpoints]
        assert cp_a["id"] not in cp_ids
        assert cp_b["id"] in cp_ids

    async def test_deleted_checkpoint_cannot_bind_to_metric(self, client, user_a):
        """Soft-deleted checkpoint should not be assignable to new metrics."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_a["token"], "Вечер")

        # Soft-delete cp_a
        await client.delete(
            f"/api/checkpoints/{cp_a['id']}",
            headers=auth_headers(user_a["token"]),
        )

        # Try to create metric with deleted checkpoint
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Test", "type": "bool",
                "checkpoint_configs": [{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_deleted_checkpoint_not_in_interval_binding(self, client, user_a):
        """Soft-deleted checkpoint should not be used for interval binding."""
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "Вечер")

        # Get interval before delete
        iv_resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(user_a["token"]))
        intervals = iv_resp.json()
        iv1 = intervals[0]

        # Soft-delete cp_a
        await client.delete(
            f"/api/checkpoints/{cp_a['id']}",
            headers=auth_headers(user_a["token"]),
        )

        # Try to create by_interval metric with interval referencing deleted checkpoint
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Test", "type": "bool",
                "interval_binding": "by_interval",
                "interval_ids": [iv1["id"]],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_recalculate_intervals_after_middle_delete(self, client, user_a):
        """Удаление среднего чекпоинта [A,B,C] → интервал A→C должен создаться."""
        cp_a = await create_checkpoint(client, user_a["token"], "A")
        cp_b = await create_checkpoint(client, user_a["token"], "B")
        cp_c = await create_checkpoint(client, user_a["token"], "C")

        # Before delete: intervals A→B, B→C
        iv_resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(user_a["token"]))
        assert len(iv_resp.json()) == 2

        # Delete middle checkpoint B
        resp = await client.delete(
            f"/api/checkpoints/{cp_b['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # After delete: interval A→C
        iv_resp2 = await client.get("/api/checkpoints/intervals", headers=auth_headers(user_a["token"]))
        intervals = iv_resp2.json()
        assert len(intervals) == 1
        assert intervals[0]["start_checkpoint_id"] == cp_a["id"]
        assert intervals[0]["end_checkpoint_id"] == cp_c["id"]

    async def test_delete_nonexistent(self, client, user_a):
        resp = await client.delete(
            "/api/checkpoints/99999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestReorderCheckpoints:
    async def test_reorder(self, client, user_a):
        c1 = await create_checkpoint(client, user_a["token"], "A")
        c2 = await create_checkpoint(client, user_a["token"], "B")
        c3 = await create_checkpoint(client, user_a["token"], "C")
        # Reverse order
        resp = await client.post(
            "/api/checkpoints/reorder",
            json=[
                {"id": c3["id"], "sort_order": 0},
                {"id": c2["id"], "sort_order": 10},
                {"id": c1["id"], "sort_order": 20},
            ],
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        labels = [c["label"] for c in resp.json()]
        assert labels == ["C", "B", "A"]


@pytest.mark.asyncio
class TestCheckpointDataIsolation:
    async def test_users_see_own_checkpoints(self, client):
        user_a = await register_user(client, "checkpoint_user_a")
        user_b = await register_user(client, "checkpoint_user_b")

        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_b["token"], "Вечер")

        resp_a = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        resp_b = await client.get("/api/checkpoints", headers=auth_headers(user_b["token"]))

        assert len(resp_a.json()) == 1
        assert resp_a.json()[0]["label"] == "Утро"
        assert len(resp_b.json()) == 1
        assert resp_b.json()[0]["label"] == "Вечер"

    async def test_user_cannot_update_others_checkpoint(self, client):
        user_a = await register_user(client, "owner_a")
        user_b = await register_user(client, "other_b")
        checkpoint = await create_checkpoint(client, user_a["token"], "My Checkpoint")

        resp = await client.patch(
            f"/api/checkpoints/{checkpoint['id']}",
            json={"label": "Hacked"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_user_cannot_delete_others_checkpoint(self, client):
        user_a = await register_user(client, "del_owner")
        user_b = await register_user(client, "del_other")
        checkpoint = await create_checkpoint(client, user_a["token"], "My Checkpoint")

        resp = await client.delete(
            f"/api/checkpoints/{checkpoint['id']}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_same_label_different_users(self, client):
        """Two users can have checkpoints with the same label."""
        user_a = await register_user(client, "dup_a")
        user_b = await register_user(client, "dup_b")
        cp_a = await create_checkpoint(client, user_a["token"], "Утро")
        cp_b = await create_checkpoint(client, user_b["token"], "Утро")
        assert cp_a["id"] != cp_b["id"]


@pytest.mark.asyncio
class TestMergeCheckpoints:
    async def test_merge_moves_metric_checkpoints(self, client, user_a):
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_a["token"], "Утро")
        extra = await create_checkpoint(client, user_a["token"], "День")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": source["id"]}, {"checkpoint_id": extra["id"]}],
        )
        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Verify metric now has target checkpoint instead of source
        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metric = next(x for x in metrics_resp.json() if x["id"] == m["id"])
        checkpoint_ids = [c["id"] for c in metric["checkpoints"]]
        assert target["id"] in checkpoint_ids
        assert source["id"] not in checkpoint_ids

    async def test_merge_moves_entries(self, client, user_a):
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": source["id"]}, {"checkpoint_id": target["id"]}],
        )
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, checkpoint_id=source["id"])

        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries_moved"] == 1

        # Verify entry is now on target checkpoint
        entries_resp = await client.get(
            f"/api/entries?date=2026-01-10&metric_id={m['id']}",
            headers=auth_headers(user_a["token"]),
        )
        entries = entries_resp.json()
        assert len(entries) == 1
        assert entries[0]["checkpoint_id"] == target["id"]

    async def test_merge_deletes_conflicting_entries(self, client, user_a):
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": source["id"]}, {"checkpoint_id": target["id"]}],
        )
        # Both checkpoints have entries for the same metric+date
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", False, checkpoint_id=source["id"])
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, checkpoint_id=target["id"])

        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries_deleted"] >= 1

        # Only the target entry survives
        entries_resp = await client.get(
            f"/api/entries?date=2026-01-10&metric_id={m['id']}",
            headers=auth_headers(user_a["token"]),
        )
        entries = entries_resp.json()
        assert len(entries) == 1
        assert entries[0]["value"] is True  # target's value preserved

    async def test_merge_deletes_source_checkpoint(self, client, user_a):
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_a["token"], "Утро")

        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        checkpoints_resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        checkpoint_ids = [c["id"] for c in checkpoints_resp.json()]
        assert source["id"] not in checkpoint_ids
        assert target["id"] in checkpoint_ids

    async def test_merge_duplicate_metric_checkpoint_handled(self, client, user_a):
        """If both checkpoints are on the same metric, the duplicate junction row is removed."""
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": source["id"]}, {"checkpoint_id": target["id"]}],
        )

        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Metric should have only target checkpoint (no duplicate)
        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metric = metrics_resp.json()[0]
        checkpoint_ids = [c["id"] for c in metric["checkpoints"]]
        assert checkpoint_ids == [target["id"]]

    async def test_merge_source_not_found(self, client, user_a):
        target = await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.post(
            f"/api/checkpoints/99999/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_merge_target_not_found(self, client, user_a):
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/99999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_merge_same_checkpoint(self, client, user_a):
        checkpoint = await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.post(
            f"/api/checkpoints/{checkpoint['id']}/merge/{checkpoint['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_merge_other_users_checkpoint(self, client, user_a):
        user_b = await register_user(client, "merge_other")
        source = await create_checkpoint(client, user_a["token"], "Вечер")
        target = await create_checkpoint(client, user_b["token"], "Утро")
        resp = await client.post(
            f"/api/checkpoints/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestCheckpointGlobalSortOrder:
    """Checkpoints attached to a metric must be returned in global sort_order
    (checkpoints.sort_order), not in metric_checkpoints.sort_order."""

    async def test_metric_checkpoints_follow_global_order(self, client, user_a):
        # Create global checkpoints: A(sort_order=0), B(1), C(2)
        cp_a = await create_checkpoint(client, user_a["token"], "A")
        cp_b = await create_checkpoint(client, user_a["token"], "B")
        cp_c = await create_checkpoint(client, user_a["token"], "C")

        # Attach in reverse order: C, A (metric_checkpoints.sort_order = 0 for C, 1 for A)
        metric = await create_metric(
            client, user_a["token"],
            name="Test", metric_type="bool",
            checkpoint_configs=[
                {"checkpoint_id": cp_c["id"]},
                {"checkpoint_id": cp_a["id"]},
            ],
        )

        # GET /api/metrics/{id} should return checkpoints in global order: A, C
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        checkpoints = resp.json()["checkpoints"]
        assert [c["label"] for c in checkpoints] == ["A", "C"]

    async def test_daily_checkpoints_follow_global_order(self, client, user_a):
        cp_a = await create_checkpoint(client, user_a["token"], "Morning")
        cp_b = await create_checkpoint(client, user_a["token"], "Evening")

        # Attach Evening first, then Morning
        metric = await create_metric(
            client, user_a["token"],
            name="Mood", metric_type="bool",
            checkpoint_configs=[
                {"checkpoint_id": cp_b["id"]},
                {"checkpoint_id": cp_a["id"]},
            ],
        )

        resp = await client.get(
            "/api/daily/2026-03-20",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        # Multi-checkpoint metrics are split into per-checkpoint items
        mood_items = [m for m in metrics if m["metric_id"] == metric["id"]]
        assert len(mood_items) == 2
        # Items should be in global checkpoint sort order: Morning, Evening
        checkpoint_labels = [item["checkpoints"][0]["label"] for item in mood_items]
        assert checkpoint_labels == ["Morning", "Evening"]
