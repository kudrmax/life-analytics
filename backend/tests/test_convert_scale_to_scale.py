"""Tests for POST /api/metrics/{id}/convert — scale → scale."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth_headers,
    create_entry,
    create_metric,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_payload(
    *,
    mapping: dict[str, str | None],
    scale_min: int,
    scale_max: int,
    scale_step: int,
) -> dict:
    return {
        "target_type": "scale",
        "value_mapping": mapping,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "scale_step": scale_step,
    }


async def _do_convert(
    client: AsyncClient,
    token: str,
    metric_id: int,
    **kwargs,
) -> tuple[int, dict]:
    resp = await client.post(
        f"/api/metrics/{metric_id}/convert",
        json=_convert_payload(**kwargs),
        headers=auth_headers(token),
    )
    return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestScaleToScaleHappyPath:

    async def test_remap_1_5_to_1_10(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Remap each value: 1→2, 2→4, 3→6, 4→8, 5→10."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

    async def test_merge_values(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Multiple old values can map to the same new value."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "1", "2": "1", "3": "5", "4": "10", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

    async def test_delete_some(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Delete values 1,2 and remap 3,4,5."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": None, "2": None, "3": "1", "4": "2", "5": "3"},
            scale_min=1, scale_max=3, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 3
        assert body["deleted"] == 2

    async def test_delete_all(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": None, "2": None, "3": None, "4": None, "5": None},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 0
        assert body["deleted"] == 5

    async def test_empty_metric(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        mid = scale_metric["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={},
            scale_min=1, scale_max=10, scale_step=2,
        )
        assert status == 200
        assert body["converted"] == 0
        assert body["deleted"] == 0

    async def test_identity_conversion(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Same config, same values — should still work."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "1", "2": "2", "3": "3", "4": "4", "5": "5"},
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

    async def test_extra_mapping_keys(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        """Mapping has keys for values not in DB — should be OK."""
        mid = scale_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", 3)
        status, body = await _do_convert(
            client, token, mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 1


# ---------------------------------------------------------------------------
# Validation errors — scale parameters
# ---------------------------------------------------------------------------

class TestScaleToScaleParamValidation:

    @pytest.mark.parametrize("params,reason", [
        ({"scale_min": 5, "scale_max": 5, "scale_step": 1}, "min == max"),
        ({"scale_min": 10, "scale_max": 5, "scale_step": 1}, "min > max"),
        ({"scale_min": 1, "scale_max": 5, "scale_step": 0}, "step == 0"),
        ({"scale_min": 1, "scale_max": 5, "scale_step": -1}, "step < 0"),
        ({"scale_min": 1, "scale_max": 5, "scale_step": 6}, "step > range"),
    ])
    async def test_invalid_scale_params(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
        params: dict, reason: str,
    ):
        resp = await client.post(
            f"/api/metrics/{scale_metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                **params,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400, f"Expected 400 for {reason}"

    @pytest.mark.parametrize("missing_field", ["scale_min", "scale_max", "scale_step"])
    async def test_missing_scale_param(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
        missing_field: str,
    ):
        params = {"scale_min": 1, "scale_max": 10, "scale_step": 1}
        params[missing_field] = None
        resp = await client.post(
            f"/api/metrics/{scale_metric['id']}/convert",
            json={
                "target_type": "scale",
                "value_mapping": {},
                **params,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Validation errors — mapping
# ---------------------------------------------------------------------------

class TestScaleToScaleMappingValidation:

    async def test_incomplete_mapping(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Not all actual values in mapping → 400."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "1", "2": "2"},  # missing 3,4,5
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 400

    async def test_mapping_to_value_outside_range(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "1", "2": "2", "3": "3", "4": "4", "5": "99"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 400

    async def test_mapping_to_non_step_value(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Target value not on step grid (e.g. 3 with min=1, step=2 → valid are 1,3,5)."""
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "1", "2": "2", "3": "3", "4": "4", "5": "5"},
            scale_min=1, scale_max=5, scale_step=2,  # valid: 1, 3, 5
        )
        assert status == 400  # 2 and 4 are not valid targets

    async def test_mapping_non_numeric_target(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "abc", "2": "2", "3": "3", "4": "4", "5": "5"},
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 400


# ---------------------------------------------------------------------------
# Auth / isolation
# ---------------------------------------------------------------------------

class TestScaleToScaleAuth:

    async def test_not_found(self, client: AsyncClient, user_a: dict):
        status, _ = await _do_convert(
            client, user_a["token"], 999999,
            mapping={}, scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 404

    async def test_other_user(
        self, client: AsyncClient, user_a: dict, user_b: dict, scale_metric: dict,
    ):
        status, _ = await _do_convert(
            client, user_b["token"], scale_metric["id"],
            mapping={}, scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 404

    async def test_not_scale_type(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """bool → scale is not allowed."""
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
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

    async def test_no_auth(self, client: AsyncClient, scale_metric: dict):
        resp = await client.post(
            f"/api/metrics/{scale_metric['id']}/convert",
            json=_convert_payload(
                mapping={}, scale_min=1, scale_max=10, scale_step=1,
            ),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Database state verification
# ---------------------------------------------------------------------------

class TestScaleToScaleDBState:

    async def test_verify_db_state(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict, db_pool,
    ):
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            # scale_config updated
            sc = await conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
                mid,
            )
            assert sc["scale_min"] == 1
            assert sc["scale_max"] == 10
            assert sc["scale_step"] == 1

            # values_scale values updated
            rows = await conn.fetch(
                """SELECT vs.value FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1 ORDER BY vs.value""",
                mid,
            )
            values = [r["value"] for r in rows]
            assert values == [2, 4, 6, 8, 10]

    async def test_verify_entries_preserved(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict, db_pool,
    ):
        mid = scale_metric_with_entries["id"]
        async with db_pool.acquire() as conn:
            before = await conn.fetch(
                "SELECT id FROM entries WHERE metric_id = $1 ORDER BY id", mid,
            )
        before_ids = [r["id"] for r in before]

        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            after = await conn.fetch(
                "SELECT id FROM entries WHERE metric_id = $1 ORDER BY id", mid,
            )
        after_ids = [r["id"] for r in after]
        assert after_ids == before_ids

    async def test_values_scale_context_updated(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict, db_pool,
    ):
        """values_scale.scale_min/max/step must be updated to new values."""
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT vs.scale_min, vs.scale_max, vs.scale_step
                   FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            for row in rows:
                assert row["scale_min"] == 1
                assert row["scale_max"] == 10
                assert row["scale_step"] == 1

    async def test_scale_config_updated_on_empty_metric(
        self, client: AsyncClient, user_a: dict, scale_metric: dict, db_pool,
    ):
        """scale_config must be updated even when there are no entries."""
        mid = scale_metric["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={},
            scale_min=0, scale_max=100, scale_step=10,
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            sc = await conn.fetchrow(
                "SELECT scale_min, scale_max, scale_step FROM scale_config WHERE metric_id = $1",
                mid,
            )
            assert sc["scale_min"] == 0
            assert sc["scale_max"] == 100
            assert sc["scale_step"] == 10


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestScaleToScaleEdgeCases:

    async def test_negative_scale_range(
        self, client: AsyncClient, user_a: dict,
    ):
        """Negative values in CASE WHEN — SQL parser must handle 'WHEN -3 THEN 2'."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Neg Scale", metric_type="scale",
            scale_min=-5, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        for i, val in enumerate([-5, -3, 0, 3, 5]):
            await create_entry(client, token, mid, f"2026-02-{10 + i:02d}", val)

        status, body = await _do_convert(
            client, token, mid,
            mapping={"-5": "1", "-3": "2", "0": "3", "3": "4", "5": "5"},
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

    async def test_zero_as_min_value(
        self, client: AsyncClient, user_a: dict,
    ):
        """0 as boundary value — while loop must start at 0."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Zero Min", metric_type="scale",
            scale_min=0, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-02-10", 0)

        status, body = await _do_convert(
            client, token, mid,
            mapping={"0": "5"},
            scale_min=0, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 1

    async def test_step_equals_range(
        self, client: AsyncClient, user_a: dict,
    ):
        """step = (max - min) → only {min, max} are valid."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Step Range", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=9,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-02-10", 1)
        await create_entry(client, token, mid, "2026-02-11", 10)

        status, body = await _do_convert(
            client, token, mid,
            mapping={"1": "10", "10": "1"},
            scale_min=1, scale_max=10, scale_step=9,
        )
        assert status == 200
        assert body["converted"] == 2

    async def test_step_produces_single_value(
        self, client: AsyncClient, user_a: dict,
    ):
        """step > (max - min) is rejected; step = 4 with min=1, max=5 → valid {1, 5}."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Single Val", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=4,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-02-10", 1)

        # step=5 on range [1..5] → step > range → 400
        status, _ = await _do_convert(
            client, token, mid,
            mapping={"1": "1"},
            scale_min=1, scale_max=5, scale_step=5,
        )
        assert status == 400

    async def test_mapping_key_with_leading_spaces(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict,
    ):
        """Keys with leading spaces won't match actual values → 400 incomplete."""
        mid = scale_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            mapping={" 1": "1", " 2": "2", " 3": "3", " 4": "4", " 5": "5"},
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 400

    async def test_scale_metric_with_slots(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """Scale metric with measurement slots — slot_id preserved after convert."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Scale Slots", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
            slot_labels=["Утро", "Вечер"],
        )
        mid = metric["id"]
        slots = metric["slots"]
        assert len(slots) == 2

        await create_entry(client, token, mid, "2026-02-10", 3, slot_id=slots[0]["id"])
        await create_entry(client, token, mid, "2026-02-10", 4, slot_id=slots[1]["id"])

        status, body = await _do_convert(
            client, token, mid,
            mapping={"3": "6", "4": "8"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 2

        async with db_pool.acquire() as conn:
            entries = await conn.fetch(
                "SELECT slot_id FROM entries WHERE metric_id = $1 ORDER BY slot_id", mid,
            )
            slot_ids = {r["slot_id"] for r in entries}
            assert slot_ids == {slots[0]["id"], slots[1]["id"]}

    async def test_large_number_of_entries(
        self, client: AsyncClient, user_a: dict,
    ):
        """50 entries with batch UPDATE/DELETE — CASE WHEN on 5 clauses, ANY() on 50 rows."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Large Scale", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        for i in range(50):
            val = (i % 5) + 1
            await create_entry(client, token, mid, f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", val)

        status, body = await _do_convert(
            client, token, mid,
            mapping={"1": "2", "2": "4", "3": "6", "4": "8", "5": "10"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 50
        assert body["deleted"] == 0

    async def test_remap_all_to_single_value(
        self, client: AsyncClient, user_a: dict, scale_metric_with_entries: dict, db_pool,
    ):
        """All 5 distinct values mapped to same new value."""
        mid = scale_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            mapping={"1": "5", "2": "5", "3": "5", "4": "5", "5": "5"},
            scale_min=1, scale_max=5, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT vs.value FROM values_scale vs
                   JOIN entries e ON e.id = vs.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert all(r["value"] == 5 for r in rows)

    async def test_disabled_metric_can_be_converted(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """Disabled metric must still be convertible."""
        token = user_a["token"]
        metric = await create_metric(
            client, token,
            name="Dis Scale", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        mid = metric["id"]
        await create_entry(client, token, mid, "2026-02-10", 3)

        # Disable the metric
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE metric_definitions SET enabled = FALSE WHERE id = $1", mid,
            )

        status, body = await _do_convert(
            client, token, mid,
            mapping={"3": "6"},
            scale_min=1, scale_max=10, scale_step=1,
        )
        assert status == 200
        assert body["converted"] == 1
