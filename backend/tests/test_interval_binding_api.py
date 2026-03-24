"""API tests for interval binding feature (Phase 2)."""

import pytest

from tests.conftest import auth_headers, create_metric, create_slot


@pytest.mark.anyio
class TestIntervalBindingCreate:
    async def test_create_daily_default(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        assert metric["interval_binding"] == "daily"
        assert metric["interval_start_slot_id"] is None

    async def test_create_floating(self, client, user_a):
        # Create checkpoints first
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")
        s3 = await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "floating"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "floating"
        # Should have 2 slots (N-1 intervals for 3 checkpoints)
        assert len(data["slots"]) == 2

    async def test_create_fixed(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "fixed",
                  "interval_start_slot_id": s1["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["interval_binding"] == "fixed"
        assert data["interval_start_slot_id"] == s1["id"]
        assert len(data["slots"]) == 1


@pytest.mark.anyio
class TestIntervalBindingUpdate:
    async def test_switch_to_floating(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")
        await create_slot(client, user_a["token"], "Вечер")

        metric = await create_metric(client, user_a["token"], name="Кофе", metric_type="bool")
        assert metric["interval_binding"] == "daily"
        assert len(metric["slots"]) == 0

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "floating"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["interval_binding"] == "floating"
        assert len(data["slots"]) == 2

    async def test_switch_back_to_daily(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "floating"},
            headers=auth_headers(user_a["token"]),
        )
        metric = resp.json()
        assert len(metric["slots"]) == 1

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"interval_binding": "daily"},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["interval_binding"] == "daily"


@pytest.mark.anyio
class TestIntervalBindingValidation:
    async def test_fixed_without_slot_id_returns_400(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "fixed"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestIntervalLabelsInMetricsApi:
    async def test_fixed_slot_label_is_interval(self, client, user_a):
        s1 = await create_slot(client, user_a["token"], "Утро")
        s2 = await create_slot(client, user_a["token"], "День")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "fixed",
                  "interval_start_slot_id": s1["id"]},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert len(data["slots"]) == 1
        assert data["slots"][0]["label"] == "Утро → День"

    async def test_floating_slots_have_interval_labels(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")
        await create_slot(client, user_a["token"], "Вечер")

        resp = await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "floating"},
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
            json={"name": "Душ", "type": "bool", "interval_binding": "fixed",
                  "interval_start_slot_id": s1["id"]},
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
        assert data["interval_binding"] == "daily"
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
            json={"name": "Кофе", "type": "bool", "interval_binding": "floating"},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        # Multi-slot metrics are now split into per-checkpoint items
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert len(coffee) == 2
        # Each item has one slot with interval label
        labels = [c["slots"][0]["label"] for c in coffee]
        assert "Утро → День" in labels
        assert "День → Вечер" in labels

    async def test_daily_interval_binding_field(self, client, user_a):
        await create_slot(client, user_a["token"], "Утро")
        await create_slot(client, user_a["token"], "День")

        await client.post(
            "/api/metrics",
            json={"name": "Кофе", "type": "bool", "interval_binding": "floating"},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/daily/2026-03-24", headers=auth_headers(user_a["token"]))
        metrics = resp.json()["metrics"]
        coffee = [m for m in metrics if m["name"] == "Кофе"]
        assert coffee[0]["interval_binding"] == "floating"
