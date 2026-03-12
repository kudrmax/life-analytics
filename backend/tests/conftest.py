"""
Shared fixtures for conversion tests.

Creates a dedicated test database in the existing PostgreSQL instance
(life-analytics-db-1 container on localhost:5432).
"""
from __future__ import annotations

from typing import AsyncGenerator

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.database as db_module
from app.database import _init_db_schema

# Connection params for the existing PostgreSQL container
_PG_USER = "la_user"
_PG_PASSWORD = "la_password"
_PG_HOST = "localhost"
_PG_PORT = 5432
_PG_ADMIN_DB = "life_analytics"  # existing DB, used to CREATE the test DB
_PG_TEST_DB = "life_analytics_test"


# ---------------------------------------------------------------------------
# Database pool (session-scoped — one test DB per session)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    # Connect to admin DB to create/recreate the test database
    admin_conn = await asyncpg.connect(
        user=_PG_USER, password=_PG_PASSWORD,
        host=_PG_HOST, port=_PG_PORT, database=_PG_ADMIN_DB,
    )
    # Terminate any lingering connections to the test DB
    await admin_conn.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{_PG_TEST_DB}' AND pid <> pg_backend_pid()
    """)
    await admin_conn.execute(f"DROP DATABASE IF EXISTS {_PG_TEST_DB}")
    await admin_conn.execute(f"CREATE DATABASE {_PG_TEST_DB} OWNER {_PG_USER}")
    await admin_conn.close()

    # Create pool connected to the test DB
    pool = await asyncpg.create_pool(
        user=_PG_USER, password=_PG_PASSWORD,
        host=_PG_HOST, port=_PG_PORT, database=_PG_TEST_DB,
        min_size=1, max_size=4,
    )

    # Initialise schema (creates full current DDL) and mark all migrations
    # as applied — init_db_schema already produces the final schema, so
    # evolutionary migrations must not re-run on a clean DB.
    async with pool.acquire() as conn:
        await _init_db_schema(conn)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        from app.migrations import MIGRATIONS
        for version, description, _ in MIGRATIONS:
            await conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                version, description,
            )

    yield pool

    await pool.close()

    # Drop test database
    admin_conn = await asyncpg.connect(
        user=_PG_USER, password=_PG_PASSWORD,
        host=_PG_HOST, port=_PG_PORT, database=_PG_ADMIN_DB,
    )
    await admin_conn.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{_PG_TEST_DB}' AND pid <> pg_backend_pid()
    """)
    await admin_conn.execute(f"DROP DATABASE IF EXISTS {_PG_TEST_DB}")
    await admin_conn.close()


# ---------------------------------------------------------------------------
# FastAPI app with overridden DB dependency
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def app(db_pool: asyncpg.Pool):
    # Patch the module-level pool so get_db() yields from our test pool
    db_module.pool = db_pool

    from app.main import app as fastapi_app
    yield fastapi_app


# ---------------------------------------------------------------------------
# HTTP client (function-scoped — fresh per test)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Auto-cleanup after each test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def cleanup(db_pool: asyncpg.Pool):
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE users CASCADE")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register_user(client: AsyncClient, username: str) -> dict[str, str | int]:
    """Register a user, return {"token": ..., "user_id": ...}."""
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "testpassword123"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Decode user_id from token for convenience
    from app.auth import decode_token
    user_info = decode_token(data["access_token"])
    return {"token": data["access_token"], "user_id": user_info["id"]}


async def create_metric(
    client: AsyncClient,
    token: str,
    *,
    name: str,
    metric_type: str,
    slug: str | None = None,
    scale_min: int | None = None,
    scale_max: int | None = None,
    scale_step: int | None = None,
    slot_labels: list[str] | None = None,
) -> dict:
    """Create a metric via API, return full response dict."""
    payload: dict = {"name": name, "type": metric_type}
    if slug:
        payload["slug"] = slug
    if scale_min is not None:
        payload["scale_min"] = scale_min
    if scale_max is not None:
        payload["scale_max"] = scale_max
    if scale_step is not None:
        payload["scale_step"] = scale_step
    if slot_labels is not None:
        payload["slot_labels"] = slot_labels
    resp = await client.post("/api/metrics", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_entry(
    client: AsyncClient,
    token: str,
    metric_id: int,
    date: str,
    value: bool | int | str,
    slot_id: int | None = None,
) -> dict:
    """Create an entry via API, return full response dict."""
    payload: dict = {"metric_id": metric_id, "date": date, "value": value}
    if slot_id is not None:
        payload["slot_id"] = slot_id
    resp = await client.post("/api/entries", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def user_a(client: AsyncClient) -> dict[str, str | int]:
    return await register_user(client, "user_a")


@pytest_asyncio.fixture
async def user_b(client: AsyncClient) -> dict[str, str | int]:
    return await register_user(client, "user_b")


# ---------------------------------------------------------------------------
# Metric fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def bool_metric(client: AsyncClient, user_a: dict) -> dict:
    return await create_metric(client, user_a["token"], name="Bool Test", metric_type="bool")


@pytest_asyncio.fixture
async def scale_metric(client: AsyncClient, user_a: dict) -> dict:
    return await create_metric(
        client, user_a["token"],
        name="Scale Test", metric_type="scale",
        scale_min=1, scale_max=5, scale_step=1,
    )


@pytest_asyncio.fixture
async def bool_metric_with_entries(
    client: AsyncClient, user_a: dict, bool_metric: dict,
) -> dict:
    """Bool metric with 3×true + 2×false entries."""
    mid = bool_metric["id"]
    token = user_a["token"]
    for i, val in enumerate([True, True, True, False, False]):
        await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", val)
    return bool_metric


@pytest_asyncio.fixture
async def scale_metric_with_entries(
    client: AsyncClient, user_a: dict, scale_metric: dict,
) -> dict:
    """Scale metric with values 1,2,3,4,5."""
    mid = scale_metric["id"]
    token = user_a["token"]
    for i, val in enumerate([1, 2, 3, 4, 5]):
        await create_entry(client, token, mid, f"2026-01-{10 + i:02d}", val)
    return scale_metric
