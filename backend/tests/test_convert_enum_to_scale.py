"""Tests for enum → scale conversion."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, create_entry, create_metric


class TestEnumToScaleHappyPath:
    """Happy-path scenarios for enum→scale conversion."""

    async def test_basic_3_options(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """3 options → scale 0-2, each option maps to sequential value."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Mood", metric_type="enum",
            enum_options=["Плохо", "Средне", "Хорошо"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        oid_bad, oid_mid, oid_good = opts[0]["id"], opts[1]["id"], opts[2]["id"]

        await create_entry(client, token, mid, "2026-01-10", [oid_bad])
        await create_entry(client, token, mid, "2026-01-11", [oid_mid])
        await create_entry(client, token, mid, "2026-01-12", [oid_good])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(oid_bad): "0",
                    str(oid_mid): "1",
                    str(oid_good): "2",
                },
                "scale_min": 0, "scale_max": 2, "scale_step": 1,
                "scale_labels": {"0": "Плохо", "1": "Средне", "2": "Хорошо"},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 3
        assert data["deleted"] == 0

    async def test_with_deletion(
        self, client: AsyncClient, user_a: dict,
    ):
        """One option mapped to None → entries deleted."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Del Enum", metric_type="enum",
            enum_options=["A", "B", "C"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        oid_a, oid_b, oid_c = opts[0]["id"], opts[1]["id"], opts[2]["id"]

        await create_entry(client, token, mid, "2026-01-10", [oid_a])
        await create_entry(client, token, mid, "2026-01-11", [oid_b])
        await create_entry(client, token, mid, "2026-01-12", [oid_c])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(oid_a): "0",
                    str(oid_b): None,
                    str(oid_c): "1",
                },
                "scale_min": 0, "scale_max": 1, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 2
        assert data["deleted"] == 1

    async def test_empty_metric(
        self, client: AsyncClient, user_a: dict,
    ):
        """Enum with no entries — converts cleanly."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Empty Enum", metric_type="enum",
            enum_options=["X", "Y"],
        )
        mid = metric["id"]

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 0, "scale_max": 1, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 0
        assert data["deleted"] == 0

    async def test_merge_options_to_same_value(
        self, client: AsyncClient, user_a: dict,
    ):
        """Two options mapped to the same scale value."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Merge Enum", metric_type="enum",
            enum_options=["Low", "Medium", "High"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        oid_l, oid_m, oid_h = opts[0]["id"], opts[1]["id"], opts[2]["id"]

        await create_entry(client, token, mid, "2026-01-10", [oid_l])
        await create_entry(client, token, mid, "2026-01-11", [oid_m])
        await create_entry(client, token, mid, "2026-01-12", [oid_h])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(oid_l): "0",
                    str(oid_m): "0",
                    str(oid_h): "1",
                },
                "scale_min": 0, "scale_max": 1, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 3
        assert data["deleted"] == 0

    async def test_labels_stored(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """scale_labels should be stored in scale_config."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Label Enum", metric_type="enum",
            enum_options=["Bad", "Good"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(opts[0]["id"]): "0",
                    str(opts[1]["id"]): "1",
                },
                "scale_min": 0, "scale_max": 1, "scale_step": 1,
                "scale_labels": {"0": "Bad", "1": "Good"},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200

        import json
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT labels FROM scale_config WHERE metric_id = $1", mid,
            )
            assert row is not None
            labels = json.loads(row["labels"]) if isinstance(row["labels"], str) else row["labels"]
            assert labels == {"0": "Bad", "1": "Good"}


    async def test_labels_for_unfilled_options(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """Enum with 3 options, only 2 filled — labels for all 3 stored in scale_config."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Unfilled Labels", metric_type="enum",
            enum_options=["Бег", "Зарядка", "Йога"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        oid_a, oid_b, oid_c = opts[0]["id"], opts[1]["id"], opts[2]["id"]

        # Only fill 2 out of 3 options
        await create_entry(client, token, mid, "2026-01-10", [oid_a])
        await create_entry(client, token, mid, "2026-01-11", [oid_c])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(oid_a): "0",
                    str(oid_b): "1",
                    str(oid_c): "2",
                },
                "scale_min": 0, "scale_max": 2, "scale_step": 1,
                "scale_labels": {"0": "Бег", "1": "Зарядка", "2": "Йога"},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 2
        assert data["deleted"] == 0

        import json
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT labels FROM scale_config WHERE metric_id = $1", mid,
            )
            assert row is not None
            labels = json.loads(row["labels"]) if isinstance(row["labels"], str) else row["labels"]
            assert labels == {"0": "Бег", "1": "Зарядка", "2": "Йога"}


class TestEnumToScaleValidation:
    """Validation errors for enum→scale conversion."""

    async def test_missing_scale_params(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="No Params", metric_type="enum",
            enum_options=["A", "B"],
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
        assert "scale_min" in resp.json()["detail"]

    async def test_invalid_range(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Bad Range", metric_type="enum",
            enum_options=["A", "B"],
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 5, "scale_max": 2, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

    async def test_incomplete_mapping(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Incomplete Map", metric_type="enum",
            enum_options=["A", "B"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        await create_entry(client, token, mid, "2026-01-10", [opts[0]["id"]])
        await create_entry(client, token, mid, "2026-01-11", [opts[1]["id"]])

        # Only map one option, leave the other unmapped
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {str(opts[0]["id"]): "0"},
                "scale_min": 0, "scale_max": 1, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
        assert "incomplete" in resp.json()["detail"].lower()

    async def test_multi_select_rejected(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Multi Sel", metric_type="enum",
            enum_options=["A", "B", "C"],
            multi_select=True,
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 0, "scale_max": 2, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
        assert "multi-select" in resp.json()["detail"].lower()

    async def test_value_outside_range(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Out Range", metric_type="enum",
            enum_options=["A", "B"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        await create_entry(client, token, mid, "2026-01-10", [opts[0]["id"]])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {str(opts[0]["id"]): "99"},
                "scale_min": 0, "scale_max": 2, "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
        assert "not in valid range" in resp.json()["detail"]


class TestEnumToScaleDBState:
    """Verify DB state after successful conversion."""

    async def test_db_state_after_conversion(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """Full DB state check: type, config, values, cleanup."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="DB State Enum", metric_type="enum",
            enum_options=["Low", "High"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        oid_low, oid_high = opts[0]["id"], opts[1]["id"]

        await create_entry(client, token, mid, "2026-01-10", [oid_low])
        await create_entry(client, token, mid, "2026-01-11", [oid_high])

        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {
                    str(oid_low): "1",
                    str(oid_high): "5",
                },
                "scale_min": 1, "scale_max": 5, "scale_step": 1,
                "scale_labels": {"1": "Low", "5": "High"},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200

        import json
        async with db_pool.acquire() as conn:
            # 1. Type changed to scale
            row = await conn.fetchrow(
                "SELECT type FROM metric_definitions WHERE id = $1", mid,
            )
            assert row["type"] == "scale"

            # 2. scale_config created with labels
            sc = await conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step, labels FROM scale_config WHERE metric_id = $1",
                mid,
            )
            assert sc is not None
            assert sc["scale_min"] == 1
            assert sc["scale_max"] == 5
            assert sc["scale_step"] == 1
            labels = json.loads(sc["labels"]) if isinstance(sc["labels"], str) else sc["labels"]
            assert labels == {"1": "Low", "5": "High"}

            # 3. values_scale created with correct values
            vs_rows = await conn.fetch(
                """SELECT vs.value, vs.scale_min, vs.scale_max, vs.scale_step
                   FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1 ORDER BY vs.value""",
                mid,
            )
            assert len(vs_rows) == 2
            assert vs_rows[0]["value"] == 1
            assert vs_rows[0]["scale_min"] == 1
            assert vs_rows[0]["scale_max"] == 5
            assert vs_rows[1]["value"] == 5

            # 4. values_enum cleaned up
            ve_cnt = await conn.fetchval(
                """SELECT COUNT(*) FROM values_enum ve
                   JOIN entries e ON e.id = ve.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert ve_cnt == 0

            # 5. enum_config deleted
            ec_cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM enum_config WHERE metric_id = $1", mid,
            )
            assert ec_cnt == 0

            # 6. enum_options deleted
            eo_cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM enum_options WHERE metric_id = $1", mid,
            )
            assert eo_cnt == 0

            # 7. entries preserved (2 entries still exist)
            entry_cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM entries WHERE metric_id = $1", mid,
            )
            assert entry_cnt == 2
