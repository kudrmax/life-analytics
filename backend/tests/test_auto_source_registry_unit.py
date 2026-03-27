"""Unit tests for auto source registry — compute_auto_source() for all 11 types."""

from __future__ import annotations

import unittest

from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
from app.source_key import AutoSourceType


class TestNonzero(unittest.TestCase):
    def test_positive_values(self) -> None:
        inp = AutoSourceInput(all_dates=[], parent_data={"d1": 5.0, "d2": 0.0, "d3": -1.0})
        result = compute_auto_source(AutoSourceType.NONZERO, inp)
        assert result == {"d1": 1.0, "d2": 0.0, "d3": 0.0}

    def test_empty_parent(self) -> None:
        inp = AutoSourceInput(all_dates=[], parent_data={})
        result = compute_auto_source(AutoSourceType.NONZERO, inp)
        assert result == {}

    def test_none_parent(self) -> None:
        inp = AutoSourceInput(all_dates=[])
        result = compute_auto_source(AutoSourceType.NONZERO, inp)
        assert result == {}


class TestDayOfWeek(unittest.TestCase):
    def test_monday(self) -> None:
        # 2025-01-06 is Monday (isoweekday=1)
        inp = AutoSourceInput(all_dates=["2025-01-06", "2025-01-07"], option_id=1)
        result = compute_auto_source(AutoSourceType.DAY_OF_WEEK, inp)
        assert result["2025-01-06"] == 1.0
        assert result["2025-01-07"] == 0.0

    def test_no_option_id(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-06"])
        result = compute_auto_source(AutoSourceType.DAY_OF_WEEK, inp)
        assert result == {}


class TestMonth(unittest.TestCase):
    def test_january(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-15", "2025-02-15"], option_id=1)
        result = compute_auto_source(AutoSourceType.MONTH, inp)
        assert result["2025-01-15"] == 1.0
        assert result["2025-02-15"] == 0.0

    def test_no_option_id(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-15"])
        result = compute_auto_source(AutoSourceType.MONTH, inp)
        assert result == {}


class TestIsWorkday(unittest.TestCase):
    def test_workday(self) -> None:
        # 2025-01-06 Monday, 2025-01-11 Saturday
        inp = AutoSourceInput(all_dates=["2025-01-06", "2025-01-11"], option_id=1)
        result = compute_auto_source(AutoSourceType.IS_WORKDAY, inp)
        assert result["2025-01-06"] == 1.0
        assert result["2025-01-11"] == 0.0

    def test_weekend(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-06", "2025-01-11"], option_id=2)
        result = compute_auto_source(AutoSourceType.IS_WORKDAY, inp)
        assert result["2025-01-06"] == 0.0
        assert result["2025-01-11"] == 1.0

    def test_no_option_id(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-06"])
        result = compute_auto_source(AutoSourceType.IS_WORKDAY, inp)
        assert result == {}


class TestCheckpointMax(unittest.TestCase):
    def test_max_across_slots(self) -> None:
        slot_data = [
            {"d1": 5.0, "d2": 3.0},
            {"d1": 8.0, "d2": 1.0},
        ]
        inp = AutoSourceInput(all_dates=[], slot_data=slot_data)
        result = compute_auto_source(AutoSourceType.CHECKPOINT_MAX, inp)
        assert result == {"d1": 8.0, "d2": 3.0}

    def test_no_slot_data(self) -> None:
        inp = AutoSourceInput(all_dates=[])
        result = compute_auto_source(AutoSourceType.CHECKPOINT_MAX, inp)
        assert result == {}


class TestCheckpointMin(unittest.TestCase):
    def test_min_across_slots(self) -> None:
        slot_data = [
            {"d1": 5.0, "d2": 3.0},
            {"d1": 8.0, "d2": 1.0},
        ]
        inp = AutoSourceInput(all_dates=[], slot_data=slot_data)
        result = compute_auto_source(AutoSourceType.CHECKPOINT_MIN, inp)
        assert result == {"d1": 5.0, "d2": 1.0}


class TestRollingAvg(unittest.TestCase):
    def test_window_3(self) -> None:
        parent = {"2025-01-01": 3.0, "2025-01-02": 6.0, "2025-01-03": 9.0, "2025-01-04": 12.0}
        inp = AutoSourceInput(all_dates=[], parent_data=parent, option_id=3)
        result = compute_auto_source(AutoSourceType.ROLLING_AVG, inp)
        assert "2025-01-03" in result
        assert abs(result["2025-01-03"] - 6.0) < 0.01  # (3+6+9)/3

    def test_no_parent(self) -> None:
        inp = AutoSourceInput(all_dates=[], option_id=7)
        result = compute_auto_source(AutoSourceType.ROLLING_AVG, inp)
        assert result == {}

    def test_no_window(self) -> None:
        inp = AutoSourceInput(all_dates=[], parent_data={"d1": 1.0})
        result = compute_auto_source(AutoSourceType.ROLLING_AVG, inp)
        assert result == {}


class TestStreakTrue(unittest.TestCase):
    def test_consecutive_true(self) -> None:
        dates = ["d1", "d2", "d3", "d4"]
        parent = {"d1": 1.0, "d2": 1.0, "d3": 0.0, "d4": 1.0}
        inp = AutoSourceInput(all_dates=dates, parent_data=parent)
        result = compute_auto_source(AutoSourceType.STREAK_TRUE, inp)
        assert result == {"d1": 1.0, "d2": 2.0, "d3": 0.0, "d4": 1.0}

    def test_no_parent(self) -> None:
        inp = AutoSourceInput(all_dates=["d1"])
        result = compute_auto_source(AutoSourceType.STREAK_TRUE, inp)
        assert result == {}


class TestStreakFalse(unittest.TestCase):
    def test_consecutive_false(self) -> None:
        dates = ["d1", "d2", "d3"]
        parent = {"d1": 0.0, "d2": 0.0, "d3": 1.0}
        inp = AutoSourceInput(all_dates=dates, parent_data=parent)
        result = compute_auto_source(AutoSourceType.STREAK_FALSE, inp)
        assert result == {"d1": 1.0, "d2": 2.0, "d3": 0.0}


class TestNoteCount(unittest.TestCase):
    def test_passthrough(self) -> None:
        """NOTE_COUNT expects pre-fetched data as parent_data."""
        inp = AutoSourceInput(all_dates=[], parent_data={"d1": 3.0, "d2": 1.0})
        result = compute_auto_source(AutoSourceType.NOTE_COUNT, inp)
        assert result == {"d1": 3.0, "d2": 1.0}

    def test_none(self) -> None:
        inp = AutoSourceInput(all_dates=[])
        result = compute_auto_source(AutoSourceType.NOTE_COUNT, inp)
        assert result == {}


class TestAWActive(unittest.TestCase):
    def test_passthrough(self) -> None:
        """AW_ACTIVE expects pre-fetched data as parent_data."""
        inp = AutoSourceInput(all_dates=[], parent_data={"d1": 5.5})
        result = compute_auto_source(AutoSourceType.AW_ACTIVE, inp)
        assert result == {"d1": 5.5}


class TestWeekNumber(unittest.TestCase):
    def test_deprecated_returns_empty(self) -> None:
        inp = AutoSourceInput(all_dates=["2025-01-06"])
        result = compute_auto_source(AutoSourceType.WEEK_NUMBER, inp)
        assert result == {}
