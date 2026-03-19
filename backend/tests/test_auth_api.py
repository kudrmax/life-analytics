"""API integration tests for the auth router."""

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user


class TestRegister:
    """POST /api/auth/register"""

    async def test_register_success(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "securepass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "newuser"
        assert data["token_type"] == "bearer"

    async def test_register_short_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "validuser", "password": "short"},
        )
        assert resp.status_code == 400
        assert "8 characters" in resp.json()["detail"]

    async def test_register_short_username(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "ab", "password": "securepass123"},
        )
        assert resp.status_code == 400
        assert "3-30" in resp.json()["detail"]

    async def test_register_long_username(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "a" * 31, "password": "securepass123"},
        )
        assert resp.status_code == 400
        assert "3-30" in resp.json()["detail"]

    async def test_register_duplicate_username(self, client: AsyncClient) -> None:
        await register_user(client, "duplicate")
        resp = await client.post(
            "/api/auth/register",
            json={"username": "duplicate", "password": "securepass123"},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


class TestLogin:
    """POST /api/auth/login"""

    async def test_login_success(self, client: AsyncClient) -> None:
        await register_user(client, "loginuser")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "loginuser", "password": "testpassword123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "loginuser"
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient) -> None:
        await register_user(client, "loginuser")
        resp = await client.post(
            "/api/auth/login",
            json={"username": "loginuser", "password": "wrongpassword"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "ghost", "password": "doesntmatter"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]


class TestMe:
    """GET /api/auth/me"""

    async def test_me_authenticated(self, client: AsyncClient, user_a: dict) -> None:
        resp = await client.get("/api/auth/me", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "user_a"
        assert data["id"] == user_a["user_id"]
        assert "created_at" in data

    async def test_me_no_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401


class TestPrivacyMode:
    """GET/PUT /api/auth/privacy-mode"""

    async def test_get_default_privacy_mode(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.get(
            "/api/auth/privacy-mode", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["privacy_mode"] is False

    async def test_put_enable_privacy_mode(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["privacy_mode"] is True

    async def test_get_after_enable(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get(
            "/api/auth/privacy-mode", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["privacy_mode"] is True

    async def test_put_disable_privacy_mode(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": False},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["privacy_mode"] is False


class TestDeleteAccount:
    """DELETE /api/auth/account"""

    async def test_delete_returns_204(self, client: AsyncClient) -> None:
        user = await register_user(client, "deleteme")
        resp = await client.delete(
            "/api/auth/account", headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 204

    async def test_user_gone_after_delete(self, client: AsyncClient) -> None:
        user = await register_user(client, "gonegone")
        await client.delete(
            "/api/auth/account", headers=auth_headers(user["token"]),
        )
        resp = await client.get(
            "/api/auth/me", headers=auth_headers(user["token"]),
        )
        assert resp.status_code == 404

    async def test_delete_no_auth(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/auth/account")
        assert resp.status_code == 401

    async def test_other_user_unaffected(self, client: AsyncClient) -> None:
        user_del = await register_user(client, "todelete")
        user_keep = await register_user(client, "tokeep")
        await client.delete(
            "/api/auth/account", headers=auth_headers(user_del["token"]),
        )
        resp = await client.get(
            "/api/auth/me", headers=auth_headers(user_keep["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "tokeep"


class TestHealth:
    """GET /api/health"""

    async def test_health_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "env" in data


class TestDataIsolation:
    """Users cannot see each other's data via /me."""

    async def test_me_returns_own_data(
        self,
        client: AsyncClient,
        user_a: dict,
        user_b: dict,
    ) -> None:
        resp_a = await client.get(
            "/api/auth/me", headers=auth_headers(user_a["token"]),
        )
        resp_b = await client.get(
            "/api/auth/me", headers=auth_headers(user_b["token"]),
        )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        data_a = resp_a.json()
        data_b = resp_b.json()

        assert data_a["username"] == "user_a"
        assert data_b["username"] == "user_b"
        assert data_a["id"] != data_b["id"]
