"""Unit tests for TimeSeriesTransform.checkpoint_agg and shift_dates."""

import unittest

from app.analytics.time_series import TimeSeriesTransform

checkpoint_agg = TimeSeriesTransform.checkpoint_agg
shift_dates = TimeSeriesTransform.shift_dates


# ── checkpoint_agg ───────────────────────────────────────────────────


class TestCheckpointAggMax(unittest.TestCase):
    """Max aggregation across multiple checkpoints."""

    def test_max_from_three_checkpoints(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5, "2025-01-02": 3},
            1: {"2025-01-01": 8, "2025-01-02": 1},
            2: {"2025-01-01": 2, "2025-01-02": 9},
        }
        result = checkpoint_agg([0, 1, 2], source, max)
        self.assertEqual(result, {"2025-01-01": 8, "2025-01-02": 9})

    def test_min_from_three_checkpoints(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5, "2025-01-02": 3},
            1: {"2025-01-01": 8, "2025-01-02": 1},
            2: {"2025-01-01": 2, "2025-01-02": 9},
        }
        result = checkpoint_agg([0, 1, 2], source, min)
        self.assertEqual(result, {"2025-01-01": 2, "2025-01-02": 1})


class TestCheckpointAggGaps(unittest.TestCase):
    """Checkpoints with non-overlapping dates."""

    def test_checkpoints_with_disjoint_dates(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 10.0},
            1: {"2025-01-02": 20.0},
        }
        result = checkpoint_agg([0, 1], source, max)
        self.assertEqual(result, {"2025-01-01": 10.0, "2025-01-02": 20.0})

    def test_partial_overlap(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 3.0, "2025-01-02": 7.0},
            1: {"2025-01-02": 4.0, "2025-01-03": 9.0},
        }
        result = checkpoint_agg([0, 1], source, max)
        self.assertEqual(result, {
            "2025-01-01": 3.0,
            "2025-01-02": 7.0,
            "2025-01-03": 9.0,
        })


class TestCheckpointAggSingleSlot(unittest.TestCase):
    """Single checkpoint returns its own data."""

    def test_single_checkpoint_max(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5.0, "2025-01-02": 3.0},
        }
        result = checkpoint_agg([0], source, max)
        self.assertEqual(result, {"2025-01-01": 5.0, "2025-01-02": 3.0})

    def test_single_checkpoint_min(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5.0, "2025-01-02": 3.0},
        }
        result = checkpoint_agg([0], source, min)
        self.assertEqual(result, {"2025-01-01": 5.0, "2025-01-02": 3.0})


class TestCheckpointAggEmpty(unittest.TestCase):
    """Edge cases with empty inputs."""

    def test_empty_checkpoint_indices(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5.0},
        }
        result = checkpoint_agg([], source, max)
        self.assertEqual(result, {})

    def test_missing_index_in_source(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": 5.0},
        }
        # Index 1 is not in source_data — should be skipped gracefully
        result = checkpoint_agg([0, 1], source, max)
        self.assertEqual(result, {"2025-01-01": 5.0})

    def test_all_indices_missing(self) -> None:
        source: dict[int, dict[str, float]] = {}
        result = checkpoint_agg([0, 1, 2], source, max)
        self.assertEqual(result, {})

    def test_empty_source_and_indices(self) -> None:
        result = checkpoint_agg([], {}, max)
        self.assertEqual(result, {})


class TestCheckpointAggNegativeValues(unittest.TestCase):
    """Negative and zero values."""

    def test_negative_values_max(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": -5.0},
            1: {"2025-01-01": -2.0},
            2: {"2025-01-01": -8.0},
        }
        result = checkpoint_agg([0, 1, 2], source, max)
        self.assertEqual(result, {"2025-01-01": -2.0})

    def test_negative_values_min(self) -> None:
        source: dict[int, dict[str, float]] = {
            0: {"2025-01-01": -5.0},
            1: {"2025-01-01": -2.0},
            2: {"2025-01-01": -8.0},
        }
        result = checkpoint_agg([0, 1, 2], source, min)
        self.assertEqual(result, {"2025-01-01": -8.0})


# ── shift_dates ──────────────────────────────────────────────────────


class TestShiftDatesBasic(unittest.TestCase):
    """Basic forward shifts."""

    def test_shift_by_1_day(self) -> None:
        result = shift_dates({"2025-01-15": 5.0}, 1)
        self.assertEqual(result, {"2025-01-16": 5.0})

    def test_shift_by_7_days(self) -> None:
        result = shift_dates({"2025-01-15": 5.0}, 7)
        self.assertEqual(result, {"2025-01-22": 5.0})

    def test_multiple_entries(self) -> None:
        data = {
            "2025-01-01": 1.0,
            "2025-01-02": 2.0,
            "2025-01-03": 3.0,
        }
        result = shift_dates(data, 1)
        self.assertEqual(result, {
            "2025-01-02": 1.0,
            "2025-01-03": 2.0,
            "2025-01-04": 3.0,
        })


class TestShiftDatesEmpty(unittest.TestCase):
    """Empty input."""

    def test_empty_dict(self) -> None:
        result = shift_dates({}, 1)
        self.assertEqual(result, {})

    def test_empty_dict_zero_shift(self) -> None:
        result = shift_dates({}, 0)
        self.assertEqual(result, {})


class TestShiftDatesBoundaries(unittest.TestCase):
    """Month and year boundary crossings."""

    def test_cross_month_jan_to_feb(self) -> None:
        result = shift_dates({"2025-01-31": 10.0}, 1)
        self.assertEqual(result, {"2025-02-01": 10.0})

    def test_cross_year(self) -> None:
        result = shift_dates({"2025-12-31": 42.0}, 1)
        self.assertEqual(result, {"2026-01-01": 42.0})

    def test_cross_feb_28_non_leap(self) -> None:
        result = shift_dates({"2025-02-28": 7.0}, 1)
        self.assertEqual(result, {"2025-03-01": 7.0})

    def test_cross_feb_29_leap_year(self) -> None:
        result = shift_dates({"2024-02-28": 7.0}, 1)
        self.assertEqual(result, {"2024-02-29": 7.0})

    def test_cross_feb_29_to_mar_leap_year(self) -> None:
        result = shift_dates({"2024-02-29": 7.0}, 1)
        self.assertEqual(result, {"2024-03-01": 7.0})


class TestShiftDatesZeroAndNegative(unittest.TestCase):
    """Zero shift and negative shifts (backward)."""

    def test_zero_shift(self) -> None:
        data = {"2025-06-15": 3.0}
        result = shift_dates(data, 0)
        self.assertEqual(result, {"2025-06-15": 3.0})

    def test_negative_shift(self) -> None:
        result = shift_dates({"2025-01-15": 5.0}, -1)
        self.assertEqual(result, {"2025-01-14": 5.0})

    def test_negative_shift_cross_year(self) -> None:
        result = shift_dates({"2025-01-01": 5.0}, -1)
        self.assertEqual(result, {"2024-12-31": 5.0})


class TestShiftDatesValuesPreserved(unittest.TestCase):
    """Values are preserved exactly after shift."""

    def test_float_values_preserved(self) -> None:
        data = {"2025-01-01": 3.14159}
        result = shift_dates(data, 1)
        self.assertEqual(result["2025-01-02"], 3.14159)

    def test_zero_value_preserved(self) -> None:
        data = {"2025-01-01": 0.0}
        result = shift_dates(data, 1)
        self.assertEqual(result["2025-01-02"], 0.0)

    def test_negative_value_preserved(self) -> None:
        data = {"2025-01-01": -99.5}
        result = shift_dates(data, 1)
        self.assertEqual(result["2025-01-02"], -99.5)


if __name__ == "__main__":
    unittest.main()
