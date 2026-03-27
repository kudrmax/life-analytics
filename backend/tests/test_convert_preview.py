"""Tests for GET /api/metrics/{id}/convert/preview endpoint."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, create_entry, create_metric, create_checkpoint


class TestPreviewBoolMetric:
    """Preview for bool → enum conversion."""

    async def test_preview_bool_both_values(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 5
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        assert "true" in by_val
        assert "false" in by_val
        assert by_val["true"]["count"] == 3
        assert by_val["false"]["count"] == 2

    async def test_preview_bool_only_true(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", True)
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 2
        assert len(data["entries_by_value"]) == 1
        assert data["entries_by_value"][0]["value"] == "true"

    async def test_preview_bool_only_false(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", False)
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 1
        assert data["entries_by_value"][0]["value"] == "false"

    async def test_preview_bool_empty(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 0
        assert data["entries_by_value"] == []

    async def test_preview_bool_value_format(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        """Values must be lowercase 'true'/'false', display 'Да'/'Нет'."""
        mid = bool_metric_with_entries["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        assert by_val["true"]["display"] == "Да"
        assert by_val["false"]["display"] == "Нет"


class TestPreviewEnumMetric:
    """Preview for enum → scale conversion."""

    async def test_preview_enum_3_options(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Mood Prev", metric_type="enum",
            enum_options=["Плохо", "Средне", "Хорошо"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        await create_entry(client, token, mid, "2026-01-10", [opts[0]["id"]])
        await create_entry(client, token, mid, "2026-01-11", [opts[1]["id"]])
        await create_entry(client, token, mid, "2026-01-12", [opts[2]["id"]])
        await create_entry(client, token, mid, "2026-01-13", [opts[2]["id"]])

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 4
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        assert by_val[str(opts[0]["id"])]["display"] == "Плохо"
        assert by_val[str(opts[0]["id"])]["count"] == 1
        assert by_val[str(opts[2]["id"])]["display"] == "Хорошо"
        assert by_val[str(opts[2]["id"])]["count"] == 2

    async def test_preview_enum_value_format(
        self, client: AsyncClient, user_a: dict,
    ):
        """Value is option_id as string, display is option label. Unfilled options included with count=0."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Fmt Prev", metric_type="enum",
            enum_options=["Alpha", "Beta"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        await create_entry(client, token, mid, "2026-01-10", [opts[0]["id"]])

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        data = resp.json()
        assert len(data["entries_by_value"]) == 2
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        assert by_val[str(opts[0]["id"])]["display"] == "Alpha"
        assert by_val[str(opts[0]["id"])]["count"] == 1
        assert by_val[str(opts[1]["id"])]["display"] == "Beta"
        assert by_val[str(opts[1]["id"])]["count"] == 0

    async def test_preview_enum_unfilled_options_included(
        self, client: AsyncClient, user_a: dict,
    ):
        """Regression: enum with 3 options, only 1 filled → all 3 in preview, unfilled have count=0."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Partial Prev", metric_type="enum",
            enum_options=["Бег", "Зарядка", "Йога"],
        )
        mid = metric["id"]
        opts = metric["enum_options"]
        # Only fill the first option
        await create_entry(client, token, mid, "2026-01-10", [opts[0]["id"]])

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 1
        assert len(data["entries_by_value"]) == 3
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        assert by_val[str(opts[0]["id"])]["count"] == 1
        assert by_val[str(opts[0]["id"])]["display"] == "Бег"
        assert by_val[str(opts[1]["id"])]["count"] == 0
        assert by_val[str(opts[1]["id"])]["display"] == "Зарядка"
        assert by_val[str(opts[2]["id"])]["count"] == 0
        assert by_val[str(opts[2]["id"])]["display"] == "Йога"

    async def test_preview_enum_multi_select_rejected(
        self, client: AsyncClient, user_a: dict,
    ):
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Multi Prev", metric_type="enum",
            enum_options=["A", "B"], multi_select=True,
        )
        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 400

    async def test_preview_enum_empty(
        self, client: AsyncClient, user_a: dict,
    ):
        """No entries — all options still shown with count=0."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Empty Prev", metric_type="enum",
            enum_options=["X", "Y"],
        )
        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 0
        assert len(data["entries_by_value"]) == 2
        by_val = {item["value"]: item for item in data["entries_by_value"]}
        opts = metric["enum_options"]
        assert by_val[str(opts[0]["id"])]["display"] == "X"
        assert by_val[str(opts[0]["id"])]["count"] == 0
        assert by_val[str(opts[1]["id"])]["display"] == "Y"
        assert by_val[str(opts[1]["id"])]["count"] == 0


class TestPreviewScaleMetric:
    """Preview for scale → scale conversion."""

    async def test_preview_scale_multiple_values(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        mid = scale_metric_with_entries["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 5
        assert len(data["entries_by_value"]) == 5
        values = [item["value"] for item in data["entries_by_value"]]
        assert values == ["1", "2", "3", "4", "5"]

    async def test_preview_scale_single_value(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        mid = scale_metric["id"]
        token = user_a["token"]
        # All entries have the same value
        for i in range(3):
            await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", 3)
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        data = resp.json()
        assert data["total_entries"] == 3
        assert len(data["entries_by_value"]) == 1
        assert data["entries_by_value"][0]["count"] == 3

    async def test_preview_scale_empty(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        mid = scale_metric["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        assert data["total_entries"] == 0
        assert data["entries_by_value"] == []

    async def test_preview_scale_value_ordering(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        """Values must be sorted ascending."""
        mid = scale_metric["id"]
        token = user_a["token"]
        # Insert in reverse order
        for i, val in enumerate([5, 1, 3]):
            await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", val)
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        data = resp.json()
        values = [item["value"] for item in data["entries_by_value"]]
        assert values == ["1", "3", "5"]


class TestPreviewEdgeCases:
    """Not-found, auth, disallowed conversions."""

    async def test_preview_not_found(
        self, client: AsyncClient, user_a: dict,
    ):
        resp = await client.get(
            "/api/metrics/999999/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_preview_other_user(
        self, client: AsyncClient, user_a: dict, user_b: dict, bool_metric: dict,
    ):
        """user_b must not see user_a's metric."""
        mid = bool_metric["id"]
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "source_type,scale_kwargs,target",
        [
            ("bool", {}, "scale"),
            ("number", {}, "enum"),
            ("scale", {"scale_min": 1, "scale_max": 5, "scale_step": 1}, "enum"),
        ],
    )
    async def test_preview_disallowed_conversion(
        self, client: AsyncClient, user_a: dict,
        source_type: str, scale_kwargs: dict, target: str,
    ):
        metric = await create_metric(
            client, user_a["token"],
            name=f"dis_{source_type}_{target}",
            metric_type=source_type,
            **scale_kwargs,
        )
        resp = await client.get(
            f"/api/metrics/{metric['id']}/convert/preview",
            params={"target_type": target},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_preview_no_auth(self, client: AsyncClient, bool_metric: dict):
        resp = await client.get(
            f"/api/metrics/{bool_metric['id']}/convert/preview",
            params={"target_type": "enum"},
        )
        assert resp.status_code == 401

    async def test_preview_invalid_token(self, client: AsyncClient, bool_metric: dict):
        resp = await client.get(
            f"/api/metrics/{bool_metric['id']}/convert/preview",
            params={"target_type": "enum"},
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert resp.status_code == 401

    async def test_preview_disabled_metric(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict, db_pool,
    ):
        """Disabled metric should still return preview."""
        mid = bool_metric_with_entries["id"]
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE metric_definitions SET enabled = FALSE WHERE id = $1", mid,
            )
        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 5

    async def test_preview_bool_with_checkpoints(
        self, client: AsyncClient, user_a: dict,
    ):
        """Bool metric with checkpoints — preview aggregates all checkpoints."""
        token = user_a["token"]
        cp_u = await create_checkpoint(client, token, "Утро")
        cp_v = await create_checkpoint(client, token, "Вечер")
        metric = await create_metric(
            client, token,
            name="Bool CPs Prev", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_u["id"]}, {"checkpoint_id": cp_v["id"]}],
        )
        mid = metric["id"]
        checkpoints = metric["checkpoints"]
        await create_entry(client, token, mid, "2026-02-10", True, checkpoint_id=checkpoints[0]["id"])
        await create_entry(client, token, mid, "2026-02-10", False, checkpoint_id=checkpoints[1]["id"])

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "enum"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 2

    async def test_preview_scale_negative_values(
        self, client: AsyncClient, user_a: dict,
    ):
        """Scale with negative values — GROUP BY/ORDER BY on negatives."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Neg Scale Prev", metric_type="scale",
            scale_min=-5, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        for i, val in enumerate([-5, -3, 0, 3, 5]):
            await create_entry(client, token, mid, f"2026-02-{10 + i:02d}", val)

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 5
        values = [item["value"] for item in data["entries_by_value"]]
        assert values == ["-5", "-3", "0", "3", "5"]

    async def test_preview_scale_zero_value(
        self, client: AsyncClient, user_a: dict,
    ):
        """Entry with value=0 — must appear in preview (0 is falsy in some contexts)."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Zero Scale Prev", metric_type="scale",
            scale_min=0, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-02-10", 0)

        resp = await client.get(
            f"/api/metrics/{mid}/convert/preview",
            params={"target_type": "scale"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_entries"] == 1
        assert data["entries_by_value"][0]["value"] == "0"
