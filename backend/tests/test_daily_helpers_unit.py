"""Unit tests for daily_helpers.evaluate_condition."""

import unittest

from app.services.daily_helpers import evaluate_condition


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
