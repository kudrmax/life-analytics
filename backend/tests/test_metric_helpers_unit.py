"""Unit tests for domain/privacy, domain/formatters, services/metric_builder,
repositories/entry_repository, repositories/metric_repository — pure functions and async functions with mocks."""

import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.privacy import mask_name, mask_icon, is_blocked
from app.domain.formatters import format_display_value
from app.services.metric_builder import build_metric_out
from app.repositories.entry_repository import EntryRepository
from app.repositories.metric_repository import MetricRepository


# ===================================================================
# Pure function tests (no DB, no mocks)
# ===================================================================


class TestMaskName(unittest.TestCase):
    """Tests for mask_name(name, is_private, privacy_mode)."""

    def test_private_and_privacy_mode_returns_mask(self) -> None:
        assert mask_name("Вес", is_private=True, privacy_mode=True) == "***"

    def test_private_without_privacy_mode_returns_original(self) -> None:
        assert mask_name("Вес", is_private=True, privacy_mode=False) == "Вес"

    def test_not_private_with_privacy_mode_returns_original(self) -> None:
        assert mask_name("Вес", is_private=False, privacy_mode=True) == "Вес"

    def test_not_private_without_privacy_mode_returns_original(self) -> None:
        assert mask_name("Вес", is_private=False, privacy_mode=False) == "Вес"


class TestMaskIcon(unittest.TestCase):
    """Tests for mask_icon(icon, is_private, privacy_mode)."""

    def test_private_and_privacy_mode_returns_lock(self) -> None:
        assert mask_icon("🏋️", is_private=True, privacy_mode=True) == "🔒"

    def test_not_private_with_privacy_mode_returns_original(self) -> None:
        assert mask_icon("🏋️", is_private=False, privacy_mode=True) == "🏋️"


class TestIsBlocked(unittest.TestCase):
    """Tests for is_blocked(is_private, privacy_mode)."""

    def test_both_true(self) -> None:
        assert is_blocked(is_private=True, privacy_mode=True) is True

    def test_private_only(self) -> None:
        assert is_blocked(is_private=True, privacy_mode=False) is False

    def test_privacy_mode_only(self) -> None:
        assert is_blocked(is_private=False, privacy_mode=True) is False

    def test_both_false(self) -> None:
        assert is_blocked(is_private=False, privacy_mode=False) is False


class TestFormatDisplayValue(unittest.TestCase):
    """Tests for format_display_value(value, metric_type, result_type, enum_options)."""

    # --- None ---
    def test_none_value_returns_dash(self) -> None:
        assert format_display_value(None, "number") == "—"

    # --- bool ---
    def test_bool_true(self) -> None:
        assert format_display_value(True, "bool") == "Да"

    def test_bool_false(self) -> None:
        assert format_display_value(False, "bool") == "Нет"

    # --- number ---
    def test_number_value(self) -> None:
        assert format_display_value(42, "number") == "42"

    # --- duration ---
    def test_duration_with_hours_and_minutes(self) -> None:
        assert format_display_value(90, "duration") == "1ч 30м"

    def test_duration_minutes_only(self) -> None:
        assert format_display_value(30, "duration") == "30м"

    # --- time ---
    def test_time_value(self) -> None:
        assert format_display_value("14:30", "time") == "14:30"

    def test_time_none(self) -> None:
        assert format_display_value(None, "time") == "—"

    # --- enum ---
    def test_enum_with_options(self) -> None:
        options = [
            {"id": 1, "label": "opt1"},
            {"id": 2, "label": "opt2"},
        ]
        result = format_display_value([1, 2], "enum", enum_options=options)
        assert result == "opt1, opt2"

    def test_enum_without_options(self) -> None:
        result = format_display_value([1, 2], "enum")
        assert result == "1, 2"

    # --- computed ---
    def test_computed_float(self) -> None:
        result = format_display_value(3.14159, "computed", result_type="float")
        assert result == "3.14"

    def test_computed_bool_true(self) -> None:
        result = format_display_value(True, "computed", result_type="bool")
        assert result == "Да"

    def test_computed_int(self) -> None:
        result = format_display_value(7.6, "computed", result_type="int")
        assert result == "8"

    def test_computed_time(self) -> None:
        result = format_display_value("14:30", "computed", result_type="time")
        assert result == "14:30"

    # --- scale ---
    def test_scale_value(self) -> None:
        assert format_display_value(3, "scale") == "3"


class TestFormatDisplayValueEdgeCases(unittest.TestCase):
    """Edge cases for format_display_value to increase branch coverage."""

    def test_enum_non_list_returns_dash(self) -> None:
        """Non-list value for enum type should return dash."""
        assert format_display_value("not_list", "enum") == "—"

    def test_enum_non_list_int_returns_dash(self) -> None:
        """Integer value for enum type should return dash."""
        assert format_display_value(5, "enum") == "—"

    def test_duration_zero(self) -> None:
        """Zero duration should return '0м'."""
        assert format_display_value(0, "duration") == "0м"

    def test_duration_exact_hours(self) -> None:
        """Duration with exact hours (no remainder minutes)."""
        assert format_display_value(120, "duration") == "2ч 0м"

    def test_bool_zero_int(self) -> None:
        """Integer 0 treated as bool should return 'Нет'."""
        assert format_display_value(0, "bool") == "Нет"

    def test_bool_one_int(self) -> None:
        """Integer 1 treated as bool should return 'Да'."""
        assert format_display_value(1, "bool") == "Да"

    def test_computed_no_result_type(self) -> None:
        """Computed without result_type defaults to 'float' formatting."""
        assert format_display_value(3.14, "computed") == "3.14"

    def test_computed_no_result_type_int_value(self) -> None:
        """Computed with integer value and no result_type uses str()."""
        assert format_display_value(42, "computed") == "42"

    def test_computed_duration(self) -> None:
        """Computed with result_type='duration' returns str(value)."""
        assert format_display_value(90, "computed", result_type="duration") == "90"

    def test_computed_bool_false(self) -> None:
        """Computed with result_type='bool' and falsy value."""
        assert format_display_value(False, "computed", result_type="bool") == "Нет"

    def test_computed_bool_zero(self) -> None:
        """Computed with result_type='bool' and zero value."""
        assert format_display_value(0, "computed", result_type="bool") == "Нет"

    def test_computed_int_with_string_value(self) -> None:
        """Computed with result_type='int' and non-numeric value uses str()."""
        assert format_display_value("abc", "computed", result_type="int") == "abc"

    def test_computed_float_with_int_value(self) -> None:
        """Computed with result_type='float' and int value uses str()."""
        assert format_display_value(42, "computed", result_type="float") == "42"

    def test_text_type(self) -> None:
        """Text type should fall through to bool branch and return str."""
        # text type is not handled explicitly; falls to the bool branch
        result = format_display_value("hello", "text")
        assert result == "Да"  # truthy string -> "Да"

    def test_scale_zero(self) -> None:
        """Scale with zero value should return '0'."""
        assert format_display_value(0, "scale") == "0"

    def test_scale_with_label(self) -> None:
        """Scale with labels returns label text."""
        labels = {"0": "нет", "1": "мало", "2": "достаточно"}
        assert format_display_value(0, "scale", scale_labels=labels) == "нет"
        assert format_display_value(1, "scale", scale_labels=labels) == "мало"
        assert format_display_value(2, "scale", scale_labels=labels) == "достаточно"

    def test_scale_with_partial_labels(self) -> None:
        """Scale with partial labels: labeled values get text, others get number."""
        labels = {"0": "нет", "2": "норм"}
        assert format_display_value(0, "scale", scale_labels=labels) == "нет"
        assert format_display_value(1, "scale", scale_labels=labels) == "1"
        assert format_display_value(2, "scale", scale_labels=labels) == "норм"

    def test_scale_with_empty_labels(self) -> None:
        """Scale with empty labels dict behaves like no labels."""
        assert format_display_value(3, "scale", scale_labels={}) == "3"

    def test_scale_with_none_labels(self) -> None:
        """Scale with None labels behaves normally."""
        assert format_display_value(3, "scale", scale_labels=None) == "3"

    def test_number_type_ignores_scale_labels(self) -> None:
        """Number type should not use scale_labels."""
        labels = {"42": "answer"}
        assert format_display_value(42, "number", scale_labels=labels) == "42"

    def test_integration_type(self) -> None:
        """Integration type should return str(value)."""
        assert format_display_value(42, "integration") == "42"

    def test_integration_type_string(self) -> None:
        """Integration type with string value."""
        assert format_display_value("test", "integration") == "test"

    def test_time_empty_string(self) -> None:
        """Time with empty string should return dash (falsy)."""
        assert format_display_value("", "time") == "—"

    def test_number_zero(self) -> None:
        """Number with zero — zero is falsy but not None, should return '0'."""
        result = format_display_value(0, "number")
        # 0 is not None, so str(0) = "0"
        assert result == "0"

    def test_enum_empty_list(self) -> None:
        """Enum with empty list returns empty string (no items to join)."""
        assert format_display_value([], "enum") == ""

    def test_enum_option_id_not_in_options(self) -> None:
        """Enum with option ID not found in options dict falls back to str(oid)."""
        options = [{"id": 1, "label": "A"}]
        result = format_display_value([1, 99], "enum", enum_options=options)
        assert result == "A, 99"


# ===================================================================
# _parse_time tests (pure function)
# ===================================================================


class TestParseTime(unittest.TestCase):
    """Tests for EntryRepository._parse_time(value, entry_date)."""

    def test_with_specific_date(self) -> None:
        """Parse HH:MM with a specific date."""
        result = EntryRepository._parse_time("14:30", date(2026, 3, 15))
        expected = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
        assert result == expected

    def test_with_none_date_uses_today(self) -> None:
        """Parse HH:MM with None date uses today."""
        result = EntryRepository._parse_time("08:00", None)
        today = date.today()
        expected = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_midnight(self) -> None:
        """Parse midnight time."""
        result = EntryRepository._parse_time("00:00", date(2026, 1, 1))
        expected = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_end_of_day(self) -> None:
        """Parse 23:59."""
        result = EntryRepository._parse_time("23:59", date(2026, 12, 31))
        expected = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
        assert result == expected


# ===================================================================
# Helper: create a dict-like mock that mimics asyncpg.Record
# ===================================================================


def _make_record(data: dict) -> MagicMock:
    """Create a MagicMock that behaves like asyncpg.Record (supports [] and .get())."""
    rec = MagicMock()
    rec.__getitem__ = lambda self, key: data[key]
    rec.get = lambda key, default=None: data.get(key, default)
    rec.__contains__ = lambda self, key: key in data
    return rec


# ===================================================================
# build_metric_out tests (async, mocked Record)
# ===================================================================


class TestBuildMetricOut:
    """Tests for build_metric_out with mocked asyncpg.Record."""

    @pytest.mark.asyncio
    async def test_basic_metric(self) -> None:
        """Build output for a simple bool metric."""
        row = _make_record({
            "id": 1, "slug": "test", "name": "Test", "type": "bool",
            "enabled": True, "sort_order": 0, "icon": "X",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "scale_labels": None,
            "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row)
        assert result.id == 1
        assert result.slug == "test"
        assert result.name == "Test"
        assert result.type.value == "bool"
        assert result.checkpoints == []
        assert result.private is False

    @pytest.mark.asyncio
    async def test_with_formula_as_json_string(self) -> None:
        """Formula stored as JSON string should be deserialized."""
        formula_tokens = [{"type": "metric", "id": 5}, {"type": "op", "value": "+"}]
        row = _make_record({
            "id": 2, "slug": "comp", "name": "Computed", "type": "computed",
            "enabled": True, "sort_order": 1, "icon": "",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "formula": json.dumps(formula_tokens),
            "result_type": "float", "provider": None, "metric_key": None,
            "value_type": None, "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row)
        assert result.formula == formula_tokens
        assert result.result_type == "float"

    @pytest.mark.asyncio
    async def test_with_formula_already_parsed(self) -> None:
        """Formula already a list should not be double-parsed."""
        formula_tokens = [{"type": "number", "value": 42}]
        row = _make_record({
            "id": 3, "slug": "comp2", "name": "Computed2", "type": "computed",
            "enabled": True, "sort_order": 2, "icon": "",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "formula": formula_tokens,
            "result_type": "int", "provider": None, "metric_key": None,
            "value_type": None, "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row)
        assert result.formula == formula_tokens

    @pytest.mark.asyncio
    async def test_with_privacy_mode(self) -> None:
        """Private metric with privacy mode ON should mask name and icon."""
        row = _make_record({
            "id": 4, "slug": "private", "name": "Secret", "type": "number",
            "enabled": True, "sort_order": 0, "icon": "S",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": True,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row, privacy_mode=True)
        assert result.name == "***"
        assert result.icon == "🔒"
        assert result.private is True

    @pytest.mark.asyncio
    async def test_with_checkpoints(self) -> None:
        """Checkpoints should be converted to CheckpointOut."""
        row = _make_record({
            "id": 5, "slug": "cp_metric", "name": "WithCPs", "type": "bool",
            "enabled": True, "sort_order": 0, "icon": "",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "scale_labels": None,
            "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        checkpoints = [
            {"id": 10, "label": "Morning", "sort_order": 0, "category_id": None},
            {"id": 11, "label": "Evening", "sort_order": 1, "category_id": None},
        ]
        result = await build_metric_out(row, checkpoints=checkpoints)
        assert len(result.checkpoints) == 2
        assert result.checkpoints[0].label == "Morning"
        assert result.checkpoints[1].label == "Evening"

    @pytest.mark.asyncio
    async def test_with_condition_value_json(self) -> None:
        """condition_value as JSON string should be deserialized."""
        row = _make_record({
            "id": 6, "slug": "cond", "name": "Conditional", "type": "bool",
            "enabled": True, "sort_order": 0, "icon": "",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": 10, "condition_type": "equals",
            "condition_value": "true",
        })
        result = await build_metric_out(row)
        assert result.condition_value is True
        assert result.condition_type == "equals"
        assert result.condition_metric_id == 10

    @pytest.mark.asyncio
    async def test_with_scale_labels(self) -> None:
        """Scale labels from JSONB string should be deserialized."""
        row = _make_record({
            "id": 8, "slug": "rated", "name": "Rating", "type": "scale",
            "enabled": True, "sort_order": 0, "icon": "",
            "category_id": None, "scale_min": 0, "scale_max": 2,
            "scale_step": 1, "scale_labels": json.dumps({"0": "нет", "1": "мало", "2": "много"}),
            "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row)
        assert result.scale_labels == {"0": "нет", "1": "мало", "2": "много"}

    @pytest.mark.asyncio
    async def test_with_scale_labels_none(self) -> None:
        """Null scale_labels should remain None."""
        row = _make_record({
            "id": 9, "slug": "rated2", "name": "Rating2", "type": "scale",
            "enabled": True, "sort_order": 0, "icon": "",
            "category_id": None, "scale_min": 1, "scale_max": 5,
            "scale_step": 1, "scale_labels": None,
            "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": None, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        result = await build_metric_out(row)
        assert result.scale_labels is None

    @pytest.mark.asyncio
    async def test_with_enum_options(self) -> None:
        """Enum options passed to build_metric_out."""
        row = _make_record({
            "id": 7, "slug": "mood", "name": "Mood", "type": "enum",
            "enabled": True, "sort_order": 0, "icon": "",
            "category_id": None, "scale_min": None, "scale_max": None,
            "scale_step": None, "formula": None, "result_type": None,
            "provider": None, "metric_key": None, "value_type": None,
            "filter_name": None, "filter_query": None,
            "activitywatch_category_id": None, "config_app_name": None,
            "multi_select": True, "private": False,
            "condition_metric_id": None, "condition_type": None,
            "condition_value": None,
        })
        opts = [{"id": 1, "label": "Good", "sort_order": 0, "enabled": True}]
        result = await build_metric_out(row, enum_opts=opts)
        assert result.enum_options == opts
        assert result.multi_select is True


# ===================================================================
# get_entry_value tests (async, mocked connection)
# ===================================================================


class TestGetEntryValue:
    """Tests for EntryRepository.get_entry_value with mocked asyncpg connection."""

    def _make_repo(self, conn: AsyncMock) -> EntryRepository:
        return EntryRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_time_type_returns_formatted(self) -> None:
        """Time type returns HH:MM string."""
        ts = MagicMock()
        ts.hour = 14
        ts.minute = 5
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value": ts}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="time")
        assert result == "14:05"

    @pytest.mark.asyncio
    async def test_time_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="time")
        assert result is None

    @pytest.mark.asyncio
    async def test_number_type_returns_value(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value": 42}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="number")
        assert result == 42

    @pytest.mark.asyncio
    async def test_number_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="number")
        assert result is None

    @pytest.mark.asyncio
    async def test_scale_type_returns_value(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value": 3}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="scale")
        assert result == 3

    @pytest.mark.asyncio
    async def test_scale_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="scale")
        assert result is None

    @pytest.mark.asyncio
    async def test_duration_type_returns_value(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value": 90}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="duration")
        assert result == 90

    @pytest.mark.asyncio
    async def test_duration_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="duration")
        assert result is None

    @pytest.mark.asyncio
    async def test_enum_type_returns_list(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"selected_option_ids": [1, 3, 5]}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="enum")
        assert result == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_enum_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="enum")
        assert result is None

    @pytest.mark.asyncio
    async def test_bool_type_returns_value(self) -> None:
        """Default (bool) branch returns value."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value": True}
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="bool")
        assert result is True

    @pytest.mark.asyncio
    async def test_bool_type_no_row_returns_none(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_entry_value(entry_id=1, metric_type="bool")
        assert result is None


# ===================================================================
# insert_value tests (async, mocked connection)
# ===================================================================


class TestInsertValue:
    """Tests for EntryRepository.insert_value with mocked asyncpg connection."""

    def _make_repo(self, conn: AsyncMock) -> EntryRepository:
        return EntryRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_insert_time(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value="14:30", metric_type="time",
                           entry_date=date(2026, 3, 15))
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_time" in args[0][0]

    @pytest.mark.asyncio
    async def test_insert_number(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value=42, metric_type="number")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_number" in args[0][0]
        assert args[0][2] == 42

    @pytest.mark.asyncio
    async def test_insert_scale_with_config(self) -> None:
        """Scale insert reads config from scale_config table."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"scale_min": 1, "scale_max": 10, "scale_step": 2}
        await self._make_repo(conn).insert_value(entry_id=1, value=5, metric_type="scale", metric_id=10)
        conn.fetchrow.assert_called_once()
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_scale" in args[0][0]
        # value=5, scale_min=1, scale_max=10, scale_step=2
        assert args[0][2] == 5
        assert args[0][3] == 1
        assert args[0][4] == 10
        assert args[0][5] == 2

    @pytest.mark.asyncio
    async def test_insert_scale_no_config_uses_defaults(self) -> None:
        """Scale insert without config uses defaults (1, 5, 1)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        await self._make_repo(conn).insert_value(entry_id=1, value=3, metric_type="scale", metric_id=10)
        args = conn.execute.call_args
        # defaults: scale_min=1, scale_max=5, scale_step=1
        assert args[0][3] == 1
        assert args[0][4] == 5
        assert args[0][5] == 1

    @pytest.mark.asyncio
    async def test_insert_duration(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value=90, metric_type="duration")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_duration" in args[0][0]

    @pytest.mark.asyncio
    async def test_insert_enum_list(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value=[1, 2], metric_type="enum")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_enum" in args[0][0]
        assert args[0][2] == [1, 2]

    @pytest.mark.asyncio
    async def test_insert_enum_single_value(self) -> None:
        """Non-list value for enum wraps in a list."""
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value=5, metric_type="enum")
        args = conn.execute.call_args
        assert args[0][2] == [5]

    @pytest.mark.asyncio
    async def test_insert_bool(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).insert_value(entry_id=1, value=True, metric_type="bool")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "values_bool" in args[0][0]
        assert args[0][2] is True


# ===================================================================
# update_value tests (async, mocked connection)
# ===================================================================


class TestUpdateValue:
    """Tests for EntryRepository.update_value with mocked asyncpg connection."""

    def _make_repo(self, conn: AsyncMock) -> EntryRepository:
        return EntryRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_update_time(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value="08:15", metric_type="time",
                           entry_date=date(2026, 3, 15))
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_time" in args[0][0]

    @pytest.mark.asyncio
    async def test_update_number(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=99, metric_type="number")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_number" in args[0][0]

    @pytest.mark.asyncio
    async def test_update_scale(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=4, metric_type="scale")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_scale" in args[0][0]

    @pytest.mark.asyncio
    async def test_update_duration(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=45, metric_type="duration")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_duration" in args[0][0]

    @pytest.mark.asyncio
    async def test_update_enum_list(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=[2, 3], metric_type="enum")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_enum" in args[0][0]
        assert args[0][1] == [2, 3]

    @pytest.mark.asyncio
    async def test_update_enum_single_value(self) -> None:
        """Non-list value for enum wraps in a list."""
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=7, metric_type="enum")
        args = conn.execute.call_args
        assert args[0][1] == [7]

    @pytest.mark.asyncio
    async def test_update_bool(self) -> None:
        conn = AsyncMock()
        await self._make_repo(conn).update_value(entry_id=1, value=False, metric_type="bool")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "UPDATE values_bool" in args[0][0]


# ===================================================================
# resolve_storage_type tests (async, mocked connection)
# ===================================================================


class TestResolveStorageType:
    """Tests for EntryRepository.resolve_storage_type."""

    def _make_repo(self, conn: AsyncMock) -> EntryRepository:
        return EntryRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_non_integration_returns_type_as_is(self) -> None:
        conn = AsyncMock()
        result = await self._make_repo(conn).resolve_storage_type(metric_id=1, metric_type="bool")
        assert result == "bool"
        conn.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_integration_returns_value_type(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"value_type": "duration"}
        result = await self._make_repo(conn).resolve_storage_type(metric_id=1, metric_type="integration")
        assert result == "duration"

    @pytest.mark.asyncio
    async def test_integration_no_config_returns_number(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).resolve_storage_type(metric_id=1, metric_type="integration")
        assert result == "number"


# ===================================================================
# get_metric_type tests (async, mocked connection)
# ===================================================================


class TestGetMetricType:
    """Tests for EntryRepository.get_metric_type."""

    def _make_repo(self, conn: AsyncMock) -> EntryRepository:
        return EntryRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_found(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = {"type": "scale"}
        result = await self._make_repo(conn).get_metric_type(metric_id=1)
        assert result == "scale"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        result = await self._make_repo(conn).get_metric_type(metric_id=999)
        assert result is None


# ===================================================================
# get_metric_checkpoints tests (async, mocked connection)
# ===================================================================


class TestGetMetricCheckpoints:
    """Tests for MetricRepository.get_checkpoints_for_metrics."""

    def _make_repo(self, conn: AsyncMock) -> MetricRepository:
        return MetricRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_returns_grouped_checkpoints(self) -> None:
        row1 = {"metric_id": 1, "id": 10, "label": "Morning", "sort_order": 0, "category_id": None}
        row2 = {"metric_id": 1, "id": 11, "label": "Evening", "sort_order": 1, "category_id": None}
        row3 = {"metric_id": 2, "id": 20, "label": "Daily", "sort_order": 0, "category_id": 5}
        conn = AsyncMock()
        conn.fetch.return_value = [_make_record(row1), _make_record(row2), _make_record(row3)]
        result = await self._make_repo(conn).get_checkpoints_for_metrics(metric_ids=[1, 2])
        assert len(result[1]) == 2
        assert len(result[2]) == 1
        assert result[1][0]["label"] == "Morning"
        assert result[2][0]["category_id"] == 5

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []
        result = await self._make_repo(conn).get_checkpoints_for_metrics(metric_ids=[1])
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_enabled_only_true(self) -> None:
        """enabled_only=True adds AND msl.enabled = TRUE condition."""
        conn = AsyncMock()
        conn.fetch.return_value = []
        await self._make_repo(conn).get_checkpoints_for_metrics(metric_ids=[1], enabled_only=True)
        query = conn.fetch.call_args[0][0]
        assert "AND mc.enabled = TRUE" in query

    @pytest.mark.asyncio
    async def test_enabled_only_false(self) -> None:
        """enabled_only=False does not add enabled condition."""
        conn = AsyncMock()
        conn.fetch.return_value = []
        await self._make_repo(conn).get_checkpoints_for_metrics(metric_ids=[1], enabled_only=False)
        query = conn.fetch.call_args[0][0]
        assert "AND msl.enabled = TRUE" not in query


# ===================================================================
# get_enum_options tests (async, mocked connection)
# ===================================================================


class TestGetEnumOptions:
    """Tests for MetricRepository.get_enum_options_for_metrics."""

    def _make_repo(self, conn: AsyncMock) -> MetricRepository:
        return MetricRepository(conn, user_id=1)

    @pytest.mark.asyncio
    async def test_returns_grouped_options(self) -> None:
        row1 = {"metric_id": 1, "id": 100, "label": "Good", "sort_order": 0, "enabled": True}
        row2 = {"metric_id": 1, "id": 101, "label": "Bad", "sort_order": 1, "enabled": True}
        conn = AsyncMock()
        conn.fetch.return_value = [_make_record(row1), _make_record(row2)]
        result = await self._make_repo(conn).get_enum_options_for_metrics(metric_ids=[1])
        assert len(result[1]) == 2
        assert result[1][0]["label"] == "Good"
        assert result[1][1]["label"] == "Bad"

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []
        result = await self._make_repo(conn).get_enum_options_for_metrics(metric_ids=[1])
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_enabled_only_true(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []
        await self._make_repo(conn).get_enum_options_for_metrics(metric_ids=[1], enabled_only=True)
        query = conn.fetch.call_args[0][0]
        assert "AND eo.enabled = TRUE" in query

    @pytest.mark.asyncio
    async def test_enabled_only_false(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []
        await self._make_repo(conn).get_enum_options_for_metrics(metric_ids=[1], enabled_only=False)
        query = conn.fetch.call_args[0][0]
        assert "AND eo.enabled = TRUE" not in query


if __name__ == "__main__":
    unittest.main()
