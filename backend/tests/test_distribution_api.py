"""API tests for GET /api/analytics/metric-distribution."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import auth_headers, create_entry, create_metric, register_user


@pytest.mark.asyncio
class TestDistributionNumber:
    """Distribution endpoint with a number metric."""

    async def test_basic_response_structure(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="Steps", metric_type="number")
        today = date.today()
        for i in range(15):
            d = (today - timedelta(days=i)).isoformat()
            await create_entry(client, user_a["token"], metric["id"], d, 1000 + i * 100)

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric_id"] == metric["id"]
        assert data["metric_type"] == "number"
        assert data["n"] == 15
        assert len(data["bins"]) >= 5
        assert all("count" in b and "label" in b for b in data["bins"])
        assert sum(b["count"] for b in data["bins"]) == 15
        assert len(data["kde_x"]) == 50
        assert len(data["kde_y"]) == 50
        stats = data["stats"]
        assert "mean" in stats
        assert "median" in stats
        assert "variance" in stats
        assert "std_dev" in stats
        assert "skewness" in stats
        assert "kurtosis" in stats

    async def test_insufficient_data(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="Sparse", metric_type="number")
        today = date.today()
        await create_entry(client, user_a["token"], metric["id"], today.isoformat(), 42)

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["insufficient_data"] is True
        assert data["n"] == 1

    async def test_no_entries(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="Empty", metric_type="number")
        today = date.today()
        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["insufficient_data"] is True
        assert data["n"] == 0


@pytest.mark.asyncio
class TestDistributionNotApplicable:
    """Types that don't support distribution."""

    async def test_bool(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="BoolDist", metric_type="bool")
        today = date.today()
        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_applicable"] is True

    async def test_enum(self, client, user_a) -> None:
        metric = await create_metric(
            client, user_a["token"], name="EnumDist", metric_type="enum",
            enum_options=["A", "B", "C"],
        )
        today = date.today()
        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_applicable"] is True

    async def test_text(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="TextDist", metric_type="text")
        today = date.today()
        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_applicable"] is True


@pytest.mark.asyncio
class TestDistributionTypes:
    """Verify distribution works for different numeric types."""

    async def test_duration(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="DurDist", metric_type="duration")
        today = date.today()
        for i in range(10):
            d = (today - timedelta(days=i)).isoformat()
            await create_entry(client, user_a["token"], metric["id"], d, 30 + i * 10)

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n"] == 10
        assert data["metric_type"] == "duration"
        for b in data["bins"]:
            assert "ч" in b["label"] and "м" in b["label"]

    async def test_scale(self, client, user_a) -> None:
        metric = await create_metric(
            client, user_a["token"], name="ScaleDist", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )
        today = date.today()
        for i in range(10):
            d = (today - timedelta(days=i)).isoformat()
            await create_entry(client, user_a["token"], metric["id"], d, 1 + (i % 5))

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n"] == 10
        assert data["metric_type"] == "scale"
        for b in data["bins"]:
            assert "%" in b["label"]

    async def test_time(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="TimeDist", metric_type="time")
        today = date.today()
        for i in range(10):
            d = (today - timedelta(days=i)).isoformat()
            h = 7 + i
            await create_entry(client, user_a["token"], metric["id"], d, f"{h:02d}:{30}:00")

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["n"] == 10
        assert data["metric_type"] == "time"
        for b in data["bins"]:
            assert ":" in b["label"]


@pytest.mark.asyncio
class TestDistributionDataIsolation:
    """User B cannot see User A's metric distribution."""

    async def test_other_user_not_found(self, client, user_a, user_b) -> None:
        metric = await create_metric(client, user_a["token"], name="Private Steps", metric_type="number")
        today = date.today()
        for i in range(5):
            d = (today - timedelta(days=i)).isoformat()
            await create_entry(client, user_a["token"], metric["id"], d, 100 + i)

        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("error") == "Metric not found"


@pytest.mark.asyncio
class TestDistributionPrivacy:
    """Privacy mode blocks private metrics."""

    async def test_privacy_blocks(self, client, user_a) -> None:
        metric = await create_metric(client, user_a["token"], name="Secret", metric_type="number")
        # Mark metric as private
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"private": True},
            headers=auth_headers(user_a["token"]),
        )
        # Enable privacy mode
        await client.put(
            "/api/auth/privacy-mode",
            json={"enabled": True},
            headers=auth_headers(user_a["token"]),
        )
        today = date.today()
        resp = await client.get(
            f"/api/analytics/metric-distribution?metric_id={metric['id']}&start={(today - timedelta(days=30)).isoformat()}&end={today.isoformat()}",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("blocked") is True
