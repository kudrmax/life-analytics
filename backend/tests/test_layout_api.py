"""API tests for daily layout ordering."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, create_metric, create_checkpoint


async def _get_layout(client: AsyncClient, token: str) -> dict:
    resp = await client.get("/api/layout", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()


async def _get_intervals(client: AsyncClient, token: str) -> list[dict]:
    resp = await client.get("/api/checkpoints/intervals", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.anyio
class TestLayoutSeedOnCheckpointCreate:
    """Creating checkpoints adds checkpoint + interval blocks to layout."""

    async def test_create_checkpoints_populates_layout(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        data = await _get_layout(client, user_a["token"])
        blocks = data["blocks"]
        types = [b["type"] for b in blocks]
        assert "checkpoint" in types
        assert "interval" in types

    async def test_checkpoint_block_count_matches(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        await create_checkpoint(client, user_a["token"], "Вечер")

        data = await _get_layout(client, user_a["token"])
        cp_blocks = [b for b in data["blocks"] if b["type"] == "checkpoint"]
        iv_blocks = [b for b in data["blocks"] if b["type"] == "interval"]
        assert len(cp_blocks) == 3
        assert len(iv_blocks) == 2  # Утро→День, День→Вечер


@pytest.mark.anyio
class TestLayoutSeedOnMetricCreate:
    """Creating standalone metrics adds them to layout."""

    async def test_standalone_metric_added_to_layout(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert any(b["id"] == metric["id"] for b in metric_blocks)

    async def test_metric_with_category_adds_category_block(self, client, user_a):
        resp = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        cat_id = resp.json()["category_id"]

        data = await _get_layout(client, user_a["token"])
        cat_blocks = [b for b in data["blocks"] if b["type"] == "category"]
        assert any(b["id"] == cat_id for b in cat_blocks)

    async def test_bound_metric_not_in_layout_as_standalone(self, client, user_a):
        """Metric bound to checkpoints should NOT appear as standalone block."""
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
        metric_id = resp.json()["id"]

        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert not any(b["id"] == metric_id for b in metric_blocks)


@pytest.mark.anyio
class TestLayoutOnDelete:
    """Deleting metrics/checkpoints removes them from layout."""

    async def test_delete_standalone_metric_removes_from_layout(self, client, user_a):
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")
        resp = await client.delete(f"/api/metrics/{metric['id']}", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 204

        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert not any(b["id"] == metric["id"] for b in metric_blocks)

    async def test_delete_checkpoint_removes_from_layout(self, client, user_a):
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        cp2 = await create_checkpoint(client, user_a["token"], "День")

        data_before = await _get_layout(client, user_a["token"])
        assert any(b["id"] == cp1["id"] and b["type"] == "checkpoint" for b in data_before["blocks"])

        # Delete cp1 (no metrics attached)
        resp = await client.delete(f"/api/checkpoints/{cp1['id']}", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

        data_after = await _get_layout(client, user_a["token"])
        assert not any(b["id"] == cp1["id"] and b["type"] == "checkpoint" for b in data_after["blocks"])


@pytest.mark.anyio
class TestLayoutBlockReorder:
    """POST /api/layout/blocks — reorder top-level blocks."""

    async def test_reorder_blocks(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        metric = await create_metric(client, user_a["token"], name="Спорт", metric_type="bool")

        data = await _get_layout(client, user_a["token"])
        blocks = data["blocks"]
        # Reverse order
        reversed_items = [
            {"block_type": b["type"], "block_id": b["id"], "sort_order": i * 10}
            for i, b in enumerate(reversed(blocks))
        ]
        resp = await client.post("/api/layout/blocks", json=reversed_items, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

        data2 = await _get_layout(client, user_a["token"])
        new_ids = [(b["type"], b["id"]) for b in data2["blocks"]]
        old_ids = [(b["type"], b["id"]) for b in blocks]
        assert new_ids == list(reversed(old_ids))


@pytest.mark.anyio
class TestLayoutDailyPageRespected:
    """Daily page should render metrics in layout order."""

    async def test_daily_returns_block_type_and_block_id(self, client, user_a):
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")
        resp = await client.post(
            "/api/metrics",
            json={"name": "Настроение", "type": "scale", "scale_min": 1, "scale_max": 5,
                  "is_checkpoint": True,
                  "checkpoint_configs": [
                      {"checkpoint_id": (await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))).json()[0]["id"]},
                      {"checkpoint_id": (await client.get("/api/checkpoints", headers=auth_headers(user_a["token"]))).json()[1]["id"]},
                  ]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        daily = await client.get("/api/daily/2026-03-31", headers=auth_headers(user_a["token"]))
        assert daily.status_code == 200
        metrics = daily.json()["metrics"]
        for m in metrics:
            assert "block_type" in m
            assert "block_id" in m


@pytest.mark.anyio
class TestLayoutDataIsolation:
    """Users cannot see or modify each other's layout."""

    async def test_layout_isolated_between_users(self, client, user_a, user_b):
        await create_metric(client, user_a["token"], name="A-Metric", metric_type="bool")
        await create_metric(client, user_b["token"], name="B-Metric", metric_type="bool")

        data_a = await _get_layout(client, user_a["token"])
        data_b = await _get_layout(client, user_b["token"])

        a_labels = [b.get("label") for b in data_a["blocks"]]
        b_labels = [b.get("label") for b in data_b["blocks"]]
        assert "A-Metric" in a_labels
        assert "A-Metric" not in b_labels
        assert "B-Metric" in b_labels
        assert "B-Metric" not in a_labels
