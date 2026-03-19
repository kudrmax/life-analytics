"""Integration tests for the categories router (/api/categories)."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_category(
    client: AsyncClient,
    token: str,
    name: str,
    parent_id: int | None = None,
) -> dict:
    payload: dict = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = await client.post(
        "/api/categories", json=payload, headers=auth_headers(token),
    )
    return resp.json() if resp.status_code < 300 else {}, resp  # type: ignore[return-value]


async def _create_cat(
    client: AsyncClient, token: str, name: str, parent_id: int | None = None,
) -> dict:
    """Shorthand that asserts 201 and returns the response body."""
    payload: dict = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = await client.post(
        "/api/categories", json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateCategory:

    async def test_create_top_level(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/categories",
            json={"name": "Work"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Work"
        assert body["parent_id"] is None
        assert "id" in body

    async def test_create_subcategory(self, client: AsyncClient, user_a: dict) -> None:
        parent = await _create_cat(client, user_a["token"], "Health")
        resp = await client.post(
            "/api/categories",
            json={"name": "Sleep", "parent_id": parent["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["parent_id"] == parent["id"]
        assert body["name"] == "Sleep"

    async def test_create_depth_exceeds_two_levels(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        parent = await _create_cat(client, user_a["token"], "Level1")
        child = await _create_cat(client, user_a["token"], "Level2", parent_id=parent["id"])
        resp = await client.post(
            "/api/categories",
            json={"name": "Level3", "parent_id": child["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_create_duplicate_name(self, client: AsyncClient, user_a: dict) -> None:
        await _create_cat(client, user_a["token"], "Fitness")
        resp = await client.post(
            "/api/categories",
            json={"name": "Fitness"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 409

    async def test_create_empty_name(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.post(
            "/api/categories",
            json={"name": "   "},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListCategories:

    async def test_empty_list(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_tree_structure(self, client: AsyncClient, user_a: dict) -> None:
        parent = await _create_cat(client, user_a["token"], "Health")
        child1 = await _create_cat(client, user_a["token"], "Sleep", parent_id=parent["id"])
        child2 = await _create_cat(client, user_a["token"], "Exercise", parent_id=parent["id"])

        resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        tree = resp.json()

        # One top-level node
        assert len(tree) == 1
        assert tree[0]["id"] == parent["id"]
        assert tree[0]["name"] == "Health"

        # Two children nested
        children_ids = {c["id"] for c in tree[0]["children"]}
        assert children_ids == {child1["id"], child2["id"]}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class TestUpdateCategory:

    async def test_rename(self, client: AsyncClient, user_a: dict) -> None:
        cat = await _create_cat(client, user_a["token"], "Old Name")
        resp = await client.patch(
            f"/api/categories/{cat['id']}",
            json={"name": "New Name"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_move_to_another_parent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        parent_a = await _create_cat(client, user_a["token"], "Parent A")
        parent_b = await _create_cat(client, user_a["token"], "Parent B")
        child = await _create_cat(
            client, user_a["token"], "Child", parent_id=parent_a["id"],
        )

        resp = await client.patch(
            f"/api/categories/{child['id']}",
            json={"parent_id": parent_b["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["parent_id"] == parent_b["id"]

    async def test_update_not_found(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.patch(
            "/api/categories/999999",
            json={"name": "X"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

    async def test_cannot_be_own_parent(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        cat = await _create_cat(client, user_a["token"], "Self Ref")
        resp = await client.patch(
            f"/api/categories/{cat['id']}",
            json={"parent_id": cat["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_nothing_to_update(self, client: AsyncClient, user_a: dict) -> None:
        cat = await _create_cat(client, user_a["token"], "Static")
        resp = await client.patch(
            f"/api/categories/{cat['id']}",
            json={},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteCategory:

    async def test_delete_existing(self, client: AsyncClient, user_a: dict) -> None:
        cat = await _create_cat(client, user_a["token"], "Doomed")
        resp = await client.delete(
            f"/api/categories/{cat['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        assert all(c["id"] != cat["id"] for c in list_resp.json())

    async def test_delete_not_found(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.delete(
            "/api/categories/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------

class TestReorderCategories:

    async def test_reorder_changes_sort_order(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        cat_a = await _create_cat(client, user_a["token"], "Alpha")
        cat_b = await _create_cat(client, user_a["token"], "Beta")
        cat_c = await _create_cat(client, user_a["token"], "Gamma")

        # Reverse the order
        resp = await client.post(
            "/api/categories/reorder",
            json=[
                {"id": cat_c["id"], "sort_order": 0, "parent_id": None},
                {"id": cat_b["id"], "sort_order": 1, "parent_id": None},
                {"id": cat_a["id"], "sort_order": 2, "parent_id": None},
            ],
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        list_resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        names = [c["name"] for c in list_resp.json()]
        assert names == ["Gamma", "Beta", "Alpha"]


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestDataIsolation:

    async def test_user_a_cannot_see_user_b_categories(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await _create_cat(client, user_b["token"], "Secret")

        resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_user_a_cannot_delete_user_b_category(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        cat = await _create_cat(client, user_b["token"], "Protected")

        resp = await client.delete(
            f"/api/categories/{cat['id']}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404

        # Verify it still exists for user_b
        list_resp = await client.get(
            "/api/categories", headers=auth_headers(user_b["token"]),
        )
        assert any(c["id"] == cat["id"] for c in list_resp.json())
