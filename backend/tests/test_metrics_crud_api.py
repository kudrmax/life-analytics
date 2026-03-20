"""API integration tests for metrics CRUD operations."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_slot


# ── Create ────────────────────────────────────────────────────────────


class TestCreateBoolMetric:
    """POST /api/metrics — bool type."""

    async def test_create_bool_metric(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Зарядка", "type": "bool"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "bool"
        assert data["name"] == "Зарядка"
        assert data["slug"]  # auto-generated slug is non-empty
        assert data["enabled"] is True


class TestCreateNumberMetric:
    """POST /api/metrics — number type."""

    async def test_create_number_metric(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Steps", "type": "number"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "number"
        assert data["name"] == "Steps"


class TestCreateTimeMetric:
    """POST /api/metrics — time type."""

    async def test_create_time_metric(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Wake Up", "type": "time"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "time"


class TestCreateDurationMetric:
    """POST /api/metrics — duration type."""

    async def test_create_duration_metric(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Reading", "type": "duration"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "duration"


class TestCreateScaleMetric:
    """POST /api/metrics — scale type with config."""

    async def test_create_scale_metric_with_config(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Mood",
                "type": "scale",
                "scale_min": 1,
                "scale_max": 10,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "scale"
        assert data["scale_min"] == 1
        assert data["scale_max"] == 10
        assert data["scale_step"] == 1


class TestCreateEnumMetric:
    """POST /api/metrics — enum type with options."""

    async def test_create_enum_metric_with_options(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Weather",
                "type": "enum",
                "enum_options": ["Sunny", "Cloudy", "Rain"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "enum"
        assert data["enum_options"] is not None
        labels = [opt["label"] for opt in data["enum_options"]]
        assert labels == ["Sunny", "Cloudy", "Rain"]


class TestCreateTextMetric:
    """POST /api/metrics — text type."""

    async def test_create_text_metric(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Journal", "type": "text"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "text"


class TestCreateComputedMetric:
    """POST /api/metrics — computed type with formula."""

    async def test_create_computed_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Need a number metric to reference in the formula
        number_metric = await create_metric(
            client, user_a["token"], name="Base Number", metric_type="number",
        )
        mid = number_metric["id"]

        formula = [
            {"type": "metric", "id": mid},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Computed",
                "type": "computed",
                "formula": formula,
                "result_type": "int",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "computed"
        assert data["result_type"] == "int"
        assert data["formula"] is not None
        assert len(data["formula"]) == 3


class TestCreateWithCustomSlug:
    """POST /api/metrics — custom slug."""

    async def test_create_with_custom_slug(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "My Metric", "type": "bool", "slug": "custom_slug"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["slug"] == "custom_slug"


class TestCreateWithSlots:
    """POST /api/metrics — with measurement slots."""

    async def test_create_with_slot_configs(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_am = await create_slot(client, user_a["token"], "AM")
        slot_pm = await create_slot(client, user_a["token"], "PM")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Pressure",
                "type": "number",
                "slot_configs": [{"slot_id": slot_am["id"]}, {"slot_id": slot_pm["id"]}],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["slots"]) == 2
        slot_labels = [s["label"] for s in data["slots"]]
        assert slot_labels == ["AM", "PM"]


class TestCreateWithCondition:
    """POST /api/metrics — with condition on another metric."""

    async def test_create_with_condition_filled(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        dep_metric = await create_metric(
            client, user_a["token"], name="Dependency", metric_type="bool",
        )
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Conditional",
                "type": "number",
                "condition_metric_id": dep_metric["id"],
                "condition_type": "filled",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["condition_metric_id"] == dep_metric["id"]
        assert data["condition_type"] == "filled"


class TestCreateWithInlineCategory:
    """POST /api/metrics — with new_category_name for inline category creation."""

    async def test_create_with_new_category_name(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Metric With Cat",
                "type": "bool",
                "new_category_name": "Health",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["category_id"] is not None


class TestCreatePrivateMetric:
    """POST /api/metrics — with private=true."""

    async def test_create_private_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Secret", "type": "bool", "private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        assert resp.json()["private"] is True


class TestDuplicateSlugAutoIncrement:
    """POST /api/metrics — duplicate name auto-increments slug."""

    async def test_duplicate_slug_auto_increments(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(
            client, user_a["token"], name="Same Name", metric_type="bool",
        )
        m2 = await create_metric(
            client, user_a["token"], name="Same Name", metric_type="bool",
        )
        assert m1["slug"] != m2["slug"]
        # Second slug should be base_slug + "_2"
        assert m2["slug"] == m1["slug"] + "_2"


# ── Get / List ────────────────────────────────────────────────────────


class TestListMetrics:
    """GET /api/metrics"""

    async def test_list_returns_created_metrics(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(client, user_a["token"], name="Metric A", metric_type="bool")
        await create_metric(client, user_a["token"], name="Metric B", metric_type="number")

        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [m["name"] for m in data]
        assert "Metric A" in names
        assert "Metric B" in names

    async def test_list_enabled_only_excludes_disabled(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(
            client, user_a["token"], name="Active", metric_type="bool",
        )
        m2 = await create_metric(
            client, user_a["token"], name="Inactive", metric_type="bool",
        )
        # Disable second metric
        await client.patch(
            f"/api/metrics/{m2['id']}",
            json={"enabled": False},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get(
            "/api/metrics",
            params={"enabled_only": "true"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert m1["id"] in ids
        assert m2["id"] not in ids


class TestGetSingleMetric:
    """GET /api/metrics/{id}"""

    async def test_get_single_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Detail", metric_type="bool",
        )
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == metric["id"]
        assert data["name"] == "Detail"
        assert data["type"] == "bool"

    async def test_get_nonexistent_metric_returns_404(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.get(
            "/api/metrics/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ── Update ────────────────────────────────────────────────────────────


class TestUpdateMetric:
    """PATCH /api/metrics/{id}"""

    async def test_rename_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Old Name", metric_type="bool",
        )
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"name": "New Name"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_toggle_enabled(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Toggle Me", metric_type="bool",
        )
        assert metric["enabled"] is True

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"enabled": False},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_update_scale_config(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"],
            name="Scale Upd", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"scale_min": 0, "scale_max": 100, "scale_step": 10},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scale_min"] == 0
        assert data["scale_max"] == 100
        assert data["scale_step"] == 10

    async def test_update_enum_options(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Fruit",
                "type": "enum",
                "enum_options": ["Apple", "Banana"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        existing_opts = metric["enum_options"]
        apple_id = next(o["id"] for o in existing_opts if o["label"] == "Apple")

        # Update: rename Apple->Apricot, add Cherry
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "enum_options": [
                    {"id": apple_id, "label": "Apricot"},
                    {"label": "Cherry"},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = [o["label"] for o in data["enum_options"] if o.get("enabled", True)]
        assert "Apricot" in labels
        assert "Cherry" in labels

    async def test_update_private_flag(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Priv Toggle", metric_type="bool",
        )
        assert metric["private"] is False

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["private"] is True

    async def test_update_condition_set_and_remove(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        dep = await create_metric(
            client, user_a["token"], name="Dep Metric", metric_type="bool",
        )
        metric = await create_metric(
            client, user_a["token"], name="Cond Metric", metric_type="number",
        )

        # Set condition
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "condition_metric_id": dep["id"],
                "condition_type": "filled",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["condition_metric_id"] == dep["id"]
        assert data["condition_type"] == "filled"

        # Remove condition
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"remove_condition": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["condition_metric_id"] is None
        assert data["condition_type"] is None

    async def test_update_nonexistent_returns_404(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.patch(
            "/api/metrics/999999",
            json={"name": "Ghost"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────


class TestDeleteMetric:
    """DELETE /api/metrics/{id}"""

    async def test_delete_existing_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="To Delete", metric_type="bool",
        )
        resp = await client.delete(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.delete(
            "/api/metrics/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ── Reorder ───────────────────────────────────────────────────────────


class TestReorderMetrics:
    """POST /api/metrics/reorder"""

    async def test_reorder_changes_sort_order(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(
            client, user_a["token"], name="First", metric_type="bool",
        )
        m2 = await create_metric(
            client, user_a["token"], name="Second", metric_type="bool",
        )

        # Swap order: m2 first, m1 second
        resp = await client.post(
            "/api/metrics/reorder",
            json=[
                {"id": m2["id"], "sort_order": 0},
                {"id": m1["id"], "sort_order": 1},
            ],
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Verify new order
        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        data = resp.json()
        ids = [m["id"] for m in data]
        assert ids.index(m2["id"]) < ids.index(m1["id"])


# ── Privacy masking ───────────────────────────────────────────────────


class TestPrivacyMasking:
    """Privacy mode masks private metrics."""

    async def _enable_privacy(self, client: AsyncClient, token: str) -> None:
        resp = await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200

    async def test_list_masks_private_metric_when_privacy_on(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await client.post(
            "/api/metrics",
            json={"name": "Secret Metric", "type": "bool", "private": True, "icon": "🏃"},
            headers=auth_headers(user_a["token"]),
        )
        await self._enable_privacy(client, user_a["token"])

        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "***"
        assert data[0]["icon"] == "🔒"

    async def test_get_single_private_metric_masked_when_privacy_on(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric_resp = await client.post(
            "/api/metrics",
            json={"name": "Private Detail", "type": "bool", "private": True, "icon": "💊"},
            headers=auth_headers(user_a["token"]),
        )
        metric = metric_resp.json()
        await self._enable_privacy(client, user_a["token"])

        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "***"
        assert data["icon"] == "🔒"


# ── Data isolation ────────────────────────────────────────────────────


class TestDataIsolation:
    """Users cannot access each other's metrics."""

    async def test_user_a_cannot_see_user_b_metrics(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await create_metric(
            client, user_b["token"], name="B Only", metric_type="bool",
        )

        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        names = [m["name"] for m in resp.json()]
        assert "B Only" not in names

    async def test_user_a_cannot_update_user_b_metric(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_b["token"], name="B Metric", metric_type="bool",
        )
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"name": "Hacked"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_user_a_cannot_delete_user_b_metric(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_b["token"], name="B Undeletable", metric_type="bool",
        )
        resp = await client.delete(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

        # Verify it still exists for user_b
        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200


# ── Update computed metrics ──────────────────────────────────────────


class TestUpdateComputedFormula:
    """PATCH /api/metrics/{id} — update computed metric formula."""

    async def test_update_computed_formula(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        num = await create_metric(
            client, user_a["token"], name="Base A", metric_type="number",
        )
        mid = num["id"]

        original_formula = [
            {"type": "metric", "id": mid},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Comp Formula",
                "type": "computed",
                "formula": original_formula,
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        comp = resp.json()

        new_formula = [
            {"type": "metric", "id": mid},
            {"type": "op", "value": "*"},
            {"type": "number", "value": 2},
        ]
        resp = await client.patch(
            f"/api/metrics/{comp['id']}",
            json={"formula": new_formula},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["formula"]) == 3
        ops = [t["value"] for t in data["formula"] if t["type"] == "op"]
        assert ops == ["*"]


class TestUpdateComputedResultType:
    """PATCH /api/metrics/{id} — update computed metric result_type."""

    async def test_update_computed_result_type(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        num = await create_metric(
            client, user_a["token"], name="Base RT", metric_type="number",
        )
        mid = num["id"]

        formula = [
            {"type": "metric", "id": mid},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Comp RT",
                "type": "computed",
                "formula": formula,
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        comp = resp.json()
        assert comp["result_type"] == "float"

        resp = await client.patch(
            f"/api/metrics/{comp['id']}",
            json={"result_type": "int"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["result_type"] == "int"


class TestUpdateComputedFormulaValidation:
    """PATCH /api/metrics/{id} — formula referencing nonexistent metric → 400."""

    async def test_update_computed_formula_invalid_ref(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        num = await create_metric(
            client, user_a["token"], name="Base Val", metric_type="number",
        )
        mid = num["id"]

        formula = [
            {"type": "metric", "id": mid},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Comp Val",
                "type": "computed",
                "formula": formula,
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        comp = resp.json()

        bad_formula = [
            {"type": "metric", "id": 999999},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        resp = await client.patch(
            f"/api/metrics/{comp['id']}",
            json={"formula": bad_formula},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Update enum metrics ──────────────────────────────────────────────


class TestPatchEnumMultiSelect:
    """PATCH /api/metrics/{id} — toggle multi_select on enum metric."""

    async def test_patch_enum_multi_select(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Multi Enum",
                "type": "enum",
                "enum_options": ["X", "Y", "Z"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"multi_select": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["multi_select"] is True


class TestPatchEnumOptionsAddRemove:
    """PATCH /api/metrics/{id} — rename, disable, and add enum options."""

    async def test_patch_enum_options_add_remove(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Fruit Opts",
                "type": "enum",
                "enum_options": ["A", "B", "C"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        opts = metric["enum_options"]
        a_id = next(o["id"] for o in opts if o["label"] == "A")
        b_id = next(o["id"] for o in opts if o["label"] == "B")

        # Keep A, rename B→B_renamed, drop C, add D
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "enum_options": [
                    {"id": a_id, "label": "A"},
                    {"id": b_id, "label": "B_renamed"},
                    {"label": "D"},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/metrics/{metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        all_opts = resp.json()["enum_options"]
        labels = [o["label"] for o in all_opts]
        assert "A" in labels
        assert "B_renamed" in labels
        assert "D" in labels
        # C was not in the PATCH list, so it should be disabled (excluded from enabled-only response)
        assert "C" not in labels


class TestPatchEnumOptionsDuplicateLabel:
    """PATCH /api/metrics/{id} — duplicate enum option labels → 400."""

    async def test_patch_enum_options_duplicate_label(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Dup Opts",
                "type": "enum",
                "enum_options": ["A", "B"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={
                "enum_options": [
                    {"label": "Same"},
                    {"label": "Same"},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Update slots ─────────────────────────────────────────────────────


class TestPatchSlotLabelsFirstTime:
    """PATCH /api/metrics/{id} — add slots to a metric that had none; entries migrate."""

    async def test_patch_slot_labels_first_time(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Slottable", metric_type="number",
        )
        entry_date = "2026-03-10"
        await create_entry(
            client, user_a["token"], metric["id"], entry_date, 42,
        )

        slot_m = await create_slot(client, user_a["token"], "Morning")
        slot_e = await create_slot(client, user_a["token"], "Evening")
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [{"slot_id": slot_m["id"]}, {"slot_id": slot_e["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 2
        slot_labels = [s["label"] for s in data["slots"]]
        assert slot_labels == ["Morning", "Evening"]

        # Verify existing entry was migrated to first slot via daily endpoint
        resp = await client.get(
            f"/api/daily/{entry_date}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        daily = resp.json()
        metric_data = next(
            (m for m in daily["metrics"] if m["metric_id"] == metric["id"]), None,
        )
        assert metric_data is not None
        assert metric_data["slots"] is not None
        assert len(metric_data["slots"]) == 2
        # First slot should have the migrated value
        first_slot = metric_data["slots"][0]
        assert first_slot["entry"] is not None
        assert first_slot["entry"]["value"] == 42


class TestPatchSlotLabelsUpdate:
    """PATCH /api/metrics/{id} — update existing slot labels and add new ones."""

    async def test_patch_slot_labels_update(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        metric = await create_metric(
            client, user_a["token"],
            name="Slotted", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        assert len(metric["slots"]) == 2

        slot_c = await create_slot(client, user_a["token"], "C")
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [
                {"slot_id": slot_a["id"]},
                {"slot_id": slot_b["id"]},
                {"slot_id": slot_c["id"]},
            ]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        enabled_slots = [s for s in data["slots"] if s.get("enabled", True)]
        assert len(enabled_slots) == 3
        labels = [s["label"] for s in enabled_slots]
        assert labels == ["A", "B", "C"]


class TestPatchSlotLabelsReduceFails:
    """PATCH /api/metrics/{id} — reducing to fewer than 2 slots → 400."""

    async def test_patch_slot_labels_reduce_fails(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        metric = await create_metric(
            client, user_a["token"],
            name="Reduce Slots", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [{"slot_id": slot_a["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


class TestPatchSlotLabelsDisableExtra:
    """PATCH /api/metrics/{id} — reducing from 3 to 2 slots disables the third."""

    async def test_patch_slot_labels_disable_extra(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        slot_c = await create_slot(client, user_a["token"], "C")
        metric = await create_metric(
            client, user_a["token"],
            name="Disable Slot", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}, {"slot_id": slot_c["id"]}],
        )
        assert len(metric["slots"]) == 3

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        enabled_slots = [s for s in data["slots"] if s.get("enabled", True)]
        assert len(enabled_slots) == 2
        labels = [s["label"] for s in enabled_slots]
        assert labels == ["A", "B"]


# ── Create validation: integration & enum ────────────────────────────


class TestCreateIntegrationMetricNoProvider:
    """POST /api/metrics — type=integration without provider → 400."""

    async def test_create_integration_no_provider(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "No Provider", "type": "integration"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


class TestCreateIntegrationMetricUnknownProvider:
    """POST /api/metrics — type=integration with unknown provider → 400."""

    async def test_create_integration_unknown_provider(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Bad Provider",
                "type": "integration",
                "provider": "unknown",
                "metric_key": "x",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


class TestCreateEnumMetricTooFewOptions:
    """POST /api/metrics — enum with only 1 option → 400."""

    async def test_create_enum_too_few_options(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Too Few",
                "type": "enum",
                "enum_options": ["Only"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


class TestCreateEnumMetricDuplicateLabels:
    """POST /api/metrics — enum with duplicate labels → 400."""

    async def test_create_enum_duplicate_labels(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Dup Labels",
                "type": "enum",
                "enum_options": ["A", "A", "B"],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Slot reorder / add (id-based matching) ───────────────────────────


class TestSlotReorderAndAdd:
    """PATCH /api/metrics — slot reorder and insert must preserve entries."""

    async def test_reorder_slots_preserves_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        metric = await create_metric(
            client, user_a["token"],
            name="Reorder", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        slot_a = metric["slots"][0]
        slot_b = metric["slots"][1]

        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 10, slot_id=slot_a["id"])
        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 20, slot_id=slot_b["id"])

        # Swap order: B first, A second (in slot_configs)
        # But API returns slots sorted by global sort_order (A=0, B=1)
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [
                {"slot_id": slot_b["id"]},
                {"slot_id": slot_a["id"]},
            ]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        slots = data["slots"]
        assert slots[0]["id"] == slot_a["id"]
        assert slots[0]["label"] == "A"
        assert slots[1]["id"] == slot_b["id"]
        assert slots[1]["label"] == "B"

        # Verify entries still attached to original slot ids
        daily_resp = await client.get(
            "/api/daily/2026-03-10",
            headers=auth_headers(user_a["token"]),
        )
        assert daily_resp.status_code == 200
        m_data = next(m for m in daily_resp.json()["metrics"] if m["metric_id"] == metric["id"])
        slot_values = {s["slot_id"]: s["entry"]["value"] for s in m_data["slots"] if s["entry"]}
        assert slot_values[slot_a["id"]] == 10
        assert slot_values[slot_b["id"]] == 20

    async def test_add_slot_in_middle_preserves_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        metric = await create_metric(
            client, user_a["token"],
            name="Middle", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        slot_a = metric["slots"][0]
        slot_b = metric["slots"][1]

        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 10, slot_id=slot_a["id"])
        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 20, slot_id=slot_b["id"])

        # Insert new slot in the middle
        slot_new = await create_slot(client, user_a["token"], "New")
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [
                {"slot_id": slot_a["id"]},
                {"slot_id": slot_new["id"]},
                {"slot_id": slot_b["id"]},
            ]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 3
        # Slots returned in global sort_order: A(0), B(1), New(2)
        slots = data["slots"]
        assert slots[0]["id"] == slot_a["id"]
        assert slots[1]["id"] == slot_b["id"]
        assert slots[2]["label"] == "New"

        # Entries still on original slots
        daily_resp = await client.get(
            "/api/daily/2026-03-10",
            headers=auth_headers(user_a["token"]),
        )
        assert daily_resp.status_code == 200
        m_data = next(m for m in daily_resp.json()["metrics"] if m["metric_id"] == metric["id"])
        slot_values = {s["slot_id"]: s["entry"]["value"] for s in m_data["slots"] if s["entry"]}
        assert slot_values[slot_a["id"]] == 10
        assert slot_values[slot_b["id"]] == 20
        new_slot = next(s for s in m_data["slots"] if s["label"] == "New")
        assert new_slot["entry"] is None

    async def test_add_slot_at_end(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        slot_a = await create_slot(client, user_a["token"], "A")
        slot_b = await create_slot(client, user_a["token"], "B")
        metric = await create_metric(
            client, user_a["token"],
            name="End", metric_type="number",
            slot_configs=[{"slot_id": slot_a["id"]}, {"slot_id": slot_b["id"]}],
        )
        slot_a = metric["slots"][0]
        slot_b = metric["slots"][1]

        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 10, slot_id=slot_a["id"])
        await create_entry(client, user_a["token"], metric["id"], "2026-03-10", 20, slot_id=slot_b["id"])

        slot_c = await create_slot(client, user_a["token"], "C")
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"slot_configs": [
                {"slot_id": slot_a["id"]},
                {"slot_id": slot_b["id"]},
                {"slot_id": slot_c["id"]},
            ]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["slots"]) == 3
        slots = sorted(data["slots"], key=lambda s: s["sort_order"])
        assert slots[0]["id"] == slot_a["id"]
        assert slots[1]["id"] == slot_b["id"]
        assert slots[2]["label"] == "C"

    async def test_other_users_slot_rejected(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        """Using another user's slot_id should be rejected."""
        slot_own = await create_slot(client, user_a["token"], "Own")
        slot_other = await create_slot(client, user_b["token"], "Other")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Test", "type": "number",
                "slot_configs": [
                    {"slot_id": slot_own["id"]},
                    {"slot_id": slot_other["id"]},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ── Scale Labels ──────────────────────────────────────────────────────


class TestCreateScaleMetricWithLabels:
    """POST /api/metrics — scale type with labels."""

    async def test_create_scale_with_labels(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Charge",
                "type": "scale",
                "scale_min": 0,
                "scale_max": 2,
                "scale_step": 1,
                "scale_labels": {"0": "нет", "1": "мало", "2": "достаточно"},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["scale_labels"] == {"0": "нет", "1": "мало", "2": "достаточно"}

    async def test_create_scale_without_labels(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Plain Scale",
                "type": "scale",
                "scale_min": 1,
                "scale_max": 5,
                "scale_step": 1,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["scale_labels"] is None


class TestUpdateScaleLabels:
    """PATCH /api/metrics — update scale labels."""

    async def test_add_labels_to_existing_scale(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"],
            name="Rating", metric_type="scale",
            scale_min=0, scale_max=2, scale_step=1,
        )
        assert metric["scale_labels"] is None

        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"scale_labels": {"0": "bad", "2": "good"}},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scale_labels"] == {"0": "bad", "2": "good"}

    async def test_clear_labels_with_empty_dict(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Clearable",
                "type": "scale",
                "scale_min": 0,
                "scale_max": 2,
                "scale_step": 1,
                "scale_labels": {"0": "a", "1": "b", "2": "c"},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()
        assert metric["scale_labels"] is not None

        # Clear labels by sending empty dict
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"scale_labels": {}},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["scale_labels"] is None

    async def test_update_labels_preserves_scale_range(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"],
            name="Preserve Range", metric_type="scale",
            scale_min=1, scale_max=3, scale_step=1,
        )
        resp = await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"scale_labels": {"1": "low", "3": "high"}},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scale_min"] == 1
        assert data["scale_max"] == 3
        assert data["scale_labels"] == {"1": "low", "3": "high"}
