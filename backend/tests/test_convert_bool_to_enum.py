"""Tests for POST /api/metrics/{id}/convert — bool → enum."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth_headers,
    create_entry,
    create_metric,
    create_slot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_payload(
    *,
    options: list[str] | None = None,
    mapping: dict[str, str | None] | None = None,
    multi_select: bool = False,
) -> dict:
    payload: dict = {
        "target_type": "enum",
        "value_mapping": mapping or {},
        "enum_options": options,
        "multi_select": multi_select,
    }
    return payload


async def _do_convert(
    client: AsyncClient,
    token: str,
    metric_id: int,
    **kwargs,
) -> tuple[int, dict]:
    """POST convert and return (status_code, json_body)."""
    resp = await client.post(
        f"/api/metrics/{metric_id}/convert",
        json=_convert_payload(**kwargs),
        headers=auth_headers(token),
    )
    return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestBoolToEnumHappyPath:

    async def test_happy_path_2_options(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0

    async def test_happy_path_3_options(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Хорошо", "Плохо", "Средне"],
            mapping={"true": "Хорошо", "false": "Плохо"},
        )
        assert status == 200
        assert body["converted"] == 5

    async def test_delete_true_convert_false(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Нет", "Может"],
            mapping={"true": None, "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 2  # false entries
        assert body["deleted"] == 3   # true entries

    async def test_delete_false_convert_true(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Ура", "Доп"],
            mapping={"true": "Ура", "false": None},
        )
        assert status == 200
        assert body["converted"] == 3
        assert body["deleted"] == 2

    async def test_delete_all(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["A", "B"],
            mapping={"true": None, "false": None},
        )
        assert status == 200
        assert body["converted"] == 0
        assert body["deleted"] == 5

    async def test_empty_metric(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 0
        assert body["deleted"] == 0

    async def test_only_true_entries(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        await create_entry(client, token, mid, "2026-01-11", True)
        status, body = await _do_convert(
            client, token, mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 2

    async def test_only_false_entries(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        mid = bool_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", False)
        status, body = await _do_convert(
            client, token, mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 1

    async def test_both_mapped_to_same_option(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Всё", "Другое"],
            mapping={"true": "Всё", "false": "Всё"},
        )
        assert status == 200
        assert body["converted"] == 5
        assert body["deleted"] == 0


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestBoolToEnumValidation:

    @pytest.mark.parametrize("bad_options", [
        ["one"],       # too few
        [],            # empty
    ])
    async def test_fewer_than_2_options(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
        bad_options: list[str],
    ):
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=bad_options,
            mapping={"true": bad_options[0] if bad_options else None, "false": None},
        )
        assert status == 400

    async def test_none_options(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
            json={
                "target_type": "enum",
                "value_mapping": {"true": "A", "false": "B"},
                "enum_options": None,
            },
            headers=auth_headers(user_a["token"]),
        )
        assert resp.status_code == 400

    async def test_duplicate_labels(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        status, body = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["Да", "Да"],
            mapping={"true": "Да", "false": "Да"},
        )
        assert status == 400

    async def test_duplicate_labels_case_sensitive(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """'Да' and 'да' are different labels — should pass uniqueness check."""
        status, body = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["Да", "да"],
            mapping={"true": "Да", "false": "да"},
        )
        assert status == 200

    async def test_mapping_target_not_in_options(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["A", "B"],
            mapping={"true": "A", "false": "NONEXISTENT"},
        )
        assert status == 400

    async def test_incomplete_mapping_missing_true(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        """Has true entries but mapping lacks 'true' key."""
        mid = bool_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["A", "B"],
            mapping={"false": "A"},
        )
        assert status == 400

    async def test_incomplete_mapping_missing_false(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        """Has false entries but mapping lacks 'false' key."""
        mid = bool_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["A", "B"],
            mapping={"true": "A"},
        )
        assert status == 400

    async def test_extra_mapping_keys(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """Mapping has 'false' but DB has only true entries — should be OK."""
        mid = bool_metric["id"]
        token = user_a["token"]
        await create_entry(client, token, mid, "2026-01-10", True)
        status, body = await _do_convert(
            client, token, mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 1

    async def test_invalid_mapping_key(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["A", "B"],
            mapping={"yes": "A", "no": "B"},
        )
        assert status == 400


# ---------------------------------------------------------------------------
# Special characters in labels
# ---------------------------------------------------------------------------

class TestBoolToEnumSpecialLabels:

    async def test_special_chars_in_labels(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["✅ Да!", "❌ 'Нет'"],
            mapping={"true": "✅ Да!", "false": "❌ 'Нет'"},
        )
        assert status == 200
        assert body["converted"] == 5

    async def test_comma_in_label(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        mid = bool_metric_with_entries["id"]
        status, body = await _do_convert(
            client, user_a["token"], mid,
            options=["Да, но частично", "Нет, вообще"],
            mapping={"true": "Да, но частично", "false": "Нет, вообще"},
        )
        assert status == 200
        assert body["converted"] == 5

    async def test_long_label_200_chars(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        long_label = "A" * 200
        short_label = "B" * 200
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=[long_label, short_label],
            mapping={"true": long_label, "false": short_label},
        )
        assert status == 200


# ---------------------------------------------------------------------------
# Multi-select flag
# ---------------------------------------------------------------------------

class TestBoolToEnumMultiSelect:

    async def test_multi_select_true(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
            multi_select=True,
        )
        assert status == 200

    async def test_multi_select_false(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
            multi_select=False,
        )
        assert status == 200


# ---------------------------------------------------------------------------
# Auth / isolation
# ---------------------------------------------------------------------------

class TestBoolToEnumAuth:

    async def test_metric_not_found(
        self, client: AsyncClient, user_a: dict,
    ):
        status, _ = await _do_convert(
            client, user_a["token"], 999999,
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
        )
        assert status == 404

    async def test_other_user_metric(
        self, client: AsyncClient, user_a: dict, user_b: dict, bool_metric: dict,
    ):
        status, _ = await _do_convert(
            client, user_b["token"], bool_metric["id"],
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
        )
        assert status == 404

    async def test_not_bool_type(
        self, client: AsyncClient, user_a: dict, scale_metric: dict,
    ):
        """scale → enum is not allowed."""
        status, _ = await _do_convert(
            client, user_a["token"], scale_metric["id"],
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
        )
        assert status == 400

    async def test_no_auth(self, client: AsyncClient, bool_metric: dict):
        resp = await client.post(
            f"/api/metrics/{bool_metric['id']}/convert",
            json=_convert_payload(options=["A", "B"], mapping={"true": "A", "false": "B"}),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Database state verification
# ---------------------------------------------------------------------------

class TestBoolToEnumDBState:

    async def test_verify_db_state(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict, db_pool,
    ):
        mid = bool_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            # Metric type changed to enum
            row = await conn.fetchrow(
                "SELECT type FROM metric_definitions WHERE id = $1", mid,
            )
            assert row["type"] == "enum"

            # enum_config created
            ec = await conn.fetchrow(
                "SELECT multi_select FROM enum_config WHERE metric_id = $1", mid,
            )
            assert ec is not None
            assert ec["multi_select"] is False

            # enum_options created
            opts = await conn.fetch(
                "SELECT label, sort_order FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
                mid,
            )
            assert len(opts) == 2
            assert opts[0]["label"] == "Да"
            assert opts[1]["label"] == "Нет"

            # values_bool is empty for this metric
            bool_count = await conn.fetchval(
                """SELECT COUNT(*) FROM values_bool vb
                   JOIN entries e ON e.id = vb.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert bool_count == 0

            # values_enum is filled
            enum_count = await conn.fetchval(
                """SELECT COUNT(*) FROM values_enum ve
                   JOIN entries e ON e.id = ve.entry_id
                   WHERE e.metric_id = $1""",
                mid,
            )
            assert enum_count == 5

    async def test_verify_entries_preserved(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict, db_pool,
    ):
        mid = bool_metric_with_entries["id"]

        # Get entry IDs and dates before conversion
        async with db_pool.acquire() as conn:
            before = await conn.fetch(
                "SELECT id, date FROM entries WHERE metric_id = $1 ORDER BY id", mid,
            )
        before_ids = [r["id"] for r in before]
        before_dates = [r["date"] for r in before]

        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            after = await conn.fetch(
                "SELECT id, date FROM entries WHERE metric_id = $1 ORDER BY id", mid,
            )
        after_ids = [r["id"] for r in after]
        after_dates = [r["date"] for r in after]

        assert after_ids == before_ids
        assert after_dates == before_dates

    async def test_values_enum_correct_option_ids(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict, db_pool,
    ):
        mid = bool_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            opts = await conn.fetch(
                "SELECT id, label FROM enum_options WHERE metric_id = $1", mid,
            )
            opt_map = {r["label"]: r["id"] for r in opts}

            # True entries (3) should reference "Да" option
            true_entries = await conn.fetch(
                """SELECT ve.selected_option_ids FROM values_enum ve
                   JOIN entries e ON e.id = ve.entry_id
                   WHERE e.metric_id = $1 AND e.date IN ('2026-01-10', '2026-01-11', '2026-01-12')""",
                mid,
            )
            for row in true_entries:
                assert row["selected_option_ids"] == [opt_map["Да"]]

            # False entries (2) should reference "Нет" option
            false_entries = await conn.fetch(
                """SELECT ve.selected_option_ids FROM values_enum ve
                   JOIN entries e ON e.id = ve.entry_id
                   WHERE e.metric_id = $1 AND e.date IN ('2026-01-13', '2026-01-14')""",
                mid,
            )
            for row in false_entries:
                assert row["selected_option_ids"] == [opt_map["Нет"]]

    async def test_enum_options_sort_order(
        self, client: AsyncClient, user_a: dict, bool_metric: dict, db_pool,
    ):
        mid = bool_metric["id"]
        labels = ["Первый", "Второй", "Третий"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=labels,
            mapping={"true": "Первый", "false": "Второй"},
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            opts = await conn.fetch(
                "SELECT label, sort_order FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
                mid,
            )
            for i, opt in enumerate(opts):
                assert opt["sort_order"] == i
                assert opt["label"] == labels[i]

    async def test_metric_with_slots(
        self, client: AsyncClient, user_a: dict, db_pool,
    ):
        """Bool metric with measurement slots — slot_id must be preserved."""
        token = user_a["token"]
        slot_u = await create_slot(client, token, "Утро")
        slot_v = await create_slot(client, token, "Вечер")
        metric = await create_metric(
            client, token,
            name="Bool Slots", metric_type="bool",
            slot_configs=[{"slot_id": slot_u["id"]}, {"slot_id": slot_v["id"]}],
        )
        mid = metric["id"]
        slots = metric["slots"]
        assert len(slots) == 2

        await create_entry(client, token, mid, "2026-01-10", True, slot_id=slots[0]["id"])
        await create_entry(client, token, mid, "2026-01-10", False, slot_id=slots[1]["id"])

        status, body = await _do_convert(
            client, token, mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 2

        # Verify slot_ids preserved
        async with db_pool.acquire() as conn:
            entries = await conn.fetch(
                "SELECT id, slot_id FROM entries WHERE metric_id = $1 ORDER BY slot_id", mid,
            )
            slot_ids = {r["slot_id"] for r in entries}
            assert slot_ids == {slots[0]["id"], slots[1]["id"]}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestBoolToEnumEdgeCases:

    async def test_empty_mapping_with_entries(
        self, client: AsyncClient, user_a: dict, bool_metric_with_entries: dict,
    ):
        """Empty mapping when entries exist → 400 incomplete."""
        mid = bool_metric_with_entries["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["Да", "Нет"],
            mapping={},
        )
        assert status == 400

    async def test_whitespace_only_label(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """Whitespace-only labels — no server-side validation expected."""
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["   ", "Нет"],
            mapping={"true": "   ", "false": "Нет"},
        )
        assert status == 200

    async def test_label_exceeds_varchar_limit(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """Label 256 chars — exceeds VARCHAR(200) in enum_options.

        BUG: No server-side length validation — asyncpg raises
        StringDataRightTruncationError which propagates through ASGI transport.
        """
        import asyncpg
        long_label = "X" * 256
        with pytest.raises(asyncpg.exceptions.StringDataRightTruncationError):
            await _do_convert(
                client, user_a["token"], bool_metric["id"],
                options=[long_label, "Нет"],
                mapping={"true": long_label, "false": "Нет"},
            )

    async def test_many_enum_options(
        self, client: AsyncClient, user_a: dict, bool_metric: dict, db_pool,
    ):
        """50 options — all created with correct sort_order."""
        labels = [f"Option_{i}" for i in range(50)]
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=labels,
            mapping={"true": "Option_0", "false": "Option_1"},
        )
        assert status == 200

        mid = bool_metric["id"]
        async with db_pool.acquire() as conn:
            opts = await conn.fetch(
                "SELECT label, sort_order FROM enum_options WHERE metric_id = $1 ORDER BY sort_order",
                mid,
            )
            assert len(opts) == 50
            for i, opt in enumerate(opts):
                assert opt["sort_order"] == i
                assert opt["label"] == f"Option_{i}"

    async def test_verify_multi_select_db_state(
        self, client: AsyncClient, user_a: dict, bool_metric: dict, db_pool,
    ):
        """multi_select=True is stored in enum_config."""
        mid = bool_metric["id"]
        status, _ = await _do_convert(
            client, user_a["token"], mid,
            options=["A", "B"],
            mapping={"true": "A", "false": "B"},
            multi_select=True,
        )
        assert status == 200

        async with db_pool.acquire() as conn:
            ec = await conn.fetchrow(
                "SELECT multi_select FROM enum_config WHERE metric_id = $1", mid,
            )
            assert ec is not None
            assert ec["multi_select"] is True

    async def test_empty_string_label(
        self, client: AsyncClient, user_a: dict, bool_metric: dict,
    ):
        """Empty string label — no server-side validation expected."""
        status, _ = await _do_convert(
            client, user_a["token"], bool_metric["id"],
            options=["", "Нет"],
            mapping={"true": "", "false": "Нет"},
        )
        assert status == 200

    async def test_large_number_of_entries_bool(
        self, client: AsyncClient, user_a: dict,
    ):
        """50 bool entries — batch INSERT/DELETE correctness."""
        token = user_a["token"]
        metric = await create_metric(
            client, token, name="Large Bool", metric_type="bool",
        )
        mid = metric["id"]
        for i in range(50):
            val = i % 2 == 0  # alternating True/False
            await create_entry(client, token, mid, f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", val)

        status, body = await _do_convert(
            client, token, mid,
            options=["Да", "Нет"],
            mapping={"true": "Да", "false": "Нет"},
        )
        assert status == 200
        assert body["converted"] == 50
        assert body["deleted"] == 0
