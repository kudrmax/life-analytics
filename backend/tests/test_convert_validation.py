"""Cross-cutting validation tests: auth, isolation, atomicity, disallowed conversions."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth_headers,
    create_entry,
    create_metric,
)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

class TestAuthValidation:

    async def test_no_auth_preview(self, client: AsyncClient, bool_metric: dict):
        resp = await client.get(
            f"/api/metrics/{bool_metric['id']}/convert/preview",
            params={"target_type": "enum"},
        )
        assert resp.status_code == 401

    async def test_no_auth_convert(self, client: AsyncClient, bool_metric: dict):
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "A", "false": "B"},
                "enum_options": ["A", "B"],
            },
        )
        assert resp.status_code == 401

    async def test_invalid_token_preview(self, client: AsyncClient, bool_metric: dict):
        resp = await client.get(
            f"/api/metrics/{bool_metric['id']}/convert/preview",
            params={"target_type": "enum"},
            headers={"Authorization": "Bearer bad.token.here"},
        )
        assert resp.status_code == 401

    async def test_invalid_token_convert(self, client: AsyncClient, bool_metric: dict):
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "A", "false": "B"},
                "enum_options": ["A", "B"],
            },
            headers={"Authorization": "Bearer bad.token.here"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestDataIsolation:

    async def test_data_isolation_preview(
        self, client: AsyncClient, user_a: dict, user_b: dict, bool_metric: dict,
    ):
        resp = await client.get(
            f"/api/metrics/{bool_metric['id']}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_data_isolation_convert(
        self, client: AsyncClient, user_a: dict, user_b: dict, bool_metric: dict,
    ):
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "A", "false": "B"},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Disallowed conversions (parametrized across many pairs)
# ---------------------------------------------------------------------------

class TestDisallowedConversions:

    @pytest.mark.parametrize("source_type,source_kwargs,target_type", [
        # bool can only go to enum
        ("bool", {}, "scale"),
        ("bool", {}, "number"),
        ("bool", {}, "bool"),
        # scale can only go to scale
        ("scale", {"scale_min": 1, "scale_max": 5, "scale_step": 1}, "enum"),
        ("scale", {"scale_min": 1, "scale_max": 5, "scale_step": 1}, "bool"),
        ("scale", {"scale_min": 1, "scale_max": 5, "scale_step": 1}, "number"),
        # number has no conversions
        ("number", {}, "enum"),
        ("number", {}, "bool"),
        ("number", {}, "scale"),
        # enum can only go to scale
        ("enum", {"enum_options": ["A", "B"]}, "enum"),
        ("enum", {"enum_options": ["A", "B"]}, "bool"),
        ("enum", {"enum_options": ["A", "B"]}, "number"),
        # duration has no conversions
        ("duration", {}, "enum"),
        ("duration", {}, "number"),
    ])
    async def test_disallowed_conversions(
        self, client: AsyncClient, user_a: dict,
        source_type: str, source_kwargs: dict, target_type: str,
    ):
        metric = await create_metric(
            client, user_a["token"],
            name=f"test_{source_type}_to_{target_type}",
            metric_type=source_type,
            **source_kwargs,
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": target_type,
                "value_mapping": {},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------

class TestAtomicity:

    async def test_atomicity_bool_to_enum(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """On error, metric type and entries must remain unchanged."""
        token = user_a["token"]
        metric = await create_metric(client, token, name="Atom Bool", metric_type="bool")
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", False)

        # Try conversion with invalid mapping target (not in options)
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "NONEXISTENT", "false": "B"},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

        # Verify nothing changed
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT type FROM metric_definitions WHERE id = $1", mid,
            )
            assert row["type"] == "bool"

            # entries still exist
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM entries WHERE metric_id = $1", mid,
            )
            assert cnt == 2

            # values_bool still intact
            bool_cnt = await conn.fetchval(
                """SELECT COUNT(*) FROM values_bool vb
                   JOIN entries e ON e.id = vb.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert bool_cnt == 2

            # No enum_config or values_enum created
            ec = await conn.fetchval(
                "SELECT COUNT(*) FROM enum_config WHERE metric_id = $1", mid,
            )
            assert ec == 0

    async def test_atomicity_scale(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """On error, scale_config and values_scale must remain unchanged."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Atom Scale", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-01-10", 3)

        # Save original state
        async with db_pool.acquire() as conn:
            orig_sc = await conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
                mid,
            )
            orig_val = await conn.fetchval(
                """SELECT vs.value FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )

        # Try conversion with value outside range
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {"3": "99"},  # 99 is outside 1-10
                "scale_min": 1,
                "scale_max": 10,
                "scale_step": 1,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

        # Verify nothing changed
        async with db_pool.acquire() as conn:
            sc = await conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
                mid,
            )
            assert sc["scale_min"] == orig_sc["scale_min"]
            assert sc["scale_max"] == orig_sc["scale_max"]
            assert sc["scale_step"] == orig_sc["scale_step"]

            val = await conn.fetchval(
                """SELECT vs.value FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert val == orig_val


# ---------------------------------------------------------------------------
# Double conversion (converted type not in ALLOWED_CONVERSIONS)
# ---------------------------------------------------------------------------

class TestDoubleConversion:

    async def test_double_conversion_bool_to_enum_then_reject(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """After bool→enum, trying enum→anything should fail (enum not in ALLOWED_CONVERSIONS)."""
        mid = bool_metric["id"]
        token = user_a["token"]

        # First: convert bool → enum
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "A", "false": "B"},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 200

        # Second: try enum → bool (should fail)
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "bool",
                "value_mapping": {},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

        # Also try enum → enum
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {},
                "enum_options": ["X", "Y"],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

        # enum → number (disallowed)
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "number",
                "value_mapping": {},
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Additional disallowed source types
# ---------------------------------------------------------------------------

class TestDisallowedSourceTypes:

    async def test_convert_text_type_disallowed(
        self, client: AsyncClient, user_a: dict,
    ):
        """text is not in ALLOWED_CONVERSIONS → 400."""
        metric = await create_metric(
            client, user_a["token"],
            name="Text Metric", metric_type="text",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_integration_type_disallowed(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """integration is not in ALLOWED_CONVERSIONS → 400."""
        # Integration metrics require provider via API, so create directly in DB
        token = user_a["token"]
        user_id = user_a["user_id"]
        async with db_pool.acquire() as conn:
            mid = await conn.fetchval(
                """INSERT INTO metric_definitions (user_id, slug, name, type, enabled, sort_order)
                   VALUES ($1, 'integ_test', 'Integ Metric', 'integration', TRUE, 0)
                   RETURNING id""",
                user_id,
            )
        resp = await client.post(
            f"/api/metrics/{mid}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
