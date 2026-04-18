"""API tests for checkpoint feature: checkpoint description and metric is_checkpoint."""

from tests.conftest import auth_headers, create_metric, create_checkpoint


class TestCheckpointDescription:
    async def test_create_with_description(self, client, user_a):
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "Утро", "description": "Сразу после пробуждения"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["description"] == "Сразу после пробуждения"

    async def test_create_without_description(self, client, user_a):
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "Утро"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["description"] is None

    async def test_update_description(self, client, user_a):
        cp = await create_checkpoint(client, user_a["token"], "Утро")
        resp = await client.patch(
            f"/api/checkpoints/{cp['id']}",
            json={"description": "После завтрака"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "После завтрака"

    async def test_clear_description(self, client, user_a):
        resp = await client.post(
            "/api/checkpoints",
            json={"label": "Утро", "description": "Начало дня"},
            headers=auth_headers(user_a["token"]),
        )
        cp_id = resp.json()["id"]
        resp = await client.patch(
            f"/api/checkpoints/{cp_id}",
            json={"description": ""},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] is None

    async def test_list_includes_description(self, client, user_a):
        await client.post(
            "/api/checkpoints",
            json={"label": "Утро", "description": "Описание 1"},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        checkpoints = resp.json()
        assert any(cp["description"] == "Описание 1" for cp in checkpoints)


class TestMetricIsCheckpoint:
    async def test_create_with_is_checkpoint(self, client, user_a):
        resp = await client.post(
            "/api/metrics",
            json={"name": "Настроение", "type": "scale", "scale_min": 1, "scale_max": 10, "scale_step": 1, "is_checkpoint": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["is_checkpoint"] is True

    async def test_create_default_false(self, client, user_a):
        resp = await client.post(
            "/api/metrics",
            json={"name": "Спорт", "type": "bool"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["is_checkpoint"] is False

    async def test_update_is_checkpoint(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Настроение", metric_type="scale",
                                     scale_min=1, scale_max=10, scale_step=1)
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"is_checkpoint": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["is_checkpoint"] is True

    async def test_list_includes_is_checkpoint(self, client, user_a):
        await client.post(
            "/api/metrics",
            json={"name": "Энергия", "type": "scale", "scale_min": 1, "scale_max": 5, "scale_step": 1, "is_checkpoint": True},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        metrics = resp.json()
        energy = [m for m in metrics if m["name"] == "Энергия"]
        assert len(energy) == 1
        assert energy[0]["is_checkpoint"] is True

    async def test_get_single_includes_is_checkpoint(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Тест", metric_type="bool")
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert "is_checkpoint" in resp.json()
