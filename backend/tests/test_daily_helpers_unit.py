"""Unit tests for daily_helpers — evaluate_condition, extract_dep_value_for_interval, evaluate_visibility, split_by_checkpoints."""

import unittest

from app.services.daily_helpers import (
    evaluate_condition,
    extract_dep_value_for_interval,
    evaluate_visibility,
    split_by_checkpoints,
)


class TestEvaluateConditionFilled(unittest.TestCase):
    def test_filled_with_value(self) -> None:
        assert evaluate_condition({"type": "filled"}, True) is True

    def test_filled_with_list(self) -> None:
        assert evaluate_condition({"type": "filled"}, [1, 2]) is True

    def test_filled_with_empty_list(self) -> None:
        # "Ничего" (пустой массив) тоже считается заполненным
        assert evaluate_condition({"type": "filled"}, []) is True

    def test_filled_with_none(self) -> None:
        assert evaluate_condition({"type": "filled"}, None) is False


class TestEvaluateConditionNoneSelected(unittest.TestCase):
    def test_empty_list(self) -> None:
        assert evaluate_condition({"type": "none_selected"}, []) is True

    def test_non_empty_list(self) -> None:
        assert evaluate_condition({"type": "none_selected"}, [1, 2]) is False

    def test_single_element_list(self) -> None:
        assert evaluate_condition({"type": "none_selected"}, [5]) is False

    def test_none(self) -> None:
        assert evaluate_condition({"type": "none_selected"}, None) is False

    def test_non_list_value(self) -> None:
        assert evaluate_condition({"type": "none_selected"}, 0) is False


class TestEvaluateConditionAnySelected(unittest.TestCase):
    def test_non_empty_list(self) -> None:
        assert evaluate_condition({"type": "any_selected"}, [1, 2]) is True

    def test_single_element_list(self) -> None:
        assert evaluate_condition({"type": "any_selected"}, [5]) is True

    def test_empty_list(self) -> None:
        assert evaluate_condition({"type": "any_selected"}, []) is False

    def test_none(self) -> None:
        assert evaluate_condition({"type": "any_selected"}, None) is False

    def test_non_list_value(self) -> None:
        assert evaluate_condition({"type": "any_selected"}, 1) is False


class TestEvaluateConditionEquals(unittest.TestCase):
    def test_bool_true(self) -> None:
        assert evaluate_condition({"type": "equals", "value": True}, True) is True

    def test_bool_false(self) -> None:
        assert evaluate_condition({"type": "equals", "value": True}, False) is False

    def test_enum_single_match(self) -> None:
        assert evaluate_condition({"type": "equals", "value": [2]}, [1, 2]) is True

    def test_enum_no_match(self) -> None:
        assert evaluate_condition({"type": "equals", "value": [3]}, [1, 2]) is False


class TestEvaluateConditionNotEquals(unittest.TestCase):
    def test_bool_differs(self) -> None:
        assert evaluate_condition({"type": "not_equals", "value": True}, False) is True

    def test_bool_same(self) -> None:
        assert evaluate_condition({"type": "not_equals", "value": True}, True) is False

    def test_enum_not_in_list(self) -> None:
        assert evaluate_condition({"type": "not_equals", "value": [3]}, [1, 2]) is True

    def test_enum_in_list(self) -> None:
        assert evaluate_condition({"type": "not_equals", "value": [2]}, [1, 2]) is False


def _iv(interval_id: int, value=None) -> dict:
    """Helper: build an interval sub-item."""
    entry = {"id": 1, "value": value, "recorded_at": "2024-01-01"} if value is not None else None
    return {"interval_id": interval_id, "label": f"iv{interval_id}", "entry": entry}


def _dep(entry_value=None, intervals: list | None = None) -> dict:
    """Helper: build a dep item."""
    entry = {"id": 1, "value": entry_value, "recorded_at": "2024-01-01"} if entry_value is not None else None
    return {"metric_id": 99, "type": "bool", "entry": entry, "intervals": intervals, "checkpoints": None}


class TestExtractDepValueForInterval(unittest.TestCase):
    def test_no_intervals_returns_global_entry(self) -> None:
        dep = _dep(entry_value=5)
        assert extract_dep_value_for_interval(dep, 1) == 5

    def test_no_intervals_no_entry_returns_none(self) -> None:
        dep = _dep()
        assert extract_dep_value_for_interval(dep, 1) is None

    def test_matching_interval_with_entry(self) -> None:
        dep = _dep(intervals=[_iv(1, 42), _iv(2, 7)])
        assert extract_dep_value_for_interval(dep, 1) == 42

    def test_matching_interval_second(self) -> None:
        dep = _dep(intervals=[_iv(1, 42), _iv(2, 7)])
        assert extract_dep_value_for_interval(dep, 2) == 7

    def test_matching_interval_no_entry_returns_none(self) -> None:
        # iv_id=1 found but has no entry → None, not fallback
        dep = _dep(intervals=[_iv(1), _iv(2, 7)])
        assert extract_dep_value_for_interval(dep, 1) is None

    def test_no_matching_interval_fallback_to_first_nonempty(self) -> None:
        dep = _dep(intervals=[_iv(1), _iv(2, 7)])
        assert extract_dep_value_for_interval(dep, 99) == 7

    def test_no_matching_interval_all_empty_returns_none(self) -> None:
        dep = _dep(intervals=[_iv(1), _iv(2)])
        assert extract_dep_value_for_interval(dep, 99) is None


def _item(metric_id: int, cond: dict | None = None, intervals: list | None = None, entry_value=None) -> dict:
    """Helper: build a daily result item."""
    entry = {"id": 1, "value": entry_value} if entry_value is not None else None
    return {
        "metric_id": metric_id,
        "type": "bool",
        "entry": entry,
        "intervals": intervals,
        "checkpoints": None,
        "condition": cond,
    }


class TestEvaluateVisibilityPerInterval(unittest.TestCase):
    def test_both_have_intervals_per_iv_dict_set(self) -> None:
        cond = {"type": "equals", "value": True, "depends_on_metric_id": 2}
        dep = _item(2, intervals=[_iv(1, True), _iv(2, False)])
        item = _item(1, cond=cond, intervals=[_iv(1), _iv(2)])
        evaluate_visibility([item, dep])
        assert item["_interval_condition_met"] == {1: True, 2: False}
        assert item["condition_met"] is True  # any()

    def test_both_have_intervals_all_false(self) -> None:
        cond = {"type": "equals", "value": True, "depends_on_metric_id": 2}
        dep = _item(2, intervals=[_iv(1, False), _iv(2, False)])
        item = _item(1, cond=cond, intervals=[_iv(1), _iv(2)])
        evaluate_visibility([item, dep])
        assert item["_interval_condition_met"] == {1: False, 2: False}
        assert item["condition_met"] is False

    def test_item_intervals_dep_no_intervals(self) -> None:
        # dep has a single entry → same value for all item intervals
        cond = {"type": "filled", "depends_on_metric_id": 2}
        dep = _item(2, entry_value=True)
        item = _item(1, cond=cond, intervals=[_iv(1), _iv(2)])
        evaluate_visibility([item, dep])
        assert "_interval_condition_met" not in item
        assert item["condition_met"] is True

    def test_no_condition_always_true(self) -> None:
        item = _item(1, intervals=[_iv(1)])
        evaluate_visibility([item])
        assert item["condition_met"] is True
        assert "_interval_condition_met" not in item

    def test_dep_not_found_always_true(self) -> None:
        cond = {"type": "filled", "depends_on_metric_id": 999}
        item = _item(1, cond=cond, intervals=[_iv(1)])
        evaluate_visibility([item])
        assert item["condition_met"] is True


class TestSplitByCheckpointsPerIntervalCondition(unittest.TestCase):
    def _make_active_intervals(self) -> list:
        return [
            {"id": 1, "label": "A→B", "start_checkpoint_id": 10, "end_checkpoint_id": 11, "start_sort_order": 0},
            {"id": 2, "label": "B→C", "start_checkpoint_id": 11, "end_checkpoint_id": 12, "start_sort_order": 1},
        ]

    def _make_checkpoints(self) -> list:
        return [
            {"id": 10, "label": "A", "sort_order": 0},
            {"id": 11, "label": "B", "sort_order": 1},
            {"id": 12, "label": "C", "sort_order": 2},
        ]

    def test_per_interval_condition_met_applied(self) -> None:
        item = {
            "metric_id": 1, "type": "bool", "entry": None, "checkpoints": None,
            "condition": {"type": "filled", "depends_on_metric_id": 2},
            "condition_met": True,
            "_interval_condition_met": {1: True, 2: False},
            "intervals": [_iv(1), _iv(2)],
            "category_id": None,
        }
        result = split_by_checkpoints(
            [item],
            all_user_checkpoints=self._make_checkpoints(),
            active_intervals=self._make_active_intervals(),
        )
        assert len(result) == 2
        iv1_split = next(s for s in result if s["block_id"] == 1)
        iv2_split = next(s for s in result if s["block_id"] == 2)
        assert iv1_split["condition_met"] is True
        assert iv2_split["condition_met"] is False
        assert iv1_split["_interval_condition_met"] is None
        assert iv2_split["_interval_condition_met"] is None

    def test_no_per_interval_inherits_scalar(self) -> None:
        item = {
            "metric_id": 1, "type": "bool", "entry": None, "checkpoints": None,
            "condition": {"type": "filled", "depends_on_metric_id": 2},
            "condition_met": False,
            "intervals": [_iv(1), _iv(2)],
            "category_id": None,
        }
        result = split_by_checkpoints(
            [item],
            all_user_checkpoints=self._make_checkpoints(),
            active_intervals=self._make_active_intervals(),
        )
        assert all(s["condition_met"] is False for s in result)
        assert all(s["_interval_condition_met"] is None for s in result)
