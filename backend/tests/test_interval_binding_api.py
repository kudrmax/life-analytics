"""API tests for interval binding feature."""

import pytest

from tests.conftest import auth_headers, create_metric, create_slot


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
