"""Unit tests for ValueConverter (extract_numeric, aggregate_by_date, get_value_table)."""

import unittest
from datetime import datetime, date
from typing import Any

from app.analytics.value_converter import ValueConverter


def _row(**kwargs: Any) -> dict[str, Any]:
    """Helper to build a fake value row dict."""
    return kwargs


class TestExtractNumericBool(unittest.TestCase):
    """extract_numeric for bool metric type (default)."""

    def test_true_returns_1(self) -> None:
        result = ValueConverter.extract_numeric({"value": True})
        self.assertEqual(result, 1.0)

    def test_false_returns_0(self) -> None:
        result = ValueConverter.extract_numeric({"value": False})
        self.assertEqual(result, 0.0)

    def test_truthy_int_returns_1(self) -> None:
        result = ValueConverter.extract_numeric({"value": 1})
        self.assertEqual(result, 1.0)

    def test_zero_returns_0(self) -> None:
        result = ValueConverter.extract_numeric({"value": 0})
        self.assertEqual(result, 0.0)


class TestExtractNumericNone(unittest.TestCase):
    """extract_numeric returns None for missing/empty value_row."""

    def test_none_row(self) -> None:
        self.assertIsNone(ValueConverter.extract_numeric(None))

    def test_empty_dict(self) -> None:
        self.assertIsNone(ValueConverter.extract_numeric({}))

    def test_empty_list(self) -> None:
        self.assertIsNone(ValueConverter.extract_numeric([]))

    def test_zero_value_row(self) -> None:
        """0 is falsy, so extract_numeric(0) should return None."""
        self.assertIsNone(ValueConverter.extract_numeric(0))


class TestExtractNumericTime(unittest.TestCase):
    """extract_numeric for time metric type — minutes from midnight."""

    def test_midnight(self) -> None:
        row = {"value": datetime(2026, 1, 1, 0, 0)}
        self.assertEqual(ValueConverter.extract_numeric(row, "time"), 0.0)

    def test_noon(self) -> None:
        row = {"value": datetime(2026, 1, 1, 12, 0)}
        self.assertEqual(ValueConverter.extract_numeric(row, "time"), 720.0)

    def test_14_30(self) -> None:
        row = {"value": datetime(2026, 1, 1, 14, 30)}
        self.assertEqual(ValueConverter.extract_numeric(row, "time"), 870.0)

    def test_23_59(self) -> None:
        row = {"value": datetime(2026, 1, 1, 23, 59)}
        self.assertEqual(ValueConverter.extract_numeric(row, "time"), 1439.0)

    def test_1_01(self) -> None:
        row = {"value": datetime(2026, 3, 15, 1, 1)}
        self.assertEqual(ValueConverter.extract_numeric(row, "time"), 61.0)


class TestExtractNumericNumber(unittest.TestCase):
    """extract_numeric for number metric type."""

    def test_integer(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": 42}, "number"), 42.0)

    def test_float_value(self) -> None:
        self.assertAlmostEqual(
            ValueConverter.extract_numeric({"value": 3.14}, "number"), 3.14  # type: ignore[arg-type]
        )

    def test_zero(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": 0}, "number"), 0.0)

    def test_negative(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": -10}, "number"), -10.0)


class TestExtractNumericDuration(unittest.TestCase):
    """extract_numeric for duration metric type."""

    def test_positive_duration(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": 90}, "duration"), 90.0)

    def test_zero_duration(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": 0}, "duration"), 0.0)

    def test_large_duration(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": 1440}, "duration"), 1440.0)


class TestExtractNumericScale(unittest.TestCase):
    """extract_numeric for scale metric type — normalized to 0-100%."""

    def test_mid_range(self) -> None:
        """(3-1)/(5-1)*100 = 50.0."""
        row = {"value": 3, "scale_min": 1, "scale_max": 5}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 50.0)

    def test_min_value(self) -> None:
        """(1-1)/(5-1)*100 = 0.0."""
        row = {"value": 1, "scale_min": 1, "scale_max": 5}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 0.0)

    def test_max_value(self) -> None:
        """(5-1)/(5-1)*100 = 100.0."""
        row = {"value": 5, "scale_min": 1, "scale_max": 5}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 100.0)

    def test_min_equals_max_returns_zero(self) -> None:
        """When scale_min == scale_max, return 0.0 (avoid division by zero)."""
        row = {"value": 3, "scale_min": 3, "scale_max": 3}
        self.assertEqual(ValueConverter.extract_numeric(row, "scale"), 0.0)

    def test_wide_range(self) -> None:
        """(50-0)/(100-0)*100 = 50.0."""
        row = {"value": 50, "scale_min": 0, "scale_max": 100}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 50.0)

    def test_quarter_range(self) -> None:
        """(2-0)/(10-0)*100 = 20.0."""
        row = {"value": 2, "scale_min": 0, "scale_max": 10}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 20.0)

    def test_negative_range(self) -> None:
        """(0-(-5))/(5-(-5))*100 = 50.0."""
        row = {"value": 0, "scale_min": -5, "scale_max": 5}
        self.assertAlmostEqual(ValueConverter.extract_numeric(row, "scale"), 50.0)


class TestExtractNumericUnknownType(unittest.TestCase):
    """extract_numeric falls back to bool logic for unknown metric types."""

    def test_unknown_type_truthy(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": "abc"}, "unknown"), 1.0)

    def test_unknown_type_falsy(self) -> None:
        self.assertEqual(ValueConverter.extract_numeric({"value": ""}, "unknown"), 0.0)


class TestAggregateBoolByDate(unittest.TestCase):
    """aggregate_by_date for bool metrics — any True → 1.0, all False → 0.0."""

    def test_single_true(self) -> None:
        rows = [{"value": True, "date": date(2026, 1, 1)}]
        result = ValueConverter.aggregate_by_date(rows, "bool")
        self.assertEqual(result, {"2026-01-01": 1.0})

    def test_single_false(self) -> None:
        rows = [{"value": False, "date": date(2026, 1, 1)}]
        result = ValueConverter.aggregate_by_date(rows, "bool")
        self.assertEqual(result, {"2026-01-01": 0.0})

    def test_mixed_true_false_same_day(self) -> None:
        """At least one True in a day → 1.0."""
        rows = [
            {"value": False, "date": date(2026, 1, 1)},
            {"value": True, "date": date(2026, 1, 1)},
            {"value": False, "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "bool")
        self.assertEqual(result, {"2026-01-01": 1.0})

    def test_all_false_same_day(self) -> None:
        rows = [
            {"value": False, "date": date(2026, 1, 1)},
            {"value": False, "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "bool")
        self.assertEqual(result, {"2026-01-01": 0.0})


class TestAggregateNumberByDate(unittest.TestCase):
    """aggregate_by_date for number metrics — mean of values per day."""

    def test_single_entry(self) -> None:
        rows = [{"value": 10, "date": date(2026, 1, 1)}]
        result = ValueConverter.aggregate_by_date(rows, "number")
        self.assertEqual(result, {"2026-01-01": 10.0})

    def test_mean_of_multiple(self) -> None:
        rows = [
            {"value": 10, "date": date(2026, 1, 1)},
            {"value": 20, "date": date(2026, 1, 1)},
            {"value": 30, "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "number")
        self.assertAlmostEqual(result["2026-01-01"], 20.0)

    def test_mixed_dates(self) -> None:
        rows = [
            {"value": 10, "date": date(2026, 1, 1)},
            {"value": 20, "date": date(2026, 1, 2)},
            {"value": 30, "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "number")
        self.assertAlmostEqual(result["2026-01-01"], 20.0)
        self.assertAlmostEqual(result["2026-01-02"], 20.0)


class TestAggregateByDateEmpty(unittest.TestCase):
    """aggregate_by_date with empty input."""

    def test_empty_rows(self) -> None:
        self.assertEqual(ValueConverter.aggregate_by_date([], "bool"), {})

    def test_empty_rows_number(self) -> None:
        self.assertEqual(ValueConverter.aggregate_by_date([], "number"), {})


class TestAggregateByDateNoneValues(unittest.TestCase):
    """aggregate_by_date skips rows where extract_numeric returns None."""

    def test_none_value_rows_skipped(self) -> None:
        """Rows that are falsy (e.g. None in list) are skipped by extract_numeric."""
        rows = [
            {"value": 10, "date": date(2026, 1, 1)},
            None,  # extract_numeric returns None → skipped
        ]
        # None will be passed to extract_numeric which returns None, so it's skipped
        # But iterating will try r["date"] on None → this tests that None rows
        # are handled by the v is not None check after extract_numeric
        # Actually, r["date"] would fail on None. The code does extract_numeric first
        # and checks v is not None before accessing r["date"]. Let's verify:
        # Looking at the code: v = extract_numeric(r, ...) then if v is not None: r["date"]
        # So None rows are safe since extract_numeric(None, ...) returns None.
        result = ValueConverter.aggregate_by_date(rows, "number")
        self.assertEqual(result, {"2026-01-01": 10.0})


class TestAggregateByDateScale(unittest.TestCase):
    """aggregate_by_date for scale — mean of normalized values."""

    def test_scale_mean(self) -> None:
        rows = [
            {"value": 3, "scale_min": 1, "scale_max": 5, "date": date(2026, 1, 1)},
            {"value": 5, "scale_min": 1, "scale_max": 5, "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "scale")
        # (50.0 + 100.0) / 2 = 75.0
        self.assertAlmostEqual(result["2026-01-01"], 75.0)


class TestAggregateByDateTime(unittest.TestCase):
    """aggregate_by_date for time — mean of minutes from midnight."""

    def test_time_mean(self) -> None:
        rows = [
            {"value": datetime(2026, 1, 1, 8, 0), "date": date(2026, 1, 1)},
            {"value": datetime(2026, 1, 1, 10, 0), "date": date(2026, 1, 1)},
        ]
        result = ValueConverter.aggregate_by_date(rows, "time")
        # (480 + 600) / 2 = 540.0
        self.assertAlmostEqual(result["2026-01-01"], 540.0)


class TestGetValueTableTime(unittest.TestCase):
    """get_value_table for time type."""

    def test_time(self) -> None:
        table, extra = ValueConverter.get_value_table("time")
        self.assertEqual(table, "values_time")
        self.assertEqual(extra, "")


class TestGetValueTableNumber(unittest.TestCase):
    """get_value_table for number type."""

    def test_number(self) -> None:
        table, extra = ValueConverter.get_value_table("number")
        self.assertEqual(table, "values_number")
        self.assertEqual(extra, "")


class TestGetValueTableDuration(unittest.TestCase):
    """get_value_table for duration type."""

    def test_duration(self) -> None:
        table, extra = ValueConverter.get_value_table("duration")
        self.assertEqual(table, "values_duration")
        self.assertEqual(extra, "")


class TestGetValueTableScale(unittest.TestCase):
    """get_value_table for scale type — includes extra columns."""

    def test_scale(self) -> None:
        table, extra = ValueConverter.get_value_table("scale")
        self.assertEqual(table, "values_scale")
        self.assertEqual(extra, ", v.scale_min, v.scale_max, v.scale_step")


class TestGetValueTableEnum(unittest.TestCase):
    """get_value_table for enum type."""

    def test_enum(self) -> None:
        table, extra = ValueConverter.get_value_table("enum")
        self.assertEqual(table, "values_enum")
        self.assertEqual(extra, "")


class TestGetValueTableBoolDefault(unittest.TestCase):
    """get_value_table for bool and unknown types — falls back to values_bool."""

    def test_bool(self) -> None:
        table, extra = ValueConverter.get_value_table("bool")
        self.assertEqual(table, "values_bool")
        self.assertEqual(extra, "")

    def test_unknown_type(self) -> None:
        table, extra = ValueConverter.get_value_table("something_else")
        self.assertEqual(table, "values_bool")
        self.assertEqual(extra, "")

    def test_empty_string(self) -> None:
        table, extra = ValueConverter.get_value_table("")
        self.assertEqual(table, "values_bool")
        self.assertEqual(extra, "")


if __name__ == "__main__":
    unittest.main()
