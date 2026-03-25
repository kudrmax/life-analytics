"""API tests for interval binding feature."""

import pytest

from tests.conftest import auth_headers, create_entry, create_metric, create_slot


@pytest.mark.anyio
class TestIntervalBindingCreate:
    async def test_create_all_day_default(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        assert metric["interval_binding"] == "all_day"
        assert metric["interval_slot_ids"] is None

    async def test_create_by_interval_with_one_slot(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["slots"]) == 1

    async def test_create_by_interval_with_all_slots(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["slots"]) == 2


@pytest.mark.anyio
class TestIntervalBindingUpdate:
    async def test_switch_to_by_interval(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        metric = await create_metric(client, user_a["token"], name="Кофе", metric_type="bool")
        assert metric["interval_binding"] == "all_day"
        assert len(metric["slots"]) == 0

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_binding"] == "by_interval"
        assert len(data["slots"]) == 2

    async def test_switch_back_to_all_day(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["slots"]) == 1

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["interval_binding"] == "all_day"


@pytest.mark.anyio
class TestIntervalBindingValidation:
    async def test_by_interval_without_slot_ids_returns_400(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestIntervalLabelsInMetricsApi:
    async def test_single_slot_label_is_interval(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert len(data["slots"]) == 1
        assert data["slots"][0]["label"] == "Утро → День"

    async def test_multiple_slots_have_interval_labels(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        labels = [s["label"] for s in data["slots"]]
        assert "Утро → День" in labels
        assert "День → Вечер" in labels

    async def test_list_metrics_shows_interval_labels(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        metrics = resp.json()
        shower = [m for m in metrics if m["name"] == "Душ"][0]
        assert shower["slots"][0]["label"] == "Утро → День"

    async def test_assessment_keeps_checkpoint_label(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Настроение", "type": "scale", "scale_min": 1, "scale_max": 5,
                  "is_checkpoint": True, "slot_configs": [{"slot_id": s1["id"]}, {"slot_id": s2["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "all_day"
        labels = [s["label"] for s in data["slots"]]
        assert "Утро" in labels
        assert "День" in labels
        assert "Утро → День" not in labels


@pytest.mark.anyio
class TestIntervalDailyPage:
    async def test_daily_shows_interval_labels(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert len(coffee) == 2
        labels = [c["slots"][0]["label"] for c in coffee]
        assert "Утро → День" in labels
        assert "День → Вечер" in labels

    async def test_daily_interval_binding_field(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert coffee[0]["interval_binding"] == "by_interval"


@pytest.mark.anyio
class TestMultiIntervalCreate:
    async def test_create_by_interval_with_multiple_slots(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")
        s4 = await create_slot(client, user_a["token"], "Ночь")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s3["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["slots"]) == 2
        slot_ids = {s["id"] for s in data["slots"]}
        assert s1["id"] in slot_ids
        assert s3["id"] in slot_ids

    async def test_create_by_interval_with_all_intervals(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Шаги", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["slots"]) == 2


@pytest.mark.anyio
class TestMultiIntervalUpdate:
    async def test_update_add_interval(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["slots"]) == 1

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 2

    async def test_update_remove_interval(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["slots"]) == 2

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 1
        assert data["slots"][0]["id"] == s2["id"]

    async def test_update_change_intervals(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s2["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 1
        assert data["slots"][0]["id"] == s2["id"]


@pytest.mark.anyio
class TestMultiIntervalValidation:
    async def test_by_interval_empty_array_returns_400(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": []},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_invalid_slot_returns_400(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [99999]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_deleted_slot_returns_400(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        # Soft delete slot
        await client.delete(f"/api/slots/{s1['id']}", headers=auth_headers(user_a["token"]))

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_by_interval_duplicate_slots_ignored(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Вода", "type": "number", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"], s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["slots"]) == 1


@pytest.mark.anyio
class TestMultiIntervalDailyPage:
    async def test_daily_shows_only_selected_intervals(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert len(coffee) == 1
        assert coffee[0]["slots"][0]["label"] == "Утро → День"


@pytest.mark.anyio
class TestIntervalBindingChangeMigration:
    """Bug A + Bug B: entry visibility when interval_binding changes."""

    async def test_bug_a_no_entries_by_interval_to_all_day_shows_no_slots(self, client, user_a):
        """Bug A: after by_interval → all_day, daily page shows NO slot containers (no entries)."""
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        # Create metric as by_interval (no entries for the test date)
        resp = await client.post(
            "/api/metrics",
            json={"name": "Спорт", "type": "bool", "interval_binding": "by_interval",
                  "interval_slot_ids": [s1["id"]]},
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

        # Daily page: should show NO slot containers (slots properly disabled)
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        assert sport[0]["slots"] is None, "Slots should be None after switching back to all_day"
        assert sport[0]["entry"] is None

    async def test_bug_b_all_day_entry_visible_after_switch_to_by_interval(self, client, user_a):
        """Bug B: old all_day entry (slot_id=NULL) should remain visible after switching to by_interval."""
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        # Fill entry as all_day (slot_id=NULL)
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)

        # Change to by_interval → old entry should migrate to first slot
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Daily page: old entry should be visible (in first slot)
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        assert sport[0]["slots"] is not None
        assert sport[0]["slots"][0]["entry"] is not None, "Old all_day entry should be visible in first slot"
        assert sport[0]["slots"][0]["entry"]["value"] is True

    async def test_full_cycle_all_day_to_by_interval_to_all_day(self, client, user_a):
        """Full cycle: entry remains accessible through all binding changes."""
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        # Fill entry as all_day
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)

        # all_day → by_interval (entry migrates to first slot)
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        # by_interval → all_day
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Daily page: should show no slot containers, but entry still accessible via disabled-slot path
        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        sport = [m for m in metrics if m["name"] == "Спорт"]
        assert len(sport) == 1
        # After full cycle: slots are disabled, entry (now with slot_id=s1) should show via disabled-slot path
        # The metric renders with slots=[{slot_id: s1, entry: {value: True}}]
        # OR as a single entry depending on implementation
        # At minimum: the entry value must be accessible somewhere
        has_entry_in_slots = (
            sport[0]["slots"] is not None
            and any(s["entry"] is not None for s in sport[0]["slots"])
        )
        has_single_entry = sport[0]["entry"] is not None
        assert has_entry_in_slots or has_single_entry, "Entry should be accessible after full cycle"


@pytest.mark.anyio
class TestIntervalBindingUpdateNoMigration:
    async def test_update_category_does_not_remigrate_entries(self, client, user_a):
        """Bug: PATCH with same interval_slot_ids on already-by_interval metric caused 500
        when null-slot and slot entries existed for same date (UniqueViolationError)."""
        s1 = await create_slot(client, user_a["token"], "Утро")
        cat_resp = await client.post(
            "/api/categories",
            json={"name": "Тест"},
            headers=auth_headers(user_a["token"]),
        )
        cat = cat_resp.json()

        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        # Step 1: create all_day entry for date D
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", True)
        # Step 2: switch to by_interval → null entry migrated to s1 (slot_id=s1 now)
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "by_interval", "interval_slot_ids": [s1["id"]]},
            headers=auth_headers(user_a["token"]),
        )
        # Step 3: switch back to all_day
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        # Step 4: create a new all_day entry for same date D (slot_id=NULL)
        # Now DB has BOTH (date=D, slot_id=s1) AND (date=D, slot_id=NULL) for this metric
        await create_entry(client, user_a["token"], metric["id"], "2026-03-24", False)
        # Step 5: PATCH to by_interval again + category — frontend sends full form.
        # DB now has both (date=D, slot_id=s1) and (date=D, slot_id=NULL).
        # Before fix: migrate_null_slot_entries tries to move slot=NULL entry to s1,
        # but (date=D, slot_id=s1) already exists → 500 UniqueViolationError
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "category_id": cat["id"],
                "interval_binding": "by_interval",
                "interval_slot_ids": [s1["id"]],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
