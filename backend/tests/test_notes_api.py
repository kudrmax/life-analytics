"""API integration tests for the notes router."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric


class TestCreateNote:
    """POST /api/notes"""

    async def test_create_note_for_text_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "Hello world"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["metric_id"] == metric["id"]
        assert data["date"] == "2026-03-10"
        assert data["text"] == "Hello world"
        assert "id" in data
        assert "created_at" in data

    async def test_create_note_empty_text(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "   "},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    async def test_create_note_for_non_text_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Steps", metric_type="number",
        )
        resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "Note text"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400
        assert "text" in resp.json()["detail"].lower()

    async def test_multiple_notes_per_day(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        token = user_a["token"]
        mid = metric["id"]

        resp1 = await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-03-10", "text": "First note"},
            headers=auth_headers(token),
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/notes",
            json={"metric_id": mid, "date": "2026-03-10", "text": "Second note"},
            headers=auth_headers(token),
        )
        assert resp2.status_code == 201

        assert resp1.json()["id"] != resp2.json()["id"]


class TestUpdateNote:
    """PUT /api/notes/{id}"""

    async def test_update_note_text(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        token = user_a["token"]
        create_resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "Original"},
            headers=auth_headers(token),
        )
        note_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/notes/{note_id}",
            json={"text": "Updated text"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated text"
        assert resp.json()["id"] == note_id

    async def test_update_note_empty_text(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        token = user_a["token"]
        create_resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "Original"},
            headers=auth_headers(token),
        )
        note_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/notes/{note_id}",
            json={"text": "  "},
            headers=auth_headers(token),
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    async def test_update_nonexistent_note(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.put(
            "/api/notes/999999",
            json={"text": "New text"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


class TestDeleteNote:
    """DELETE /api/notes/{id}"""

    async def test_delete_note(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        token = user_a["token"]
        create_resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-10", "text": "To delete"},
            headers=auth_headers(token),
        )
        note_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/notes/{note_id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 204

        # Verify it's gone
        list_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric["id"], "start": "2026-03-01", "end": "2026-03-31"},
            headers=auth_headers(token),
        )
        assert all(n["id"] != note_id for n in list_resp.json())

    async def test_delete_nonexistent_note(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.delete(
            "/api/notes/999999",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 404


class TestListNotes:
    """GET /api/notes"""

    async def test_list_notes_by_date_range(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
        )
        token = user_a["token"]
        mid = metric["id"]

        # Create notes on different dates
        for day in ["2026-03-05", "2026-03-10", "2026-03-15", "2026-03-20"]:
            await client.post(
                "/api/notes",
                json={"metric_id": mid, "date": day, "text": f"Note for {day}"},
                headers=auth_headers(token),
            )

        # Query a sub-range
        resp = await client.get(
            "/api/notes",
            params={"metric_id": mid, "start": "2026-03-08", "end": "2026-03-16"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        notes = resp.json()
        assert len(notes) == 2
        dates = {n["date"] for n in notes}
        assert dates == {"2026-03-10", "2026-03-15"}


class TestNotesDataIsolation:
    """Users cannot access each other's notes."""

    async def test_cannot_see_other_users_notes(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="Journal A", metric_type="text",
        )
        await client.post(
            "/api/notes",
            json={"metric_id": metric_a["id"], "date": "2026-03-10", "text": "Private"},
            headers=auth_headers(user_a["token"]),
        )

        # user_b tries to list user_a's metric notes
        resp = await client.get(
            "/api/notes",
            params={"metric_id": metric_a["id"], "start": "2026-03-01", "end": "2026-03-31"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    async def test_cannot_update_other_users_note(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="Journal A", metric_type="text",
        )
        create_resp = await client.post(
            "/api/notes",
            json={"metric_id": metric_a["id"], "date": "2026-03-10", "text": "Original"},
            headers=auth_headers(user_a["token"]),
        )
        note_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/notes/{note_id}",
            json={"text": "Hacked"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404

    async def test_cannot_delete_other_users_note(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric_a = await create_metric(
            client, user_a["token"], name="Journal A", metric_type="text",
        )
        create_resp = await client.post(
            "/api/notes",
            json={"metric_id": metric_a["id"], "date": "2026-03-10", "text": "My note"},
            headers=auth_headers(user_a["token"]),
        )
        note_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/notes/{note_id}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 404
