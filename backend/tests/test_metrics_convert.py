"""Tests for metric conversion endpoints to increase branch coverage."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry


# ── Conversion preview ───────────────────────────────────────────────


class TestConversionPreview:
    """GET /api/metrics/{id}/convert/preview"""

    async def test_preview_scale_to_scale(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Preview scale->scale conversion with entries."""
        metric = await create_metric(
            client, user_a["token"],
            name="ScalePrev", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", 3)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", 5)

        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 2

    async def test_preview_bool_to_enum(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Preview bool->enum conversion with entries."""
        metric = await create_metric(
            client, user_a["token"], name="BoolPrev", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", False)

        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 2

    async def test_preview_unsupported_conversion_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Preview unsupported conversion (number->enum) -> 400."""
        metric = await create_metric(
            client, user_a["token"], name="NumConv", metric_type="number",
        )
        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_preview_not_found_404(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Preview for non-existent metric -> 404."""
        resp = await client.get(
            "/api/metrics/999999/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ── Conversion execution: scale to scale ─────────────────────────────


class TestConvertScaleToScale:
    """POST /api/metrics/{id}/convert — scale->scale."""

    async def test_convert_scale_to_scale_success(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert scale 1-5 to 1-10 with value mapping."""
        metric = await create_metric(
            client, user_a["token"],
            name="S2S", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", 1)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", 3)

        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {"1": "2", "3": "6"},
                "scale_min": 1,
                "scale_max": 10,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 2
        assert data["deleted"] == 0

    async def test_convert_scale_delete_values(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert scale with some values mapped to null (delete)."""
        metric = await create_metric(
            client, user_a["token"],
            name="S2SDel", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", 1)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", 3)

        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {"1": "2", "3": None},
                "scale_min": 1,
                "scale_max": 10,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 1
        assert data["deleted"] == 1

    async def test_convert_scale_missing_config_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert scale without scale_min/max/step -> 400."""
        metric = await create_metric(
            client, user_a["token"],
            name="S2SMiss", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_scale_bad_range_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert scale with min >= max -> 400."""
        metric = await create_metric(
            client, user_a["token"],
            name="S2SBad", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 10,
                "scale_max": 5,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_not_found_404(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics/999999/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 1,
                "scale_max": 5,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_convert_unsupported_type_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert number to scale -> 400 (unsupported)."""
        metric = await create_metric(
            client, user_a["token"], name="NumUnsup", metric_type="number",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                "scale_min": 1,
                "scale_max": 5,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Conversion execution: bool to enum ───────────────────────────────


class TestConvertBoolToEnum:
    """POST /api/metrics/{id}/convert — bool->enum."""

    async def test_convert_bool_to_enum_success(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="B2E", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", False)

        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "Yes", "false": "No"},
                "enum_options": ["Yes", "No"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 2
        assert data["deleted"] == 0

    async def test_convert_bool_to_enum_with_delete(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Convert bool to enum, mapping false to null (delete)."""
        metric = await create_metric(
            client, user_a["token"], name="B2EDel", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-01-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-01-02", False)

        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "Active", "false": None},
                "enum_options": ["Active", "Inactive"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted"] == 1
        assert data["deleted"] == 1

    async def test_convert_bool_to_enum_too_few_options_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="B2EFew", metric_type="bool",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "Yes"},
                "enum_options": ["Yes"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_bool_to_enum_invalid_bool_key_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="B2EBad", metric_type="bool",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"yes": "A", "no": "B"},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_bool_to_enum_bad_target_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Mapping target not in enum_options -> 400."""
        metric = await create_metric(
            client, user_a["token"], name="B2EBadT", metric_type="bool",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "NonExistent", "false": "B"},
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_convert_bool_to_enum_duplicate_options_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="B2EDup", metric_type="bool",
        )
        resp = await client.post(
            f"/api/metrics/{metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "Same", "false": "Same"},
                "enum_options": ["Same", "Same"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400
