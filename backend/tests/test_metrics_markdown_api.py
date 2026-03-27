"""API tests for GET /api/metrics/export/markdown endpoint."""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_checkpoint


class TestMarkdownExportBasic:
    """Basic markdown table generation."""

    async def test_empty_metrics_returns_header_only(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2  # header + separator
        assert "Иконка" in lines[0]
        assert "Описание" in lines[0]

    async def test_bool_metric_row(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(client, user_a["token"], name="Зарядка", metric_type="bool")
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3
        row = lines[2]
        assert "Зарядка" in row
        assert "Да/Нет" in row

    async def test_number_metric_row(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(client, user_a["token"], name="Шаги", metric_type="number")
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        lines = resp.text.strip().split("\n")
        row = lines[2]
        assert "Шаги" in row
        assert "Число" in row


class TestMarkdownExportScale:
    """Scale metrics show config in details."""

    async def test_scale_details(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"],
            name="Настроение", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=1,
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        lines = resp.text.strip().split("\n")
        row = lines[2]
        assert "Шкала" in row
        assert "1–10" in row
        assert "шаг 1" in row


class TestMarkdownExportEnum:
    """Enum metrics show options in details."""

    async def test_enum_details(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"],
            name="Погода", metric_type="enum",
            enum_options=["Солнце", "Дождь", "Облачно"],
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        lines = resp.text.strip().split("\n")
        row = lines[2]
        assert "Варианты" in row
        assert "Солнце" in row
        assert "Дождь" in row
        assert "Облачно" in row

    async def test_enum_multiselect(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"],
            name="Еда", metric_type="enum",
            enum_options=["Завтрак", "Обед"],
            multi_select=True,
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = resp.text.strip().split("\n")[2]
        assert "(мультивыбор)" in row


class TestMarkdownExportDescription:
    """Description column populated / empty."""

    async def test_description_present(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create metric with description directly
        resp = await client.post(
            "/api/metrics",
            json={"name": "Тест", "type": "bool", "description": "Описание метрики"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        md_resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = md_resp.text.strip().split("\n")[2]
        assert "Описание метрики" in row

    async def test_description_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(client, user_a["token"], name="Без описания", metric_type="bool")
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        # Should not crash, row still generated
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3


class TestMarkdownExportCategories:
    """Categories and nested categories in the table."""

    async def test_top_level_category(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create category
        cat_resp = await client.post(
            "/api/categories",
            json={"name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        assert cat_resp.status_code == 201
        cat_id = cat_resp.json()["id"]

        # Create metric in that category
        m = await create_metric(client, user_a["token"], name="Зарядка", metric_type="bool")
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"category_id": cat_id},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = resp.text.strip().split("\n")[2]
        assert "Здоровье" in row

    async def test_nested_category(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create parent category
        parent_resp = await client.post(
            "/api/categories",
            json={"name": "Здоровье"},
            headers=auth_headers(user_a["token"]),
        )
        parent_id = parent_resp.json()["id"]

        # Create child category
        child_resp = await client.post(
            "/api/categories",
            json={"name": "Физ. активность", "parent_id": parent_id},
            headers=auth_headers(user_a["token"]),
        )
        child_id = child_resp.json()["id"]

        # Create metric in child category
        m = await create_metric(client, user_a["token"], name="Бег", metric_type="bool")
        await client.patch(
            f"/api/metrics/{m['id']}",
            json={"category_id": child_id},
            headers=auth_headers(user_a["token"]),
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = resp.text.strip().split("\n")[2]
        assert "Здоровье / Физ. активность" in row


class TestMarkdownExportCheckpoints:
    """Metrics with checkpoints show checkpoint labels."""

    async def test_metric_with_checkpoints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create global checkpoints
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        cp2 = await create_checkpoint(client, user_a["token"], "Вечер")

        # Create metric with checkpoints
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Давление",
                "type": "number",
                "checkpoint_configs": [
                    {"checkpoint_id": cp1["id"]},
                    {"checkpoint_id": cp2["id"]},
                ],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        md_resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = md_resp.text.strip().split("\n")[2]
        assert "Утро" in row
        assert "Вечер" in row


class TestMarkdownExportDisabledMetrics:
    """Disabled (archived) metrics appear after enabled ones."""

    async def test_archived_after_active(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        m1 = await create_metric(client, user_a["token"], name="Активная", metric_type="bool")
        m2 = await create_metric(client, user_a["token"], name="Архивная", metric_type="bool")
        # Disable second metric
        await client.patch(
            f"/api/metrics/{m2['id']}",
            json={"enabled": False},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        lines = resp.text.strip().split("\n")
        assert len(lines) == 4  # header + separator + 2 metrics
        # Enabled first
        assert "Активная" in lines[2]
        assert "❌ архив" not in lines[2]
        # Disabled second
        assert "Архивная" in lines[3]
        assert "❌ архив" in lines[3]


class TestMarkdownExportPipeEscape:
    """Pipe characters in names are escaped."""

    async def test_pipe_in_name_escaped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"],
            name="Да|Нет", metric_type="bool",
        )
        resp = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        row = resp.text.strip().split("\n")[2]
        assert "Да\\|Нет" in row


class TestMarkdownExportDataIsolation:
    """User B cannot see user A's metrics."""

    async def test_isolation(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await create_metric(client, user_a["token"], name="Секрет_A", metric_type="bool")
        await create_metric(client, user_b["token"], name="Секрет_B", metric_type="bool")

        resp_a = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_a["token"]),
        )
        resp_b = await client.get(
            "/api/metrics/export/markdown",
            headers=auth_headers(user_b["token"]),
        )

        assert "Секрет_A" in resp_a.text
        assert "Секрет_B" not in resp_a.text
        assert "Секрет_B" in resp_b.text
        assert "Секрет_A" not in resp_b.text

    async def test_unauthorized_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/metrics/export/markdown")
        assert resp.status_code in (401, 403)
