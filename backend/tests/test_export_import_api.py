"""API integration tests for export/import endpoints (/api/export)."""
from __future__ import annotations

import csv
import json
import zipfile
from io import BytesIO, StringIO

from httpx import AsyncClient

from tests.conftest import auth_headers, register_user, create_metric, create_entry, create_checkpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_zip(metrics_csv: str, entries_csv: str) -> BytesIO:
    """Build an in-memory ZIP with metrics.csv and entries.csv."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.csv", metrics_csv)
        zf.writestr("entries.csv", entries_csv)
    buf.seek(0)
    return buf


def build_zip_with_notes(
    metrics_csv: str, entries_csv: str, notes_csv: str,
) -> BytesIO:
    """Build an in-memory ZIP with metrics.csv, entries.csv, and notes.csv."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.csv", metrics_csv)
        zf.writestr("entries.csv", entries_csv)
        zf.writestr("notes.csv", notes_csv)
    buf.seek(0)
    return buf


def parse_export_zip(content: bytes) -> dict[str, str]:
    """Parse exported ZIP bytes into {filename: text} dict."""
    buf = BytesIO(content)
    result: dict[str, str] = {}
    with zipfile.ZipFile(buf) as zf:
        for name in zf.namelist():
            result[name] = zf.read(name).decode("utf-8")
    return result


def parse_csv_rows(text: str) -> list[dict[str, str]]:
    """Parse CSV text into list of row dicts."""
    return list(csv.DictReader(StringIO(text)))


async def _create_enum_metric(
    client: AsyncClient, token: str, *, name: str = "Mood",
    options: list[str] | None = None,
) -> dict:
    payload: dict = {
        "name": name,
        "type": "enum",
        "enum_options": options or ["Good", "Bad", "Meh"],
    }
    resp = await client.post(
        "/api/metrics", json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_category(
    client: AsyncClient, token: str, name: str, parent_id: int | None = None,
) -> dict:
    payload: dict = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = await client.post(
        "/api/categories", json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestExportEmpty:

    async def test_export_empty_produces_zip_with_headers_only(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]

        files = parse_export_zip(resp.content)
        assert "metrics.csv" in files
        assert "entries.csv" in files

        metrics_rows = parse_csv_rows(files["metrics.csv"])
        entries_rows = parse_csv_rows(files["entries.csv"])
        assert len(metrics_rows) == 0
        assert len(entries_rows) == 0


class TestExportWithData:

    async def test_export_bool_metric_and_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Sleep", metric_type="bool",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-03-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-03-02", False)

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        files = parse_export_zip(resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])
        entries_rows = parse_csv_rows(files["entries.csv"])

        assert len(metrics_rows) == 1
        assert metrics_rows[0]["name"] == "Sleep"
        assert metrics_rows[0]["type"] == "bool"

        assert len(entries_rows) == 2
        slugs = {r["metric_slug"] for r in entries_rows}
        assert slugs == {metric["slug"]}

    async def test_export_scale_metric_has_config(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"], name="Energy", metric_type="scale",
            scale_min=1, scale_max=10, scale_step=2,
        )

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        assert len(metrics_rows) == 1
        row = metrics_rows[0]
        assert row["scale_min"] == "1"
        assert row["scale_max"] == "10"
        assert row["scale_step"] == "2"

    async def test_export_enum_metric_has_options(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await _create_enum_metric(
            client, user_a["token"], name="Mood", options=["Happy", "Sad"],
        )

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        assert len(metrics_rows) == 1
        opts = json.loads(metrics_rows[0]["enum_options"])
        assert opts == ["Happy", "Sad"]

    async def test_export_zip_structure(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"], name="X", metric_type="bool",
        )
        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        buf = BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert "metrics.csv" in names
        assert "entries.csv" in names


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------

class TestImportBasic:

    async def test_import_valid_zip_creates_metrics_and_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metrics_csv = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value\n"
            "1,imp_bool,Imported Bool,,,,bool,1,0,,,,,,,,,,,,,,0,,,\n"
        )
        entries_csv = (
            "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
            "2026-03-01,imp_bool,true,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metrics"]["imported"] == 1
        assert body["entries"]["imported"] == 1

    async def test_import_creates_metric_by_slug(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metrics_csv = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value\n"
            "1,created_by_slug,Created By Slug,,,,bool,1,0,,,,,,,,,,,,,,0,,,\n"
        )
        entries_csv = "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )

        # Verify metric exists via metrics list
        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        slugs = [m["slug"] for m in resp.json()]
        assert "created_by_slug" in slugs

    async def test_import_skips_duplicate_entries(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        metrics_csv = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value\n"
            "1,dup_test,Dup Test,,,,bool,1,0,,,,,,,,,,,,,,0,,,\n"
        )
        entries_csv = (
            "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
            "2026-03-05,dup_test,true,,\n"
        )
        zip_buf_1 = build_zip(metrics_csv, entries_csv)
        zip_buf_2 = build_zip(metrics_csv, entries_csv)

        resp1 = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf_1, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp1.status_code == 200
        assert resp1.json()["entries"]["imported"] == 1

        resp2 = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf_2, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp2.status_code == 200
        assert resp2.json()["entries"]["skipped"] >= 1
        assert resp2.json()["entries"]["imported"] == 0

    async def test_import_non_zip_returns_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.txt", BytesIO(b"not a zip"), "text/plain")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_import_zip_without_metrics_csv_returns_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("entries.csv", "date,metric_slug,value,checkpoint_id,checkpoint_label\n")
        buf.seek(0)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Round-trip tests (export -> import on different user)
# ---------------------------------------------------------------------------

class TestRoundTrip:

    async def test_export_user_a_import_user_b_same_metrics(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"], name="RT Bool", metric_type="bool", slug="rt_bool",
        )
        await create_metric(
            client, user_a["token"], name="RT Number", metric_type="number", slug="rt_num",
        )

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)

        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["metrics"]["imported"] == 2

        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        slugs_b = {m["slug"] for m in resp_b.json()}
        assert "rt_bool" in slugs_b
        assert "rt_num" in slugs_b

    async def test_round_trip_preserves_bool_values(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="RT Bool Val", metric_type="bool", slug="rt_bv",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-03-01", True)
        await create_entry(client, user_a["token"], metric["id"], "2026-03-02", False)

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["entries"]["imported"] == 2

        # Verify values via entries list
        resp_1 = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_b["token"]),
        )
        assert resp_1.status_code == 200
        entries_1 = resp_1.json()
        assert len(entries_1) == 1
        assert entries_1[0]["value"] is True

        resp_2 = await client.get(
            "/api/entries",
            params={"date": "2026-03-02"},
            headers=auth_headers(user_b["token"]),
        )
        entries_2 = resp_2.json()
        assert len(entries_2) == 1
        assert entries_2[0]["value"] is False

    async def test_round_trip_preserves_number_values(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="RT Num Val", metric_type="number", slug="rt_nv",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-03-01", 42)
        await create_entry(client, user_a["token"], metric["id"], "2026-03-02", 0)

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["entries"]["imported"] == 2

        resp = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_b["token"]),
        )
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["value"] == 42

    async def test_round_trip_preserves_scale_config(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"], name="RT Scale", metric_type="scale",
            slug="rt_sc", scale_min=0, scale_max=100, scale_step=10,
        )

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200

        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metric_b = next(m for m in resp_b.json() if m["slug"] == "rt_sc")
        assert metric_b["scale_min"] == 0
        assert metric_b["scale_max"] == 100
        assert metric_b["scale_step"] == 10

    async def test_round_trip_preserves_enum_options_and_values(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await _create_enum_metric(
            client, user_a["token"], name="RT Enum", options=["Alpha", "Beta", "Gamma"],
        )
        option_id = metric["enum_options"][0]["id"]  # "Alpha"
        await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", [option_id],
        )

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        # Verify enum_options in export CSV
        metrics_rows = parse_csv_rows(files["metrics.csv"])
        enum_row = next(r for r in metrics_rows if r["type"] == "enum")
        exported_opts = json.loads(enum_row["enum_options"])
        assert exported_opts == ["Alpha", "Beta", "Gamma"]

        # Verify entry value contains labels (not IDs)
        entries_rows = parse_csv_rows(files["entries.csv"])
        assert len(entries_rows) == 1
        entry_value = json.loads(entries_rows[0]["value"])
        assert entry_value == ["Alpha"]

        # Import on user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["entries"]["imported"] == 1

        # Verify enum options were created for user_b
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metric_b = next(m for m in resp_b.json() if m["type"] == "enum")
        labels_b = [o["label"] for o in metric_b["enum_options"]]
        assert labels_b == ["Alpha", "Beta", "Gamma"]


# ---------------------------------------------------------------------------
# Advanced export tests
# ---------------------------------------------------------------------------

class TestExportAdvanced:

    async def test_export_with_categories(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        parent = await _create_category(client, user_a["token"], "Health")
        child = await _create_category(
            client, user_a["token"], "Sleep", parent_id=parent["id"],
        )
        # Create metric in that category
        resp = await client.post(
            "/api/metrics",
            json={"name": "Sleep Hours", "type": "number", "category_id": child["id"]},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        assert len(metrics_rows) == 1
        assert metrics_rows[0]["category_path"] == "Health > Sleep"

    async def test_export_with_checkpoints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        cp_m = await create_checkpoint(client, user_a["token"], "Morning")
        cp_e = await create_checkpoint(client, user_a["token"], "Evening")
        metric = await create_metric(
            client, user_a["token"],
            name="Mood Checkpoints", metric_type="bool",
            checkpoint_configs=[{"checkpoint_id": cp_m["id"]}, {"checkpoint_id": cp_e["id"]}],
        )
        assert len(metric["checkpoints"]) == 2

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        assert len(metrics_rows) == 1
        checkpoint_labels = json.loads(metrics_rows[0]["checkpoint_labels"])
        assert checkpoint_labels == ["Morning", "Evening"]

    async def test_export_with_private_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        resp = await client.post(
            "/api/metrics",
            json={"name": "Secret", "type": "bool", "private": True},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        assert len(metrics_rows) == 1
        assert metrics_rows[0]["private"] == "1"


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

class TestExportImportIsolation:

    async def test_export_only_shows_own_data(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"], name="A Only", metric_type="bool",
        )
        await create_metric(
            client, user_b["token"], name="B Only", metric_type="bool",
        )

        export_a = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        export_b = await client.get(
            "/api/export/csv", headers=auth_headers(user_b["token"]),
        )

        files_a = parse_export_zip(export_a.content)
        files_b = parse_export_zip(export_b.content)

        metrics_a = parse_csv_rows(files_a["metrics.csv"])
        metrics_b = parse_csv_rows(files_b["metrics.csv"])

        names_a = {r["name"] for r in metrics_a}
        names_b = {r["name"] for r in metrics_b}

        assert "A Only" in names_a
        assert "B Only" not in names_a
        assert "B Only" in names_b
        assert "A Only" not in names_b

    async def test_import_creates_data_for_current_user_only(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metrics_csv = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value\n"
            "1,iso_metric,Isolation Metric,,,,bool,1,0,,,,,,,,,,,,,,0,,,\n"
        )
        entries_csv = (
            "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
            "2026-03-10,iso_metric,true,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        # user_a must NOT see the imported metric
        resp_a = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        slugs_a = [m["slug"] for m in resp_a.json()]
        assert "iso_metric" not in slugs_a

        # user_b must see the imported metric
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        slugs_b = [m["slug"] for m in resp_b.json()]
        assert "iso_metric" in slugs_b


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestExportImportErrors:

    async def test_import_without_auth_returns_401(
        self, client: AsyncClient,
    ) -> None:
        metrics_csv = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value\n"
        )
        entries_csv = "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Round-trip: computed metrics
# ---------------------------------------------------------------------------

class TestRoundTripComputed:

    async def test_computed_metric_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        # Create source number metric for user_a
        src = await create_metric(
            client, user_a["token"], name="Base Num", metric_type="number",
            slug="base_num",
        )
        await create_entry(client, user_a["token"], src["id"], "2026-03-01", 10)

        # Create computed metric that references the source (include slug per canonical format)
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Comp", "type": "computed", "slug": "comp_test",
                "formula": [
                    {"type": "metric", "id": src["id"], "slug": "base_num"},
                    {"type": "op", "value": "+"},
                    {"type": "number", "value": 1},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Export user_a
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)

        # Import into user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["metrics"]["imported"] == 2

        # Verify user_b has both metrics
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metrics_b = resp_b.json()
        slugs_b = {m["slug"] for m in metrics_b}
        assert "base_num" in slugs_b
        assert "comp_test" in slugs_b

        # Verify the computed metric has formula with resolved IDs
        comp_b = next(m for m in metrics_b if m["slug"] == "comp_test")
        assert comp_b["formula"] is not None
        assert len(comp_b["formula"]) == 3
        # The metric token should reference user_b's base_num ID (not user_a's)
        metric_token = comp_b["formula"][0]
        assert metric_token["type"] == "metric"
        base_b = next(m for m in metrics_b if m["slug"] == "base_num")
        assert metric_token["id"] == base_b["id"]
        assert comp_b["result_type"] == "float"


# ---------------------------------------------------------------------------
# Round-trip: conditions
# ---------------------------------------------------------------------------

class TestRoundTripConditions:

    async def test_condition_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        # Create dependency bool metric
        dep = await create_metric(
            client, user_a["token"], name="Dep Cond", metric_type="bool",
            slug="dep_cond",
        )

        # Create metric with condition
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "With Cond", "type": "number", "slug": "with_cond",
                "condition_metric_id": dep["id"],
                "condition_type": "equals",
                "condition_value": True,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Export user_a
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)

        # Import into user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["metrics"]["imported"] == 2

        # Verify user_b's metric has condition pointing to correct dependency
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metrics_b = resp_b.json()
        cond_b = next(m for m in metrics_b if m["slug"] == "with_cond")
        dep_b = next(m for m in metrics_b if m["slug"] == "dep_cond")

        assert cond_b["condition_metric_id"] == dep_b["id"]
        assert cond_b["condition_type"] == "equals"
        assert cond_b["condition_value"] is True


# ---------------------------------------------------------------------------
# Round-trip: text metrics with notes
# ---------------------------------------------------------------------------

class TestRoundTripTextNotes:

    async def test_text_notes_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        # Create text metric
        metric = await create_metric(
            client, user_a["token"], name="Journal", metric_type="text",
            slug="journal_test",
        )

        # Create 3 notes on 2 different dates
        for text, date in [
            ("Morning thought", "2026-01-10"),
            ("Evening reflection", "2026-01-10"),
            ("Next day entry", "2026-01-11"),
        ]:
            resp = await client.post(
                "/api/notes",
                json={"metric_id": metric["id"], "date": date, "text": text},
                headers=auth_headers(user_a["token"]),
            )
            assert resp.status_code == 201

        # Export user_a
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)

        # Verify notes.csv is in the ZIP
        assert "notes.csv" in files
        notes_rows = parse_csv_rows(files["notes.csv"])
        assert len(notes_rows) == 3
        texts = {r["text"] for r in notes_rows}
        assert texts == {"Morning thought", "Evening reflection", "Next day entry"}

        # Import into user_b using ZIP with notes
        zip_buf = build_zip_with_notes(
            files["metrics.csv"], files["entries.csv"], files["notes.csv"],
        )
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["metrics"]["imported"] == 1

        # Verify notes exist for user_b by fetching notes via API
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metric_b = next(m for m in resp_b.json() if m["slug"] == "journal_test")
        notes_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric_b["id"], "start": "2026-01-01", "end": "2026-12-31"},
            headers=auth_headers(user_b["token"]),
        )
        assert notes_resp.status_code == 200
        notes_b = notes_resp.json()
        assert len(notes_b) == 3
        texts_b = {n["text"] for n in notes_b}
        assert texts_b == {"Morning thought", "Evening reflection", "Next day entry"}


# ---------------------------------------------------------------------------
# Round-trip: checkpoints with categories
# ---------------------------------------------------------------------------

class TestRoundTripCheckpointsWithCategories:

    async def test_checkpoints_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        # Create global checkpoints, then metric with checkpoint_configs (no category_id)
        cp_m = await create_checkpoint(client, user_a["token"], "Morning")
        cp_e = await create_checkpoint(client, user_a["token"], "Evening")
        metric = await create_metric(
            client, user_a["token"], name="Mood Checkpointed", metric_type="bool",
            slug="mood_checkpointed",
            checkpoint_configs=[
                {"checkpoint_id": cp_m["id"]},
                {"checkpoint_id": cp_e["id"]},
            ],
        )

        # Export user_a
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)

        # Verify checkpoint_labels in metrics.csv is simple format (list of strings)
        metrics_rows = parse_csv_rows(files["metrics.csv"])
        assert len(metrics_rows) == 1
        cp_data = json.loads(metrics_rows[0]["checkpoint_labels"])
        assert len(cp_data) == 2
        assert isinstance(cp_data[0], str)
        assert cp_data[0] == "Morning"
        assert cp_data[1] == "Evening"

        # Import into user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["metrics"]["imported"] == 1

        # Verify checkpoints recreated for user_b
        resp_b = await client.get(
            "/api/metrics", headers=auth_headers(user_b["token"]),
        )
        metric_b = next(m for m in resp_b.json() if m["slug"] == "mood_checkpointed")
        assert len(metric_b["checkpoints"]) == 2
        checkpoint_labels_b = [cp["label"] for cp in metric_b["checkpoints"]]
        assert checkpoint_labels_b == ["Morning", "Evening"]


# ---------------------------------------------------------------------------
# Round-trip: duration metrics
# ---------------------------------------------------------------------------

class TestRoundTripDuration:

    async def test_duration_values_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Exercise", metric_type="duration",
            slug="exercise_dur",
        )
        for date, val in [
            ("2026-03-01", 60), ("2026-03-02", 120), ("2026-03-03", 90),
        ]:
            await create_entry(client, user_a["token"], metric["id"], date, val)

        # Export
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        # Import into user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["entries"]["imported"] == 3

        # Verify values preserved
        for date, expected_val in [
            ("2026-03-01", 60), ("2026-03-02", 120), ("2026-03-03", 90),
        ]:
            resp = await client.get(
                "/api/entries",
                params={"date": date},
                headers=auth_headers(user_b["token"]),
            )
            entries = resp.json()
            assert len(entries) == 1
            assert entries[0]["value"] == expected_val


# ---------------------------------------------------------------------------
# Round-trip: time metrics
# ---------------------------------------------------------------------------

class TestRoundTripTime:

    async def test_time_values_round_trip(
        self, client: AsyncClient, user_a: dict, user_b: dict,
    ) -> None:
        metric = await create_metric(
            client, user_a["token"], name="Wake Up", metric_type="time",
            slug="wakeup_time",
        )
        await create_entry(client, user_a["token"], metric["id"], "2026-03-01", "07:30")
        await create_entry(client, user_a["token"], metric["id"], "2026-03-02", "08:00")

        # Export
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        # Import into user_b
        zip_buf = build_zip(files["metrics.csv"], files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_b["token"]),
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["entries"]["imported"] == 2

        # Verify values preserved
        resp_1 = await client.get(
            "/api/entries",
            params={"date": "2026-03-01"},
            headers=auth_headers(user_b["token"]),
        )
        entries_1 = resp_1.json()
        assert len(entries_1) == 1
        assert entries_1[0]["value"] == "07:30"

        resp_2 = await client.get(
            "/api/entries",
            params={"date": "2026-03-02"},
            headers=auth_headers(user_b["token"]),
        )
        entries_2 = resp_2.json()
        assert len(entries_2) == 1
        assert entries_2[0]["value"] == "08:00"


# ---------------------------------------------------------------------------
# Import updates existing metric
# ---------------------------------------------------------------------------

class TestImportUpdatesExistingMetric:

    async def test_import_updates_existing_metric_name(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create metric
        await create_metric(
            client, user_a["token"], name="Original", metric_type="bool",
            slug="upd_test",
        )

        # Export
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)

        # Modify the name in the CSV
        modified_csv = files["metrics.csv"].replace("Original", "Updated")

        # Import again (same user)
        zip_buf = build_zip(modified_csv, files["entries.csv"])
        import_resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert import_resp.status_code == 200
        body = import_resp.json()
        assert body["metrics"]["updated"] == 1
        assert body["metrics"]["imported"] == 0

        # Verify name was updated
        resp = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp.json() if m["slug"] == "upd_test")
        assert metric["name"] == "Updated"


# ---------------------------------------------------------------------------
# Export: computed formula is portable (no IDs)
# ---------------------------------------------------------------------------

class TestExportComputedFormulaPortable:

    async def test_exported_formula_has_no_id_field(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create source metric
        src = await create_metric(
            client, user_a["token"], name="Source Num", metric_type="number",
            slug="src_num_port",
        )

        # Create computed metric (include slug per canonical format)
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Computed Port", "type": "computed", "slug": "comp_port",
                "formula": [
                    {"type": "metric", "id": src["id"], "slug": "src_num_port"},
                    {"type": "op", "value": "*"},
                    {"type": "number", "value": 2},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Export
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        # Find the computed row
        comp_row = next(r for r in metrics_rows if r["slug"] == "comp_port")
        formula_tokens = json.loads(comp_row["formula"])

        # Verify no token has an "id" field (portable format)
        for token in formula_tokens:
            if isinstance(token, dict):
                assert "id" not in token, f"Token should not have 'id': {token}"

        # Verify the metric token has slug instead
        metric_token = next(t for t in formula_tokens if isinstance(t, dict) and t.get("type") == "metric")
        assert "slug" in metric_token
        assert metric_token["slug"] == "src_num_port"


# ---------------------------------------------------------------------------
# Export: conditions
# ---------------------------------------------------------------------------

class TestExportConditions:

    async def test_exported_condition_has_slug_and_type(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create dependency metric
        dep = await create_metric(
            client, user_a["token"], name="Dep A", metric_type="bool",
            slug="dep_a_exp",
        )

        # Create metric with condition
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Cond B", "type": "number", "slug": "cond_b_exp",
                "condition_metric_id": dep["id"],
                "condition_type": "equals",
                "condition_value": True,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Export
        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        # Find the conditional metric row
        cond_row = next(r for r in metrics_rows if r["slug"] == "cond_b_exp")
        assert cond_row["condition_metric_slug"] == "dep_a_exp"
        assert cond_row["condition_type"] == "equals"
        assert cond_row["condition_value"] == "true"


# ---------------------------------------------------------------------------
# Import: legacy format (category + fill_time columns)
# ---------------------------------------------------------------------------

class TestImportLegacyFormat:

    async def test_import_legacy_category_fill_time(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Build CSV with legacy columns (category + fill_time)
        header = (
            "id,slug,name,category_path,icon,type,enabled,sort_order,"
            "scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,"
            "provider,metric_key,value_type,filter_name,filter_query,"
            "enum_options,multi_select,private,condition_metric_slug,"
            "condition_type,condition_value,category,fill_time"
        )
        # Legacy: fill_time = parent category, category = child category
        # Path built by import: f"{fill_time} > {category}" = "Health > Sleep"
        # Columns: id,slug,name,category_path,icon,type,enabled,sort_order,
        #   scale_min,scale_max,scale_step,checkpoint_labels,formula,result_type,
        #   provider,metric_key,value_type,filter_name,filter_query,
        #   enum_options,multi_select,private,condition_metric_slug,
        #   condition_type,condition_value,category,fill_time
        row = (
            "1,legacy_metric,Legacy Metric,,,bool,1,0,"
            ",,,,,,,,,,,,,0,,,,Sleep,Health"
        )
        metrics_csv = f"{header}\n{row}\n"
        entries_csv = "date,metric_slug,value,checkpoint_id,checkpoint_label\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        # Verify categories were created from legacy format (fill_time > category)
        # API returns a tree: top-level categories with "children" arrays
        cats_resp = await client.get(
            "/api/categories", headers=auth_headers(user_a["token"]),
        )
        assert cats_resp.status_code == 200
        cats = cats_resp.json()

        # Collect all names (top-level + children)
        all_cats: list[dict] = []
        for c in cats:
            all_cats.append(c)
            for child in c.get("children", []):
                all_cats.append(child)
        cat_names = {c["name"] for c in all_cats}
        assert "Sleep" in cat_names
        assert "Health" in cat_names

        # Verify the metric has a category assigned
        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "legacy_metric")
        assert metric["category_id"] is not None

        # Verify the hierarchy: "Health" is parent, "Sleep" is child
        health_cat = next(c for c in all_cats if c["name"] == "Health")
        sleep_cat = next(c for c in all_cats if c["name"] == "Sleep")
        assert sleep_cat["parent_id"] is not None
        assert sleep_cat["parent_id"] == health_cat["id"]


# ---------------------------------------------------------------------------
# Helpers for new tests
# ---------------------------------------------------------------------------

METRICS_HEADER = (
    "id,slug,name,category_path,icon,type,enabled,sort_order,"
    "scale_min,scale_max,scale_step,scale_labels,checkpoint_labels,formula,result_type,"
    "provider,metric_key,value_type,filter_name,filter_query,"
    "enum_options,multi_select,private,condition_metric_slug,"
    "condition_type,condition_value,description,hide_in_cards,"
    "is_checkpoint,interval_binding"
)

ENTRIES_HEADER = "date,metric_slug,value,checkpoint_id,checkpoint_label"


def _metric_row(
    slug: str,
    name: str = "",
    *,
    metric_type: str = "bool",
    enabled: str = "1",
    sort_order: str = "0",
    scale_min: str = "",
    scale_max: str = "",
    scale_step: str = "",
    scale_labels: str = "",
    checkpoint_labels: str = "",
    formula: str = "",
    result_type: str = "",
    provider: str = "",
    metric_key: str = "",
    value_type: str = "",
    filter_name: str = "",
    filter_query: str = "",
    enum_options: str = "",
    multi_select: str = "",
    private: str = "0",
    condition_metric_slug: str = "",
    condition_type: str = "",
    condition_value: str = "",
    description: str = "",
    hide_in_cards: str = "0",
    is_checkpoint: str = "0",
    interval_binding: str = "all_day",
    metric_id: str = "1",
    category_path: str = "",
    icon: str = "",
) -> str:
    """Build a single metrics.csv data row with correct 30-field alignment."""
    if not name:
        name = slug
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([
        metric_id, slug, name, category_path, icon, metric_type, enabled,
        sort_order, scale_min, scale_max, scale_step, scale_labels,
        checkpoint_labels, formula, result_type, provider, metric_key, value_type,
        filter_name, filter_query, enum_options, multi_select, private,
        condition_metric_slug, condition_type, condition_value,
        description, hide_in_cards, is_checkpoint, interval_binding,
    ])
    return buf.getvalue().rstrip("\r\n")


def build_full_zip(
    metrics_csv: str,
    entries_csv: str,
    *,
    aw_daily_csv: str | None = None,
    aw_apps_csv: str | None = None,
    notes_csv: str | None = None,
) -> BytesIO:
    """Build an in-memory ZIP with arbitrary CSVs."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.csv", metrics_csv)
        zf.writestr("entries.csv", entries_csv)
        if aw_daily_csv is not None:
            zf.writestr("aw_daily.csv", aw_daily_csv)
        if aw_apps_csv is not None:
            zf.writestr("aw_apps.csv", aw_apps_csv)
        if notes_csv is not None:
            zf.writestr("notes.csv", notes_csv)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Export ActivityWatch data (lines 207-231)
# ---------------------------------------------------------------------------

class TestExportAWData:

    async def test_export_aw_daily(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """AW daily summary rows appear in aw_daily.csv when present."""
        uid = user_a["user_id"]
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO activitywatch_daily_summary
                   (user_id, date, total_seconds, active_seconds)
                   VALUES ($1, '2026-03-01', 36000, 28800)""",
                uid,
            )

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        files = parse_export_zip(resp.content)
        assert "aw_daily.csv" in files
        rows = parse_csv_rows(files["aw_daily.csv"])
        assert len(rows) == 1
        assert rows[0]["total_seconds"] == "36000"
        assert rows[0]["active_seconds"] == "28800"

    async def test_export_aw_apps(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """AW app usage rows appear in aw_apps.csv when present."""
        uid = user_a["user_id"]
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO activitywatch_app_usage
                   (user_id, date, app_name, source, duration_seconds)
                   VALUES ($1, '2026-03-01', 'Chrome', 'window', 7200)""",
                uid,
            )

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        files = parse_export_zip(resp.content)
        assert "aw_apps.csv" in files
        rows = parse_csv_rows(files["aw_apps.csv"])
        assert len(rows) == 1
        assert rows[0]["app_name"] == "Chrome"
        assert rows[0]["duration_seconds"] == "7200"

    async def test_export_no_aw_no_csv(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """User without AW data gets no aw_daily.csv or aw_apps.csv."""
        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        files = parse_export_zip(resp.content)
        assert "aw_daily.csv" not in files
        assert "aw_apps.csv" not in files


# ---------------------------------------------------------------------------
# Import ActivityWatch data (lines 724-746)
# ---------------------------------------------------------------------------

class TestImportAWData:

    async def test_import_aw_daily(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Import ZIP with aw_daily.csv creates DB rows."""
        metrics_csv = f"{METRICS_HEADER}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        aw_daily_csv = (
            "date,total_seconds,active_seconds\n"
            "2026-03-01,36000,28800\n"
            "2026-03-02,40000,32000\n"
        )
        zip_buf = build_full_zip(
            metrics_csv, entries_csv, aw_daily_csv=aw_daily_csv,
        )

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Verify DB rows
        uid = user_a["user_id"]
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT date, total_seconds, active_seconds FROM activitywatch_daily_summary WHERE user_id = $1 ORDER BY date",
                uid,
            )
        assert len(rows) == 2
        assert rows[0]["total_seconds"] == 36000
        assert rows[1]["active_seconds"] == 32000

    async def test_import_aw_apps(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Import ZIP with aw_apps.csv creates DB rows."""
        metrics_csv = f"{METRICS_HEADER}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        aw_apps_csv = (
            "date,app_name,source,duration_seconds\n"
            "2026-03-01,Firefox,window,5400\n"
        )
        zip_buf = build_full_zip(
            metrics_csv, entries_csv, aw_apps_csv=aw_apps_csv,
        )

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        uid = user_a["user_id"]
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT app_name, source, duration_seconds FROM activitywatch_app_usage WHERE user_id = $1",
                uid,
            )
        assert len(rows) == 1
        assert rows[0]["app_name"] == "Firefox"
        assert rows[0]["duration_seconds"] == 5400


# ---------------------------------------------------------------------------
# Export skips non-stored metric types (lines 188, 192)
# ---------------------------------------------------------------------------

class TestExportSkipsNonStored:

    async def test_export_computed_entries_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Computed metrics are skipped in entries export even when source has entries."""
        src = await create_metric(
            client, user_a["token"], name="Src Num", metric_type="number",
            slug="src_num_skip",
        )
        # Create an entry for the source metric so the loop runs
        await create_entry(client, user_a["token"], src["id"], "2026-03-01", 10)

        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Comp Skip", "type": "computed", "slug": "comp_skip",
                "formula": [
                    {"type": "metric", "id": src["id"], "slug": "src_num_skip"},
                    {"type": "op", "value": "+"},
                    {"type": "number", "value": 1},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        entries_rows = parse_csv_rows(files["entries.csv"])

        # Only the source metric should have entries, not computed
        assert len(entries_rows) == 1
        assert entries_rows[0]["metric_slug"] == "src_num_skip"

    async def test_export_text_no_entries_but_notes(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Text metrics produce no entries rows but notes.csv is created."""
        metric = await create_metric(
            client, user_a["token"], name="Journal Skip", metric_type="text",
            slug="journal_skip",
        )
        # Create a note
        resp = await client.post(
            "/api/notes",
            json={"metric_id": metric["id"], "date": "2026-03-01", "text": "Test note"},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        export_resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        files = parse_export_zip(export_resp.content)
        entries_rows = parse_csv_rows(files["entries.csv"])
        assert len(entries_rows) == 0

        assert "notes.csv" in files
        notes_rows = parse_csv_rows(files["notes.csv"])
        assert len(notes_rows) == 1
        assert notes_rows[0]["text"] == "Test note"


# ---------------------------------------------------------------------------
# Import updates existing scale config (lines 411-426)
# ---------------------------------------------------------------------------

class TestImportExistingScaleConfig:

    async def test_import_updates_scale_config(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Importing existing scale metric with new config updates scale_config."""
        # Create scale metric (1-5-1)
        await create_metric(
            client, user_a["token"], name="Energy", metric_type="scale",
            slug="energy_sc", scale_min=1, scale_max=5, scale_step=1,
        )

        # Import same slug with different scale config (2-10-2)
        row = _metric_row(
            "energy_sc", "Energy", metric_type="scale",
            scale_min="2", scale_max="10", scale_step="2",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["updated"] == 1

        # Verify the config was updated
        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "energy_sc")
        assert metric["scale_min"] == 2
        assert metric["scale_max"] == 10
        assert metric["scale_step"] == 2


# ---------------------------------------------------------------------------
# Import updates existing enum config (lines 451-458)
# ---------------------------------------------------------------------------

class TestImportExistingEnumConfig:

    async def test_import_updates_enum_config(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Import existing enum metric replaces options via _import_enum_options."""
        await _create_enum_metric(
            client, user_a["token"], name="Mood Upd", options=["A", "B"],
        )
        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["name"] == "Mood Upd")
        slug = metric["slug"]

        # Import same slug with different options (X, Y, Z)
        row = _metric_row(
            slug, "Mood Upd", metric_type="enum",
            enum_options=json.dumps(["X", "Y", "Z"]),
            multi_select="0",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["updated"] == 1

        # Verify options replaced
        resp_m2 = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric2 = next(m for m in resp_m2.json() if m["slug"] == slug)
        labels = [o["label"] for o in metric2["enum_options"]]
        assert "X" in labels
        assert "Y" in labels
        assert "Z" in labels


# ---------------------------------------------------------------------------
# Import new enum creates options (lines 497-506)
# ---------------------------------------------------------------------------

class TestImportNewEnum:

    async def test_import_new_enum_creates_options(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Importing a fresh enum metric creates enum_config + enum_options."""
        row = _metric_row(
            "mood_new", "Mood New", metric_type="enum",
            enum_options=json.dumps(["Happy", "Sad", "Ok"]),
            multi_select="1",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "mood_new")
        assert metric["type"] == "enum"
        assert metric["multi_select"] is True
        labels = [o["label"] for o in metric["enum_options"]]
        assert labels == ["Happy", "Sad", "Ok"]


# ---------------------------------------------------------------------------
# Import new metric with checkpoints (lines 508-513)
# ---------------------------------------------------------------------------

class TestImportNewCheckpoints:

    async def test_import_new_metric_with_checkpoints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Importing a new metric with checkpoint_labels >= 2 creates checkpoints."""
        row = _metric_row(
            "checkpointed_bool", "Checkpointed Bool",
            checkpoint_labels=json.dumps(["Morning", "Evening"]),
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "checkpointed_bool")
        assert len(metric["checkpoints"]) == 2
        checkpoint_labels = [cp["label"] for cp in metric["checkpoints"]]
        assert checkpoint_labels == ["Morning", "Evening"]


# ---------------------------------------------------------------------------
# Import enum options helper (lines 792-812)
# ---------------------------------------------------------------------------

class TestImportEnumOptionsHelper:

    async def test_reimport_enum_options_updates_and_disables(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Existing enum (A,B,C) re-imported with (A_new,B_new) updates first 2, disables third."""
        metric = await _create_enum_metric(
            client, user_a["token"], name="EHelper", options=["A", "B", "C"],
        )
        slug = metric["slug"]

        # Import with only 2 options
        row = _metric_row(
            slug, "EHelper", metric_type="enum",
            enum_options=json.dumps(["A_new", "B_new"]),
            multi_select="0",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Check DB directly: first 2 updated, third disabled
        async with db_pool.acquire() as conn:
            opts = await conn.fetch(
                "SELECT label, sort_order, enabled FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
                metric["id"],
            )
        assert len(opts) == 3
        assert opts[0]["label"] == "A_new"
        assert opts[0]["enabled"] is True
        assert opts[1]["label"] == "B_new"
        assert opts[1]["enabled"] is True
        assert opts[2]["label"] == "C"  # untouched label
        assert opts[2]["enabled"] is False


# ---------------------------------------------------------------------------
# Import checkpoints helper (lines 818-852)
# ---------------------------------------------------------------------------

class TestImportCheckpointsHelper:

    async def test_reimport_checkpoints_updates_and_disables(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Existing checkpoints (A,B,C) re-imported with (X,Y) updates first 2, disables third."""
        cp_a = await create_checkpoint(client, user_a["token"], "A")
        cp_b = await create_checkpoint(client, user_a["token"], "B")
        cp_c = await create_checkpoint(client, user_a["token"], "C")
        metric = await create_metric(
            client, user_a["token"], name="Checkpoint H", metric_type="bool",
            slug="checkpoint_h",
            checkpoint_configs=[{"checkpoint_id": cp_a["id"]}, {"checkpoint_id": cp_b["id"]}, {"checkpoint_id": cp_c["id"]}],
        )

        # Import with 2 checkpoints
        row = _metric_row(
            "checkpoint_h", "Checkpoint H",
            checkpoint_labels=json.dumps(["X", "Y"]),
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        async with db_pool.acquire() as conn:
            checkpoints = await conn.fetch(
                """SELECT c.label, mc.sort_order, mc.enabled
                   FROM metric_checkpoints mc
                   JOIN checkpoints c ON c.id = mc.checkpoint_id
                   WHERE mc.metric_id = $1 ORDER BY mc.sort_order""",
                metric["id"],
            )
        assert len(checkpoints) == 3
        assert checkpoints[0]["label"] == "X"
        assert checkpoints[0]["enabled"] is True
        assert checkpoints[1]["label"] == "Y"
        assert checkpoints[1]["enabled"] is True
        assert checkpoints[2]["label"] == "C"  # untouched
        assert checkpoints[2]["enabled"] is False

    async def test_reimport_checkpoints_with_cat_clears_metric_cat(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Importing checkpoints with category_path sets metric.category_id = NULL (line 848)."""
        # Create a category, global checkpoints, and metric with that category
        cat = await _create_category(client, user_a["token"], "SomeCat")
        cp_s1 = await create_checkpoint(client, user_a["token"], "S1")
        cp_s2 = await create_checkpoint(client, user_a["token"], "S2")
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "CatCheckpoint", "type": "bool", "slug": "cat_checkpoint",
                "category_id": cat["id"],
                "checkpoint_configs": [{"checkpoint_id": cp_s1["id"]}, {"checkpoint_id": cp_s2["id"]}],
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201
        metric = resp.json()

        # Import with checkpoints that have category_path
        checkpoint_labels_val = json.dumps([
            {"label": "S1", "category_path": "CheckpointCat"},
            {"label": "S2", "category_path": "CheckpointCat"},
        ])
        row = _metric_row(
            "cat_checkpoint", "CatCheckpoint",
            checkpoint_labels=checkpoint_labels_val,
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # Verify metric.category_id is NULL now
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT category_id FROM metric_definitions WHERE id = $1",
                metric["id"],
            )
        assert row["category_id"] is None


# ---------------------------------------------------------------------------
# Import entry value types (lines 672-708)
# ---------------------------------------------------------------------------

class TestImportEntryTypes:

    async def test_import_enum_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum entry value=["Good"] resolves label to option ID."""
        metric = await _create_enum_metric(
            client, user_a["token"], name="Mood Entry", options=["Good", "Bad"],
        )
        slug = metric["slug"]

        row = _metric_row(
            slug, "Mood Entry", metric_type="enum",
            enum_options=json.dumps(["Good", "Bad"]),
            multi_select="0",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            f'2026-03-01,{slug},"[""Good""]",,\n'
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1

    async def test_import_enum_invalid_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum entry with non-list value is skipped."""
        metric = await _create_enum_metric(
            client, user_a["token"], name="Mood Inv", options=["Good", "Bad"],
        )
        slug = metric["slug"]

        row = _metric_row(
            slug, "Mood Inv", metric_type="enum",
            enum_options=json.dumps(["Good", "Bad"]),
            multi_select="0",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            f'2026-03-01,{slug},"not_a_list",,\n'
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        # The entry should be skipped because value is a string, not a list
        assert resp.json()["entries"]["skipped"] >= 1

    async def test_import_time_non_string_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Time entry with non-string value (e.g. 123) is skipped."""
        await create_metric(
            client, user_a["token"], name="Wake Inv", metric_type="time",
            slug="wake_inv",
        )

        row = _metric_row("wake_inv", "Wake Inv", metric_type="time")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,wake_inv,123,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["skipped"] >= 1

    async def test_import_number_coercion(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Number entry with value=42 is imported successfully."""
        await create_metric(
            client, user_a["token"], name="Steps Num", metric_type="number",
            slug="steps_num",
        )

        row = _metric_row("steps_num", "Steps Num", metric_type="number")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,steps_num,42,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1

    async def test_import_scale_invalid_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Scale entry with non-numeric value is skipped."""
        await create_metric(
            client, user_a["token"], name="Scale Inv", metric_type="scale",
            slug="scale_inv", scale_min=1, scale_max=5, scale_step=1,
        )

        row = _metric_row(
            "scale_inv", "Scale Inv", metric_type="scale",
            scale_min="1", scale_max="5", scale_step="1",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            '2026-03-01,scale_inv,"abc",,\n'
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["skipped"] >= 1

    async def test_import_bool_dict_format(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Bool entry with dict format {"value": true} is imported."""
        await create_metric(
            client, user_a["token"], name="Bool Dict", metric_type="bool",
            slug="bool_dict",
        )

        row = _metric_row("bool_dict", "Bool Dict")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            '2026-03-01,bool_dict,"{""value"": true}",,\n'
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1


# ---------------------------------------------------------------------------
# Import errors (lines 284, 516-517, 771-776)
# ---------------------------------------------------------------------------

class TestImportErrors:

    async def test_import_no_entries_csv_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """ZIP with only metrics.csv (no entries.csv) returns 400."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("metrics.csv", f"{METRICS_HEADER}\n")
        buf.seek(0)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_import_bad_zip_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Non-ZIP bytes with .zip extension returns 400."""
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", BytesIO(b"this is not a zip"), "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_import_missing_slug_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Row with empty slug produces 'Missing slug' in metrics_errors."""
        row = _metric_row("", "No Slug")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metrics"]["imported"] == 0
        assert any("Missing slug" in e for e in body["metrics"]["errors"])


# ---------------------------------------------------------------------------
# Import legacy checkpoint_labels as plain strings (lines 384, 391-392)
# ---------------------------------------------------------------------------

class TestImportLegacyCheckpoints:

    async def test_import_legacy_checkpoint_labels_strings(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """checkpoint_labels as plain string list ["Morning","Evening"] creates checkpoints."""
        row = _metric_row(
            "legacy_checkpoints", "Legacy Checkpoints",
            checkpoint_labels=json.dumps(["Morning", "Evening"]),
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "legacy_checkpoints")
        assert len(metric["checkpoints"]) == 2
        labels = [cp["label"] for cp in metric["checkpoints"]]
        assert labels == ["Morning", "Evening"]


# ---------------------------------------------------------------------------
# Import notes (lines 748-769)
# ---------------------------------------------------------------------------

class TestImportNotes:

    async def test_import_notes_creates_notes(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Import ZIP with notes.csv creates note records."""
        row = _metric_row("txt_notes", "Text Notes", metric_type="text")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        notes_csv = (
            "date,metric_slug,text,created_at\n"
            "2026-03-01,txt_notes,Hello world,2026-03-01 12:00:00\n"
        )
        zip_buf = build_full_zip(
            metrics_csv, entries_csv, notes_csv=notes_csv,
        )

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "txt_notes")
        notes_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric["id"], "start": "2026-01-01", "end": "2026-12-31"},
            headers=auth_headers(user_a["token"]),
        )
        assert notes_resp.status_code == 200
        notes = notes_resp.json()
        assert len(notes) == 1
        assert notes[0]["text"] == "Hello world"

    async def test_import_notes_dedup(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Importing same note twice does not create duplicates."""
        row = _metric_row("txt_dup", "Text Dup", metric_type="text")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        notes_csv = (
            "date,metric_slug,text,created_at\n"
            "2026-03-01,txt_dup,Same note,2026-03-01 12:00:00\n"
        )
        zip_buf_1 = build_full_zip(
            metrics_csv, entries_csv, notes_csv=notes_csv,
        )
        zip_buf_2 = build_full_zip(
            metrics_csv, entries_csv, notes_csv=notes_csv,
        )

        await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf_1, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf_2, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "txt_dup")
        notes_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric["id"], "start": "2026-01-01", "end": "2026-12-31"},
            headers=auth_headers(user_a["token"]),
        )
        assert notes_resp.status_code == 200
        assert len(notes_resp.json()) == 1  # no duplicates

    async def test_import_notes_empty_text_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Notes with empty text are skipped."""
        row = _metric_row("txt_empty", "Text Empty", metric_type="text")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        notes_csv = (
            "date,metric_slug,text,created_at\n"
            "2026-03-01,txt_empty,,2026-03-01 12:00:00\n"
        )
        zip_buf = build_full_zip(
            metrics_csv, entries_csv, notes_csv=notes_csv,
        )

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "txt_empty")
        notes_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric["id"], "start": "2026-01-01", "end": "2026-12-31"},
            headers=auth_headers(user_a["token"]),
        )
        assert notes_resp.status_code == 200
        assert len(notes_resp.json()) == 0


    async def test_import_notes_unknown_slug_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Notes referencing unknown metric slug are skipped."""
        row = _metric_row("txt_known", "Text Known", metric_type="text")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        notes_csv = (
            "date,metric_slug,text,created_at\n"
            "2026-03-01,nonexistent_txt_slug,Should skip,2026-03-01 12:00:00\n"
        )
        zip_buf = build_full_zip(
            metrics_csv, entries_csv, notes_csv=notes_csv,
        )

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        # No notes should be created (slug doesn't match any metric)
        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "txt_known")
        notes_resp = await client.get(
            "/api/notes",
            params={"metric_id": metric["id"], "start": "2026-01-01", "end": "2026-12-31"},
            headers=auth_headers(user_a["token"]),
        )
        assert len(notes_resp.json()) == 0


# ---------------------------------------------------------------------------
# Import computed and text entries are skipped (lines 625-627)
# ---------------------------------------------------------------------------

class TestImportComputedTextEntriesSkipped:

    async def test_import_computed_entry_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Entries for computed metrics are skipped on import."""
        # Create a source metric and computed metric
        src = await create_metric(
            client, user_a["token"], name="SrcComp", metric_type="number",
            slug="src_comp_e",
        )
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "CompE", "type": "computed", "slug": "comp_e",
                "formula": [
                    {"type": "metric", "id": src["id"], "slug": "src_comp_e"},
                ],
                "result_type": "float",
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Try to import an entry for the computed metric
        row1 = _metric_row("src_comp_e", "SrcComp", metric_type="number")
        row2 = _metric_row("comp_e", "CompE", metric_type="computed", metric_id="2")
        metrics_csv = f"{METRICS_HEADER}\n{row1}\n{row2}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,comp_e,42,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["skipped"] >= 1
        assert resp.json()["entries"]["imported"] == 0


# ---------------------------------------------------------------------------
# Import with unknown metric slug in entries (line 623-624)
# ---------------------------------------------------------------------------

class TestImportUnknownSlugEntry:

    async def test_import_unknown_slug_entry_skipped(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Entry for non-existent metric slug is skipped."""
        metrics_csv = f"{METRICS_HEADER}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,nonexistent_slug,true,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["skipped"] >= 1
        assert resp.json()["entries"]["imported"] == 0


# ---------------------------------------------------------------------------
# Import with checkpoint entry that creates checkpoint on the fly (lines 636-651)
# ---------------------------------------------------------------------------

class TestImportCheckpointOnTheFly:

    async def test_import_creates_checkpoint_on_the_fly(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Entry with slot_sort_order (legacy) not in existing checkpoints creates a deleted checkpoint.

        The entry is saved with checkpoint_id, but the metric config stays clean
        (deleted checkpoint, no metric_checkpoint junction — no phantom checkpoints).
        """
        await create_metric(
            client, user_a["token"], name="No Checkpoint", metric_type="bool",
            slug="no_checkpoint",
        )

        row = _metric_row("no_checkpoint", "No Checkpoint")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        # Use legacy slot_sort_order/slot_label columns to test backward-compat path
        entries_csv = (
            "date,metric_slug,value,slot_sort_order,slot_label\n"
            "2026-03-01,no_checkpoint,true,0,Morning\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1

        # Entry saved with checkpoint_id — verify via entries API
        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "no_checkpoint")
        resp_e = await client.get(
            f"/api/entries?date=2026-03-01&metric_id={metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        entries = resp_e.json()
        assert len(entries) == 1
        assert entries[0]["checkpoint_id"] is not None


# ---------------------------------------------------------------------------
# Import with non-zip filename extension (line 266-267)
# ---------------------------------------------------------------------------

class TestImportNonZipFilename:

    async def test_import_non_zip_filename_returns_400(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """File that doesn't end with .zip returns 400."""
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.csv", BytesIO(b"fake"), "text/csv")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400
        assert "ZIP" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Import invalid metric type falls back to bool (line 355-356)
# ---------------------------------------------------------------------------

class TestImportInvalidMetricType:

    async def test_import_invalid_type_falls_back_to_bool(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Unknown metric type in CSV falls back to 'bool'."""
        row = _metric_row("bad_type", "Bad Type", metric_type="unknown_type")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "bad_type")
        assert metric["type"] == "bool"


# ---------------------------------------------------------------------------
# Import new scale metric without explicit config (line 473-479)
# ---------------------------------------------------------------------------

class TestImportNewScaleDefaults:

    async def test_import_new_scale_metric_defaults(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """New scale metric without explicit min/max/step gets defaults (1/5/1)."""
        row = _metric_row("scale_def", "Scale Default", metric_type="scale")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "scale_def")
        assert metric["scale_min"] == 1
        assert metric["scale_max"] == 5
        assert metric["scale_step"] == 1


# ---------------------------------------------------------------------------
# Import integration metric (lines 428-449, 481-495)
# ---------------------------------------------------------------------------

class TestImportIntegrationMetric:

    async def test_import_new_integration_metric(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """New integration metric with provider/metric_key is created."""
        row = _metric_row(
            "integ_test", "Integration Test", metric_type="integration",
            provider="todoist", metric_key="completed_tasks_count",
            value_type="number",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["metrics"]["imported"] == 1

    async def test_import_integration_filter_tasks(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Integration metric with filter_tasks_count creates filter config."""
        row = _metric_row(
            "integ_filter", "Filter Test", metric_type="integration",
            provider="todoist", metric_key="filter_tasks_count",
            value_type="number", filter_name="MyFilter",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "integ_filter")
        async with db_pool.acquire() as conn:
            cfg_row = await conn.fetchrow(
                "SELECT filter_name FROM integration_filter_config WHERE metric_id = $1",
                metric["id"],
            )
        assert cfg_row is not None
        assert cfg_row["filter_name"] == "MyFilter"

    async def test_import_integration_query_tasks(
        self, client: AsyncClient, user_a: dict, db_pool,
    ) -> None:
        """Integration metric with query_tasks_count creates query config."""
        row = _metric_row(
            "integ_query", "Query Test", metric_type="integration",
            provider="todoist", metric_key="query_tasks_count",
            value_type="number", filter_query="my_query",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        resp_m = await client.get(
            "/api/metrics", headers=auth_headers(user_a["token"]),
        )
        metric = next(m for m in resp_m.json() if m["slug"] == "integ_query")
        async with db_pool.acquire() as conn:
            cfg_row = await conn.fetchrow(
                "SELECT filter_query FROM integration_query_config WHERE metric_id = $1",
                metric["id"],
            )
        assert cfg_row is not None
        assert cfg_row["filter_query"] == "my_query"


# ---------------------------------------------------------------------------
# Import duration entry (lines 692-697)
# ---------------------------------------------------------------------------

class TestImportDurationEntry:

    async def test_import_duration_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Duration entry with integer value is imported."""
        await create_metric(
            client, user_a["token"], name="Dur Imp", metric_type="duration",
            slug="dur_imp",
        )

        row = _metric_row("dur_imp", "Dur Imp", metric_type="duration")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,dur_imp,90,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1


# ---------------------------------------------------------------------------
# Import scale entry (lines 698-703)
# ---------------------------------------------------------------------------

class TestImportScaleEntry:

    async def test_import_scale_entry(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Scale entry with valid integer value is imported."""
        await create_metric(
            client, user_a["token"], name="Scale Imp", metric_type="scale",
            slug="scale_imp", scale_min=1, scale_max=5, scale_step=1,
        )

        row = _metric_row(
            "scale_imp", "Scale Imp", metric_type="scale",
            scale_min="1", scale_max="5", scale_step="1",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            "2026-03-01,scale_imp,3,,\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1


# ---------------------------------------------------------------------------
# Import enum with empty option_ids after resolution (line 683-685)
# ---------------------------------------------------------------------------

class TestImportEnumEmptyResolution:

    async def test_import_enum_no_matching_labels_imports_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Enum entry whose labels don't match any options is imported as empty selection []."""
        metric = await _create_enum_metric(
            client, user_a["token"], name="Mood NoMatch", options=["X", "Y"],
        )
        slug = metric["slug"]

        row = _metric_row(
            slug, "Mood NoMatch", metric_type="enum",
            enum_options=json.dumps(["X", "Y"]),
            multi_select="0",
        )
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            f"{ENTRIES_HEADER}\n"
            f'2026-03-01,{slug},"[""NonExistent""]",,\n'
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] >= 1


# ---------------------------------------------------------------------------
# Export with checkpoint entries (covers checkpoint_id/checkpoint_label in entries.csv)
# ---------------------------------------------------------------------------

class TestExportCheckpointEntries:

    async def test_export_entries_with_checkpoints(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """Entries for checkpointed metric include checkpoint_id and checkpoint_label."""
        cp_m = await create_checkpoint(client, user_a["token"], "Morning")
        cp_e = await create_checkpoint(client, user_a["token"], "Evening")
        metric = await create_metric(
            client, user_a["token"], name="Checkpoint Entry", metric_type="bool",
            slug="checkpoint_entry",
            checkpoint_configs=[{"checkpoint_id": cp_m["id"]}, {"checkpoint_id": cp_e["id"]}],
        )
        # Create entries for each checkpoint
        checkpoints = metric["checkpoints"]
        await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", True,
            checkpoint_id=checkpoints[0]["id"],
        )
        await create_entry(
            client, user_a["token"], metric["id"], "2026-03-01", False,
            checkpoint_id=checkpoints[1]["id"],
        )

        resp = await client.get(
            "/api/export/csv", headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        files = parse_export_zip(resp.content)
        entries_rows = parse_csv_rows(files["entries.csv"])
        assert len(entries_rows) == 2

        # Check checkpoint info is present
        checkpoint_labels_export = {r["checkpoint_label"] for r in entries_rows}
        assert "Morning" in checkpoint_labels_export
        assert "Evening" in checkpoint_labels_export


# ---------------------------------------------------------------------------
# Import entries use enabled checkpoints, not disabled (sort_order collision fix)
# ---------------------------------------------------------------------------

class TestImportIgnoresDisabledCheckpoints:

    async def test_import_entry_uses_enabled_checkpoint_not_disabled(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        """When disabled and enabled checkpoints share sort_order, import must use the enabled one."""
        # Create 3 checkpoints
        cp_a = await create_checkpoint(client, user_a["token"], "Morning")
        cp_b = await create_checkpoint(client, user_a["token"], "Afternoon")
        cp_c = await create_checkpoint(client, user_a["token"], "Evening")

        # Create metric with all 3 checkpoints
        metric = await create_metric(
            client, user_a["token"],
            name="M", metric_type="bool",
            checkpoint_configs=[
                {"checkpoint_id": cp_a["id"]},
                {"checkpoint_id": cp_b["id"]},
                {"checkpoint_id": cp_c["id"]},
            ],
        )
        # Remove cp_b (sort_order=1) → disabled, then cp_c moves to sort_order=1
        await client.patch(
            f"/api/metrics/{metric['id']}",
            json={"checkpoint_configs": [
                {"checkpoint_id": cp_a["id"]},
                {"checkpoint_id": cp_c["id"]},
            ]},
            headers=auth_headers(user_a["token"]),
        )

        # Verify cp_c is now at sort_order=1
        resp_m = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        m = next(x for x in resp_m.json() if x["id"] == metric["id"])
        assert len(m["checkpoints"]) == 2
        assert m["checkpoints"][1]["id"] == cp_c["id"]

        # Import an entry at sort_order=1 — should go to cp_c (enabled), not cp_b (disabled)
        # Use legacy slot_sort_order column to test backward-compat path
        row = _metric_row(m["slug"], "M", checkpoint_labels=json.dumps(["Morning", "Evening"]))
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = (
            "date,metric_slug,value,slot_sort_order,slot_label\n"
            f"2026-03-01,{m['slug']},true,1,Evening\n"
        )
        zip_buf = build_zip(metrics_csv, entries_csv)

        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zip_buf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["entries"]["imported"] == 1

        # Verify entry is on cp_c (Evening), not cp_b (Afternoon)
        entries_resp = await client.get(
            f"/api/entries?date=2026-03-01&metric_id={metric['id']}",
            headers=auth_headers(user_a["token"]),
        )
        entries = entries_resp.json()
        assert len(entries) == 1
        assert entries[0]["checkpoint_id"] == cp_c["id"]


# ---------------------------------------------------------------------------
# Scale Labels round-trip
# ---------------------------------------------------------------------------


class TestExportImportScaleLabels:
    """Export/import preserves scale_labels."""

    async def test_scale_labels_round_trip(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        # Create scale metric with labels
        resp = await client.post(
            "/api/metrics",
            json={
                "name": "Labeled",
                "type": "scale",
                "scale_min": 0,
                "scale_max": 2,
                "scale_step": 1,
                "scale_labels": {"0": "нет", "1": "мало", "2": "достаточно"},
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 201

        # Export
        export_resp = await client.get(
            "/api/export/csv",
            headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        labeled = next(r for r in metrics_rows if r["name"] == "Labeled")
        assert labeled["scale_labels"] != ""
        import json
        parsed_labels = json.loads(labeled["scale_labels"])
        assert parsed_labels == {"0": "нет", "1": "мало", "2": "достаточно"}

    async def test_scale_without_labels_exports_empty(
        self, client: AsyncClient, user_a: dict,
    ) -> None:
        await create_metric(
            client, user_a["token"],
            name="NoLabel", metric_type="scale",
            scale_min=1, scale_max=5, scale_step=1,
        )

        export_resp = await client.get(
            "/api/export/csv",
            headers=auth_headers(user_a["token"]),
        )
        assert export_resp.status_code == 200
        files = parse_export_zip(export_resp.content)
        metrics_rows = parse_csv_rows(files["metrics.csv"])

        no_label = next(r for r in metrics_rows if r["name"] == "NoLabel")
        assert no_label["scale_labels"] == ""


# ---------------------------------------------------------------------------
# Interval binding import/export
# ---------------------------------------------------------------------------


class TestImportOldIntervalBindingFormat:
    async def test_import_old_daily_becomes_all_day(self, client, user_a):
        row = _metric_row("old_daily", "OldDaily", interval_binding="daily")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zf = build_zip(metrics_csv, entries_csv)
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        m = [m for m in metrics_resp.json() if m["slug"] == "old_daily"][0]
        assert m["interval_binding"] == "all_day"

    async def test_import_old_fixed_becomes_by_interval(self, client, user_a):
        row = _metric_row("old_fixed", "OldFixed", interval_binding="fixed")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zf = build_zip(metrics_csv, entries_csv)
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        m = [m for m in metrics_resp.json() if m["slug"] == "old_fixed"][0]
        assert m["interval_binding"] == "by_interval"

    async def test_import_old_floating_becomes_by_interval(self, client, user_a):
        row = _metric_row("old_float", "OldFloat", interval_binding="floating")
        metrics_csv = f"{METRICS_HEADER}\n{row}\n"
        entries_csv = f"{ENTRIES_HEADER}\n"
        zf = build_zip(metrics_csv, entries_csv)
        resp = await client.post(
            "/api/export/import",
            files={"file": ("data.zip", zf, "application/zip")},
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 200

        metrics_resp = await client.get("/api/metrics", headers=auth_headers(user_a["token"]))
        m = [m for m in metrics_resp.json() if m["slug"] == "old_float"][0]
        assert m["interval_binding"] == "by_interval"


class TestExportIntervalBinding:
    async def test_export_by_interval_metric(self, client, user_a):
        cp1 = await create_checkpoint(client, user_a["token"], "Утро")
        await create_checkpoint(client, user_a["token"], "День")

        await client.post(
            "/api/metrics",
            json={"name": "Душ", "type": "bool", "interval_binding": "by_interval",
                  "interval_ids": [cp1["id"]]},
            headers=auth_headers(user_a["token"]),
        )

        resp = await client.get("/api/export/csv", headers=auth_headers(user_a["token"]))
        assert resp.status_code == 200
        files = parse_export_zip(resp.content)
        rows = parse_csv_rows(files["metrics.csv"])
        shower = [r for r in rows if r["name"] == "Душ"][0]
        assert shower["interval_binding"] == "by_interval"
