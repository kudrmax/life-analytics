"""
Tests for /api/slots — global measurement slots CRUD.
"""
import pytest

from tests.conftest import auth_headers, register_user, create_slot, create_metric, create_entry


@pytest.mark.asyncio
class TestListSlots:
    async def test_list_empty(self, client, user_a):
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_returns_sorted(self, client, user_a):
        await create_slot(client, user_a["token"], "Вечер")
        await create_slot(client, user_a["token"], "Утро")
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["label"] == "Вечер"
        assert data[1]["label"] == "Утро"

    async def test_list_returns_usage_count_zero(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        data = resp.json()
        assert data[0]["usage_count"] == 0

    async def test_list_returns_usage_count_with_metrics(self, client, user_a):
        slot = await create_slot(client, user_a["token"], "Утро")
        slot2 = await create_slot(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": slot["id"]}, {"slot_id": slot2["id"]}],
        )
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        data = resp.json()
        usage = {s["label"]: s["usage_count"] for s in data}
        assert usage["Утро"] == 1
        assert usage["Вечер"] == 1

    async def test_list_returns_usage_metric_names(self, client, user_a):
        slot = await create_slot(client, user_a["token"], "Утро")
        slot2 = await create_slot(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="Настроение", metric_type="bool",
            slot_configs=[{"slot_id": slot["id"]}, {"slot_id": slot2["id"]}],
        )
        await create_metric(
            client, user_a["token"],
            name="Энергия", metric_type="bool",
            slot_configs=[{"slot_id": slot["id"]}, {"slot_id": slot2["id"]}],
        )
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        data = resp.json()
        names = {s["label"]: s["usage_metric_names"] for s in data}
        assert names["Утро"] == ["Настроение", "Энергия"]

    async def test_list_returns_empty_usage_metric_names(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        data = resp.json()
        assert data[0]["usage_metric_names"] == []

    async def test_list_disabled_slot_not_counted_as_usage(self, client, user_a):
        """Disabled metric_slots rows should not count as usage."""
        slot_a = await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_a["token"], "Вечер")
        slot_c = await create_slot(client, user_a["token"], "Ночь")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}, {"slot_id": slot_c["id"]}],
        )
        # Remove slot_c from metric (sets enabled=FALSE in metric_slots)
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"slot_configs": [{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        data = resp.json()
        usage = {s["label"]: s["usage_count"] for s in data}
        assert usage["Утро"] == 1
        assert usage["Вечер"] == 1
        assert usage["Ночь"] == 0  # disabled, should not count


@pytest.mark.asyncio
class TestCreateSlot:
    async def test_create_success(self, client, user_a):
        resp = await client.post(
            "/api/slots",
            json={"label": "Утро"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Утро"
        assert "id" in data

    async def test_create_duplicate_label_conflict(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        resp = await client.post(
            "/api/slots",
            json={"label": "утро"},  # case-insensitive
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_create_empty_label_fails(self, client, user_a):
        resp = await client.post(
            "/api/slots",
            json={"label": "  "},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestUpdateSlot:
    async def test_rename_slot(self, client, user_a):
        slot = await create_slot(client, user_a["token"], "Утро")
        resp = await client.patch(
            f"/api/slots/{slot['id']}",
            json={"label": "Рано утром"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "Рано утром"

    async def test_rename_to_duplicate_fails(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_a["token"], "Вечер")
        resp = await client.patch(
            f"/api/slots/{slot_b['id']}",
            json={"label": "Утро"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_rename_nonexistent(self, client, user_a):
        resp = await client.patch(
            "/api/slots/99999",
            json={"label": "X"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDeleteSlot:
    async def test_delete_unused_slot(self, client, user_a):
        slot = await create_slot(client, user_a["token"], "Утро")
        resp = await client.delete(
            f"/api/slots/{slot['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        assert len(resp.json()) == 0

    async def test_delete_used_slot_fails(self, client, user_a):
        slot_a = await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_a["token"], "Вечер")
        await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        resp = await client.delete(
            f"/api/slots/{slot_a['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409
        assert "используется" in resp.json()["detail"]

    async def test_delete_disabled_slot_succeeds(self, client, user_a):
        """Slot with only disabled metric_slots rows should be deletable."""
        slot_a = await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_a["token"], "Вечер")
        slot_c = await create_slot(client, user_a["token"], "Ночь")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}, {"slot_id": slot_c["id"]}],
        )
        # Remove slot_c by updating metric with only slot_a and slot_b
        # This disables slot_c in metric_slots (enabled=FALSE)
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"slot_configs": [{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        # Now slot_c should be deletable (only has disabled metric_slots row)
        resp = await client.delete(
            f"/api/slots/{slot_c['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

    async def test_delete_slot_with_old_entries(self, client, user_a):
        """Slot with old entries should be soft-deletable (hidden but data preserved)."""
        slot_a = await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_a["token"], "Вечер")
        m = await create_metric(
            client, user_a["token"],
            name="Настроение", metric_type="bool",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        # Create entries with slot references
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, slot_id=slot_a["id"])
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", False, slot_id=slot_b["id"])

        # Delete metric — metric_slots cascade-deleted, but entries remain with slot_id
        await client.delete(
            f"/api/metrics/{m['id']}",
            headers=auth_headers(user_a["token"]),
        )

        # Delete slot — should succeed (soft delete, entries preserved)
        resp = await client.delete(
            f"/api/slots/{slot_a['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Slot should not appear in list
        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        slot_ids = [s["id"] for s in resp.json()]
        assert slot_a["id"] not in slot_ids

    async def test_delete_nonexistent(self, client, user_a):
        resp = await client.delete(
            "/api/slots/99999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestReorderSlots:
    async def test_reorder(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "A")
        s2 = await create_slot(client, user_a["token"], "B")
        s3 = await create_slot(client, user_a["token"], "C")
        # Reverse order
        resp = await client.post(
            "/api/slots/reorder",
            json=[
                {"id": s3["id"], "sort_order": 0},
                {"id": s2["id"], "sort_order": 10},
                {"id": s1["id"], "sort_order": 20},
            ],
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        labels = [s["label"] for s in resp.json()]
        assert labels == ["C", "B", "A"]


@pytest.mark.asyncio
class TestSlotDataIsolation:
    async def test_users_see_own_slots(self, client):
        user_a = await register_user(client, "slot_user_a")
        user_b = await register_user(client, "slot_user_b")

        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_b["token"], "Вечер")

        resp_a = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        resp_b = await client.get("/api/slots", headers=auth_headers(user_b["token"]))

        assert len(resp_a.json()) == 1
        assert resp_a.json()[0]["label"] == "Утро"
        assert len(resp_b.json()) == 1
        assert resp_b.json()[0]["label"] == "Вечер"

    async def test_user_cannot_update_others_slot(self, client):
        user_a = await register_user(client, "owner_a")
        user_b = await register_user(client, "other_b")
        slot = await create_slot(client, user_a["token"], "My Slot")

        resp = await client.patch(
            f"/api/slots/{slot['id']}",
            json={"label": "Hacked"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_user_cannot_delete_others_slot(self, client):
        user_a = await register_user(client, "del_owner")
        user_b = await register_user(client, "del_other")
        slot = await create_slot(client, user_a["token"], "My Slot")

        resp = await client.delete(
            f"/api/slots/{slot['id']}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_same_label_different_users(self, client):
        """Two users can have slots with the same label."""
        user_a = await register_user(client, "dup_a")
        user_b = await register_user(client, "dup_b")
        slot_a = await create_slot(client, user_a["token"], "Утро")
        slot_b = await create_slot(client, user_b["token"], "Утро")
        assert slot_a["id"] != slot_b["id"]


@pytest.mark.asyncio
class TestMergeSlots:
    async def test_merge_moves_metric_slots(self, client, user_a):
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_a["token"], "Утро")
        extra = await create_slot(client, user_a["token"], "День")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": source["id"]}, {"slot_id": extra["id"]}],
        )
        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Verify metric now has target slot instead of source
        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metric = next(x for x in metrics_resp.json() if x["id"] == m["id"])
        slot_ids = [s["id"] for s in metric["slots"]]
        assert target["id"] in slot_ids
        assert source["id"] not in slot_ids

    async def test_merge_moves_entries(self, client, user_a):
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": source["id"]}, {"slot_id": target["id"]}],
        )
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, slot_id=source["id"])

        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries_moved"] == 1

        # Verify entry is now on target slot
        entries_resp = await client.get(
            f"/api/entries?date=2026-01-10&metric_id={m['id']}",
            headers=auth_headers(user_a["token"]),
        )
        entries = entries_resp.json()
        assert len(entries) == 1
        assert entries[0]["slot_id"] == target["id"]

    async def test_merge_deletes_conflicting_entries(self, client, user_a):
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": source["id"]}, {"slot_id": target["id"]}],
        )
        # Both slots have entries for the same metric+date
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", False, slot_id=source["id"])
        await create_entry(client, user_a["token"], m["id"], "2026-01-10", True, slot_id=target["id"])

        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
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

    async def test_merge_deletes_source_slot(self, client, user_a):
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_a["token"], "Утро")

        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        slots_resp = await client.get("/api/slots", headers=auth_headers(user_a["token"]))
        slot_ids = [s["id"] for s in slots_resp.json()]
        assert source["id"] not in slot_ids
        assert target["id"] in slot_ids

    async def test_merge_duplicate_metric_slot_handled(self, client, user_a):
        """If both slots are on the same metric, the duplicate junction row is removed."""
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_a["token"], "Утро")
        m = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            slot_configs=[{"slot_id": source["id"]}, {"slot_id": target["id"]}],
        )

        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Metric should have only target slot (no duplicate)
        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metric = metrics_resp.json()[0]
        slot_ids = [s["id"] for s in metric["slots"]]
        assert slot_ids == [target["id"]]

    async def test_merge_source_not_found(self, client, user_a):
        target = await create_slot(client, user_a["token"], "Утро")
        resp = await client.post(
            f"/api/slots/99999/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_merge_target_not_found(self, client, user_a):
        source = await create_slot(client, user_a["token"], "Вечер")
        resp = await client.post(
            f"/api/slots/{source['id']}/merge/99999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_merge_same_slot(self, client, user_a):
        slot = await create_slot(client, user_a["token"], "Утро")
        resp = await client.post(
            f"/api/slots/{slot['id']}/merge/{slot['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_merge_other_users_slot(self, client, user_a):
        user_b = await register_user(client, "merge_other")
        source = await create_slot(client, user_a["token"], "Вечер")
        target = await create_slot(client, user_b["token"], "Утро")
        resp = await client.post(
            f"/api/slots/{source['id']}/merge/{target['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestSlotGlobalSortOrder:
    """Slots attached to a metric must be returned in global sort_order
    (measurement_slots.sort_order), not in metric_slots.sort_order."""

    async def test_metric_slots_follow_global_order(self, client, user_a):
        # Create global slots: A(sort_order=0), B(1), C(2)
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        slot_c = await create_slot(client, user_a["token"], "C")

        # Attach in reverse order: C, A (metric_slots.sort_order = 0 for C, 1 for A)
        metric = await create_metric(
            client, user_a["token"],
            name="Test", metric_type="bool",
            slot_configs=[
                {"slot_id": slot_c["id"]},
                {"slot_id": slot_a["id"]},
            ],
        )

        # GET /api/metrics/{id} should return slots in global order: A, C
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        slots = resp.json()["slots"]
        assert [s["label"] for s in slots] == ["A", "C"]

    async def test_daily_slots_follow_global_order(self, client, user_a):
        slot_a = await create_slot(client, user_a["token"], "Morning")
        slot_b = await create_slot(client, user_a["token"], "Evening")

        # Attach Evening first, then Morning
        metric = await create_metric(
            client, user_a["token"],
            name="Mood", metric_type="bool",
            slot_configs=[
                {"slot_id": slot_b["id"]},
                {"slot_id": slot_a["id"]},
            ],
        )

        resp = await client.get(
            "/api/daily/2026-03-20",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        # Multi-slot metrics are split into per-checkpoint items
        mood_items = [m for m in metrics if m["metric_id"] == metric["id"]]
        assert len(mood_items) == 2
        # Items should be in global slot sort order: Morning, Evening
        slot_labels = [item["slots"][0]["label"] for item in mood_items]
        assert slot_labels == ["Morning", "Evening"]
