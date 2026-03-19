"""Additional metrics router tests to increase branch coverage."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_slot


# ── Computed metric creation validation ──────────────────────────────


class TestCreateComputedValidation:
    """POST /api/metrics — computed type validation edge cases."""

    async def test_computed_no_formula_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """type=computed without formula -> 400."""
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "No Formula",
                "type": "computed",
                "result_type": "int",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_computed_invalid_result_type_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """type=computed with invalid result_type -> 400."""
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Bad RT",
                "type": "computed",
                "formula": [{"type": "number", "value": 1}],
                "result_type": "invalid",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_computed_unknown_metric_ref_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Formula referencing non-existent metric -> 400."""
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Bad Ref",
                "type": "computed",
                "formula": [
                    {"type": "metric", "id": 999999},
                    {"type": "op", "value": "+"},
                    {"type": "number", "value": 1},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_computed_comparison_non_bool_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Formula with > operator but result_type != bool -> 400."""
        num = await create_metric(
            client, user_a["token"], name="CmpBase", metric_type="number",
        )
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Cmp Float",
                "type": "computed",
                "formula": [
                    {"type": "metric", "id": num["id"]},
                    {"type": "op", "value": ">"},
                    {"type": "number", "value": 5},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Create with slot_configs ─────────────────────────────────────────


class TestCreateWithSlotConfigs:
    """POST /api/metrics — with slot_configs (per-slot category)."""

    async def test_create_with_slot_configs_and_category(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        cat_resp = await client.post(
            "/api/categories",
            json={"name": "SlotCat"},
            headers=auth_headers(user_a["token"]),
        )
        assert cat_resp.status_code == 201
        cat_id = cat_resp.json()["id"]

        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "SlotCfg",
                "type": "number",
                "slot_configs": [
                    {"slot_id": slot_m["id"], "category_id": cat_id},
                    {"slot_id": slot_e["id"], "category_id": cat_id},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["slots"]) == 2
        assert data["category_id"] is None

    async def test_create_slot_configs_invalid_category_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "BadSlotCat",
                "type": "number",
                "slot_configs": [
                    {"slot_id": slot_a["id"], "category_id": 999999},
                    {"slot_id": slot_b["id"]},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Create condition validation ──────────────────────────────────────


class TestCreateConditionValidation:
    """POST /api/metrics — condition validation on create."""

    async def test_condition_dep_not_found_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "bool", "condition_metric_id": 999999, "condition_type": "filled",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_condition_equals_no_value_400(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="DepEq", metric_type="bool")
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "number", "condition_metric_id": dep["id"], "condition_type": "equals",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_condition_not_equals_no_value_400(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="DepNeq", metric_type="bool")
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "number", "condition_metric_id": dep["id"], "condition_type": "not_equals",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_condition_invalid_type_400(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="DepInv", metric_type="bool")
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "number", "condition_metric_id": dep["id"], "condition_type": "invalid_type",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_condition_with_equals_value(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="DepVal", metric_type="bool")
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "number", "condition_metric_id": dep["id"],
            "condition_type": "equals", "condition_value": True,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201


# ── Scale validation ─────────────────────────────────────────────────


class TestScaleValidation:
    """Scale config validation on create and update."""

    async def test_create_scale_min_ge_max_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "scale", "scale_min": 10, "scale_max": 5, "scale_step": 1,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_create_scale_step_too_large_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "scale", "scale_min": 1, "scale_max": 5, "scale_step": 100,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_update_scale_min_ge_max_400(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="scale",
                                scale_min=1, scale_max=10, scale_step=1)
        resp = await client.patch(f"/api/metrics/{m['id']}", json={"scale_min": 10, "scale_max": 5},
                                  headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_update_scale_step_too_large_400(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="scale",
                                scale_min=1, scale_max=10, scale_step=1)
        resp = await client.patch(f"/api/metrics/{m['id']}", json={"scale_step": 100},
                                  headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400


# ── Reorder with slots ───────────────────────────────────────────────


class TestReorderWithSlots:
    """POST /api/metrics/reorder — slot-level category assignment."""

    async def test_reorder_with_slot_id(self, client: AsyncClient, user_a: dict) -> None:
        cat_resp = await client.post("/api/categories", json={"name": "RC"},
                                     headers=auth_headers(user_a["token"]))
        cat_id = cat_resp.json()["id"]
        slot_am = await create_slot(client, user_a["token"], "AM")
        slot_pm = await create_slot(client, user_a["token"], "PM")
        m = await create_metric(client, user_a["token"], name="X", metric_type="number",
                                slot_configs=[{"slot_id": slot_am["id"]}, {"slot_id": slot_pm["id"]}])
        slot_id = m["slots"][0]["id"]
        resp = await client.post("/api/metrics/reorder", json=[
            {"id": m["id"], "sort_order": 0, "slot_id": slot_id, "category_id": cat_id},
        ], headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

    async def test_reorder_propagates_category_to_slots(self, client: AsyncClient, user_a: dict) -> None:
        cat_resp = await client.post("/api/categories", json={"name": "PC"},
                                     headers=auth_headers(user_a["token"]))
        cat_id = cat_resp.json()["id"]
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        m = await create_metric(client, user_a["token"], name="X", metric_type="number",
                                slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}])
        resp = await client.post("/api/metrics/reorder", json=[
            {"id": m["id"], "sort_order": 0, "category_id": cat_id},
        ], headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200


# ── Update condition edge cases ──────────────────────────────────────


class TestUpdateConditionEdgeCases:
    """PATCH /api/metrics/{id} — condition update edge cases."""

    async def test_self_dep_400(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="bool")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "condition_metric_id": m["id"], "condition_type": "filled",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_invalid_type_400(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="D", metric_type="bool")
        m = await create_metric(client, user_a["token"], name="M", metric_type="number")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "condition_metric_id": dep["id"], "condition_type": "bad",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_dep_not_found_400(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="bool")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "condition_metric_id": 999999, "condition_type": "filled",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_equals_no_value_400(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="D", metric_type="bool")
        m = await create_metric(client, user_a["token"], name="M", metric_type="number")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "condition_metric_id": dep["id"], "condition_type": "equals",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_circular_400(self, client: AsyncClient, user_a: dict) -> None:
        a = await create_metric(client, user_a["token"], name="A", metric_type="bool")
        b_resp = await client.post("/api/metrics", json={
            "name": "B", "type": "bool", "condition_metric_id": a["id"], "condition_type": "filled",
        }, headers=auth_headers(user_a["token"]))
        b = b_resp.json()
        resp = await client.patch(f"/api/metrics/{a['id']}", json={
            "condition_metric_id": b["id"], "condition_type": "filled",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_with_value_200(self, client: AsyncClient, user_a: dict) -> None:
        dep = await create_metric(client, user_a["token"], name="D", metric_type="bool")
        m = await create_metric(client, user_a["token"], name="M", metric_type="number")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "condition_metric_id": dep["id"], "condition_type": "equals", "condition_value": True,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200


# ── Other edge cases ─────────────────────────────────────────────────


class TestMiscEdgeCases:
    """Various small branch coverage tests."""

    async def test_explicit_duplicate_slug_409(self, client: AsyncClient, user_a: dict) -> None:
        await create_metric(client, user_a["token"], name="X", metric_type="bool", slug="my_slug")
        resp = await client.post("/api/metrics", json={
            "name": "Y", "type": "bool", "slug": "my_slug",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 409

    async def test_icon_update_on_bool(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="bool")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={"icon": "X"},
                                  headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

    async def test_category_id_zero_clears(self, client: AsyncClient, user_a: dict) -> None:
        cat_resp = await client.post("/api/categories", json={"name": "TC"},
                                     headers=auth_headers(user_a["token"]))
        cat_id = cat_resp.json()["id"]
        m = await create_metric(client, user_a["token"], name="X", metric_type="bool")
        await client.patch(f"/api/metrics/{m['id']}", json={"category_id": cat_id},
                          headers=auth_headers(user_a["token"]))
        resp = await client.patch(f"/api/metrics/{m['id']}", json={"category_id": 0},
                                  headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        assert resp.json()["category_id"] is None

    async def test_update_slot_configs_with_category(self, client: AsyncClient, user_a: dict) -> None:
        cat_resp = await client.post("/api/categories", json={"name": "SC"},
                                     headers=auth_headers(user_a["token"]))
        cat_id = cat_resp.json()["id"]
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        m = await create_metric(client, user_a["token"], name="X", metric_type="number",
                                slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}])
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "slot_configs": [{"slot_id": slot_a["id"], "category_id": cat_id}, {"slot_id": slot_b["id"]}],
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200

    async def test_update_slot_configs_invalid_category_400(self, client: AsyncClient, user_a: dict) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        m = await create_metric(client, user_a["token"], name="X", metric_type="number",
                                slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}])
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "slot_configs": [{"slot_id": slot_a["id"], "category_id": 999999}, {"slot_id": slot_b["id"]}],
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_update_slot_configs_first_time(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="number")
        slot_s1 = await create_slot(client, user_a["token"], "S1")
        slot_s2 = await create_slot(client, user_a["token"], "S2")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "slot_configs": [{"slot_id": slot_s1["id"]}, {"slot_id": slot_s2["id"]}],
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        assert len(resp.json()["slots"]) == 2

    async def test_update_computed_comparison_non_bool_400(self, client: AsyncClient, user_a: dict) -> None:
        num = await create_metric(client, user_a["token"], name="N", metric_type="number")
        comp_resp = await client.post("/api/metrics", json={
            "name": "C", "type": "computed", "result_type": "float",
            "formula": [{"type": "metric", "id": num["id"]}, {"type": "op", "value": "+"}, {"type": "number", "value": 1}],
        }, headers=auth_headers(user_a["token"]))
        comp = comp_resp.json()
        resp = await client.patch(f"/api/metrics/{comp['id']}", json={
            "formula": [{"type": "metric", "id": num["id"]}, {"type": "op", "value": ">"}, {"type": "number", "value": 5}],
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_update_enum_too_few_labels_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "E", "type": "enum", "enum_options": ["A", "B"],
        }, headers=auth_headers(user_a["token"]))
        m = resp.json()
        resp = await client.patch(f"/api/metrics/{m['id']}", json={
            "enum_options": [{"label": "Only"}],
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_single_slot_config_no_existing_noop(self, client: AsyncClient, user_a: dict) -> None:
        m = await create_metric(client, user_a["token"], name="X", metric_type="number")
        slot_only = await create_slot(client, user_a["token"], "Only")
        resp = await client.patch(f"/api/metrics/{m['id']}", json={"slot_configs": [{"slot_id": slot_only["id"]}]},
                                  headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        assert len(resp.json()["slots"]) == 0

    async def test_integration_no_metric_key_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "todoist",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_todoist_unknown_key_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "todoist", "metric_key": "bad",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_todoist_not_connected_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "todoist", "metric_key": "completed_tasks_count",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_aw_unknown_key_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "activitywatch", "metric_key": "bad",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_aw_not_enabled_400(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "activitywatch", "metric_key": "active_screen_time",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_todoist_filter_tasks_no_filter_name_400(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """filter_tasks_count without filter_name -> 400."""
        # Connect todoist first
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_integrations (user_id, provider, encrypted_token, enabled)"
                " VALUES ($1, 'todoist', 'tok', TRUE)",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "todoist",
            "metric_key": "filter_tasks_count",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_todoist_query_tasks_no_query_400(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """query_tasks_count without filter_query -> 400."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_integrations (user_id, provider, encrypted_token, enabled)"
                " VALUES ($1, 'todoist', 'tok', TRUE)",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "todoist",
            "metric_key": "query_tasks_count",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_todoist_filter_tasks_created(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """filter_tasks_count with valid filter_name -> 201."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_integrations (user_id, provider, encrypted_token, enabled)"
                " VALUES ($1, 'todoist', 'tok', TRUE)",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "Filter", "type": "integration", "provider": "todoist",
            "metric_key": "filter_tasks_count", "filter_name": "MyFilter",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201

    async def test_todoist_query_tasks_created(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """query_tasks_count with valid filter_query -> 201."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_integrations (user_id, provider, encrypted_token, enabled)"
                " VALUES ($1, 'todoist', 'tok', TRUE)",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "Query", "type": "integration", "provider": "todoist",
            "metric_key": "query_tasks_count", "filter_query": "due today",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201

    async def test_aw_category_time_no_cat_400(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """category_time without category_id -> 400."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activitywatch_settings (user_id, enabled, aw_url)"
                " VALUES ($1, TRUE, 'http://localhost:5600')",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "activitywatch",
            "metric_key": "category_time",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_aw_category_time_bad_cat_400(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """category_time with non-existent category -> 400."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activitywatch_settings (user_id, enabled, aw_url)"
                " VALUES ($1, TRUE, 'http://localhost:5600')",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "activitywatch",
            "metric_key": "category_time", "activitywatch_category_id": 999999,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_aw_category_time_created(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """category_time with valid category -> 201."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activitywatch_settings (user_id, enabled, aw_url)"
                " VALUES ($1, TRUE, 'http://localhost:5600')",
                user_a["user_id"],
            )
            cat_id = await conn.fetchval(
                "INSERT INTO activitywatch_categories (user_id, name, color, sort_order)"
                " VALUES ($1, 'Work', '#ff0000', 0) RETURNING id",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "CatTime", "type": "integration", "provider": "activitywatch",
            "metric_key": "category_time", "activitywatch_category_id": cat_id,
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201

    async def test_aw_app_time_no_name_400(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """app_time without app_name -> 400."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activitywatch_settings (user_id, enabled, aw_url)"
                " VALUES ($1, TRUE, 'http://localhost:5600')",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "activitywatch",
            "metric_key": "app_time",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400

    async def test_aw_app_time_created(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """app_time with valid app_name -> 201."""
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activitywatch_settings (user_id, enabled, aw_url)"
                " VALUES ($1, TRUE, 'http://localhost:5600')",
                user_a["user_id"],
            )
        resp = await client.post("/api/metrics", json={
            "name": "AppTime", "type": "integration", "provider": "activitywatch",
            "metric_key": "app_time", "app_name": "Chrome",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 201

    async def test_unknown_provider_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Unknown provider -> 400."""
        resp = await client.post("/api/metrics", json={
            "name": "X", "type": "integration", "provider": "github",
            "metric_key": "stars",
        }, headers=auth_headers(user_a["token"]))
        assert resp.status_code == 400
