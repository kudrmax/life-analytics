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
        assert resp.status_code == 204

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

    async def test_duplicate_blocks_handled_gracefully(self, client, user_a):
        """Duplicate (block_type, block_id) in items must not cause 500."""
        metric = await create_metric(client, user_a["token"], name="Dup", metric_type="bool")
        items = [
            {"block_type": "metric", "block_id": metric["id"], "sort_order": 0},
            {"block_type": "metric", "block_id": metric["id"], "sort_order": 10},
        ]
        resp = await client.post("/api/layout/blocks", json=items, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

    async def test_duplicate_blocks_last_sort_order_wins(self, client, user_a):
        """When duplicates sent, last sort_order should be saved."""
        m1 = await create_metric(client, user_a["token"], name="M1", metric_type="bool")
        m2 = await create_metric(client, user_a["token"], name="M2", metric_type="bool")
        items = [
            {"block_type": "metric", "block_id": m1["id"], "sort_order": 0},
            {"block_type": "metric", "block_id": m2["id"], "sort_order": 10},
            {"block_type": "metric", "block_id": m1["id"], "sort_order": 20},
        ]
        resp = await client.post("/api/layout/blocks", json=items, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

        data = await _get_layout(client, user_a["token"])
        blocks = data["blocks"]
        m1_block = next(b for b in blocks if b["type"] == "metric" and b["id"] == m1["id"])
        m2_block = next(b for b in blocks if b["type"] == "metric" and b["id"] == m2["id"])
        m1_idx = blocks.index(m1_block)
        m2_idx = blocks.index(m2_block)
        assert m2_idx < m1_idx

    async def test_duplicate_category_blocks_no_crash(self, client, user_a):
        """Exact reproduction: duplicate category block must not cause UniqueViolationError."""
        resp = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        cat_id = resp.json()["category_id"]
        items = [
            {"block_type": "category", "block_id": cat_id, "sort_order": 0},
            {"block_type": "category", "block_id": cat_id, "sort_order": 10},
        ]
        resp = await client.post("/api/layout/blocks", json=items, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200


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
class TestLayoutInnerOrderPreservesCategory:
    """Saving inner order must not lose category_id on standalone metrics.

    Regression: standalone items in category blocks were returned without
    category_id, so a round-trip (GET layout → save inner) wiped the category.
    """

    async def test_category_block_items_include_category_id(self, client, user_a):
        """GET /api/layout must return category_id in items of category blocks."""
        resp = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        cat_id = metric["category_id"]

        data = await _get_layout(client, user_a["token"])
        cat_block = next(b for b in data["blocks"] if b["type"] == "category" and b["id"] == cat_id)
        items = cat_block["items"]
        assert len(items) >= 1
        item = next(i for i in items if i["metric_id"] == metric["id"])
        assert item["category_id"] == cat_id

    async def test_save_inner_order_preserves_category(self, client, user_a):
        """Round-trip: GET layout → POST inner → metric keeps its category_id."""
        # Create two metrics in same category
        resp1 = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp1.status_code == 201
        m1 = resp1.json()
        cat_id = m1["category_id"]

        resp2 = await client.post(
            "/api/metrics",
            json={"name": "Калории", "type": "number", "category_id": cat_id},
            headers=auth_headers(user_a["token"]),
        )
        assert resp2.status_code == 201
        m2 = resp2.json()

        # Get layout — find category block
        data = await _get_layout(client, user_a["token"])
        cat_block = next(b for b in data["blocks"] if b["type"] == "category" and b["id"] == cat_id)

        # Simulate frontend: save inner order (reversed) with category_id from response
        items = cat_block["items"]
        save_items = [
            {"metric_id": it["metric_id"], "sort_order": i * 10, "category_id": it["category_id"]}
            for i, it in enumerate(reversed(items))
        ]
        resp = await client.post(
            "/api/layout/inner",
            json={"block_type": "category", "block_id": cat_id, "items": save_items},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Verify category_id is preserved on metrics
        for mid in [m1["id"], m2["id"]]:
            r = await client.get(f"/api/metrics/{mid}", headers=auth_headers(user_a["token"]))
            assert r.status_code == 200
            assert r.json()["category_id"] == cat_id, f"metric {mid} lost its category_id"

    async def test_save_inner_without_category_clears_it(self, client, user_a):
        """If inner save sends category_id=null, metric loses its category."""
        resp = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        assert metric["category_id"] is not None

        # Save inner order with category_id=null (reproduces the original bug)
        resp = await client.post(
            "/api/layout/inner",
            json={"block_type": "category", "block_id": metric["category_id"],
                  "items": [{"metric_id": metric["id"], "sort_order": 0, "category_id": None}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        r = await client.get(f"/api/metrics/{metric['id']}", headers=auth_headers(user_a["token"]))
        assert r.json()["category_id"] is None


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


@pytest.mark.anyio
class TestLayoutEnsureMissingStandalone:
    """_ensure_layout adds missing standalone metrics to layout."""

    async def test_standalone_without_layout_entry_appears(self, client, user_a, db_pool):
        """Metric that has no daily_layout entry should appear via _ensure_layout."""
        metric = await create_metric(client, user_a["token"], name="Orphan", metric_type="bool")

        # Manually delete its layout entry to simulate the bug
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM daily_layout WHERE user_id = $1 AND block_type = 'metric' AND block_id = $2",
                user_a["user_id"], metric["id"],
            )

        # GET layout should still include the metric (via _ensure_layout)
        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert any(b["id"] == metric["id"] for b in metric_blocks)

    async def test_category_metric_without_layout_entry_appears(self, client, user_a, db_pool):
        """Category block without layout entry should appear via _ensure_layout."""
        resp = await client.post(
            "/api/metrics",
            json={"name": "Вес", "type": "number", "new_category_name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        cat_id = resp.json()["category_id"]

        # Manually delete the category layout entry
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM daily_layout WHERE user_id = $1 AND block_type = 'category' AND block_id = $2",
                user_a["user_id"], cat_id,
            )

        # GET layout should still include the category block
        data = await _get_layout(client, user_a["token"])
        cat_blocks = [b for b in data["blocks"] if b["type"] == "category"]
        assert any(b["id"] == cat_id for b in cat_blocks)


@pytest.mark.anyio
class TestLayoutOnIntervalBindingChange:
    """Changing interval_binding from by_interval to all_day adds layout entry."""

    async def test_by_interval_to_all_day_adds_layout(self, client, user_a):
        """Metric transitioning from by_interval to all_day gets a layout entry."""
        await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        intervals = await _get_intervals(client, user_a["token"])
        assert len(intervals) >= 1
        iv_id = intervals[0]["id"]

        # Create metric with by_interval binding
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Активность",
                "type": "bool",
                "interval_binding": "by_interval",
                "interval_ids": [iv_id],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric_id = resp.json()["id"]

        # Verify it's NOT in layout as standalone metric
        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert not any(b["id"] == metric_id for b in metric_blocks)

        # Change to all_day
        resp = await client.patch(
            f"/api/metrics/{metric_id}",
            json={"interval_binding": "all_day"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Now it should appear as standalone in layout
        data = await _get_layout(client, user_a["token"])
        metric_blocks = [b for b in data["blocks"] if b["type"] == "metric"]
        assert any(b["id"] == metric_id for b in metric_blocks)
