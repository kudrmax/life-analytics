"""API integration tests for the insights router."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric


class TestCreateInsight:
    """POST /api/insights"""

    async def test_create_insight_text_only(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/insights",
            json={"text": "Sleep correlates with mood", "metrics": []},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["text"] == "Sleep correlates with mood"
        assert data["metrics"] == []
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_insight_with_linked_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Sleep", metric_type="number",
        )
        resp = await client.post(
            "/api/insights",
            json={
                "text": "More sleep = better mood",
                "metrics": [{"metric_id": metric["id"]}],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["metrics"]) == 1
        m = data["metrics"][0]
        assert m["metric_id"] == metric["id"]
        assert m["metric_name"] == "Sleep"
        assert m["sort_order"] == 0

    async def test_create_insight_with_custom_label(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/insights",
            json={
                "text": "Weather affects energy",
                "metrics": [{"custom_label": "Weather"}],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["metrics"]) == 1
        m = data["metrics"][0]
        assert m["metric_id"] is None
        assert m["custom_label"] == "Weather"

    async def test_create_insight_with_mixed_metrics(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Exercise", metric_type="bool",
        )
        resp = await client.post(
            "/api/insights",
            json={
                "text": "Exercise and sunshine improve mood",
                "metrics": [
                    {"metric_id": metric["id"]},
                    {"custom_label": "Sunshine"},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["metrics"]) == 2
        assert data["metrics"][0]["metric_id"] == metric["id"]
        assert data["metrics"][0]["metric_name"] == "Exercise"
        assert data["metrics"][1]["metric_id"] is None
        assert data["metrics"][1]["custom_label"] == "Sunshine"


class TestListInsights:
    """GET /api/insights"""

    async def test_list_insights_with_resolved_metrics(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Mood", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=1,
        )
        # Create two insights
        await client.post(
            "/api/insights",
            json={"text": "First insight", "metrics": [{"metric_id": metric["id"]}]},
            headers=auth_headers(user_a["token"]),
        )
        await client.post(
            "/api/insights",
            json={"text": "Second insight", "metrics": []},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get(
            "/api/insights",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        insights = resp.json()
        assert len(insights) == 2

        # Find the insight with a metric
        with_metric = [i for i in insights if len(i["metrics"]) > 0]
        assert len(with_metric) == 1
        assert with_metric[0]["metrics"][0]["metric_name"] == "Mood"


class TestUpdateInsight:
    """PUT /api/insights/{id}"""

    async def test_update_text(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        create_resp = await client.post(
            "/api/insights",
            json={"text": "Original text", "metrics": []},
            headers=auth_headers(token),
        )
        insight_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/insights/{insight_id}",
            json={"text": "Updated text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated text"
        assert resp.json()["id"] == insight_id

    async def test_update_metrics(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Sleep", metric_type="number",
        )
        create_resp = await client.post(
            "/api/insights",
            json={"text": "Insight", "metrics": []},
            headers=auth_headers(token),
        )
        insight_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/insights/{insight_id}",
            json={"metrics": [{"metric_id": metric["id"]}, {"custom_label": "Coffee"}]},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metrics"]) == 2
        assert data["metrics"][0]["metric_id"] == metric["id"]
        assert data["metrics"][0]["metric_name"] == "Sleep"
        assert data["metrics"][1]["custom_label"] == "Coffee"

    async def test_update_nonexistent_insight(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.put(
            "/api/insights/999999",
            json={"text": "New text"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


class TestDeleteInsight:
    """DELETE /api/insights/{id}"""

    async def test_delete_insight(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        token = user_a["token"]
        create_resp = await client.post(
            "/api/insights",
            json={"text": "To delete", "metrics": []},
            headers=auth_headers(token),
        )
        insight_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/insights/{insight_id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get(
            "/api/insights",
            headers=auth_headers(token),
        )
        assert all(i["id"] != insight_id for i in list_resp.json())

    async def test_delete_nonexistent_insight(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.delete(
            "/api/insights/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


class TestInsightsDataIsolation:
    """Users cannot access each other's insights."""

    async def test_cannot_see_other_users_insights(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await client.post(
            "/api/insights",
            json={"text": "Private insight", "metrics": []},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get(
            "/api/insights",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    async def test_cannot_update_other_users_insight(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        create_resp = await client.post(
            "/api/insights",
            json={"text": "User A insight", "metrics": []},
            headers=auth_headers(user_a["token"]),
        )
        insight_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/insights/{insight_id}",
            json={"text": "Hacked"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_cannot_delete_other_users_insight(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        create_resp = await client.post(
            "/api/insights",
            json={"text": "User A insight", "metrics": []},
            headers=auth_headers(user_a["token"]),
        )
        insight_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/insights/{insight_id}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404
