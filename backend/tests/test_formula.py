"""Unit tests for app.formula module."""

import pytest

from app.formula import (
    _format_result,
    convert_metric_value,
    evaluate_formula,
    get_referenced_metric_ids,
    validate_formula,
)


class TestGetReferencedMetricIds:
    def test_empty_list(self) -> None:
        assert get_referenced_metric_ids([]) == []

    def test_no_metric_tokens(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 2},
        ]
        assert get_referenced_metric_ids(tokens) == []

    def test_multiple_metrics(self) -> None:
        tokens = [
            {"type": "metric", "id": 3},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 7},
            {"type": "op", "value": "*"},
            {"type": "metric", "id": 11},
        ]
        assert get_referenced_metric_ids(tokens) == [3, 7, 11]


class TestValidateFormula:
    def test_empty_tokens(self) -> None:
        assert validate_formula([], {}) == "Формула пуста"

    def test_extra_closing_paren(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "rparen"},
        ]
        assert validate_formula(tokens, {}) == "Лишняя закрывающая скобка"

    def test_unclosed_paren(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "number", "value": 1},
        ]
        assert validate_formula(tokens, {}) == "Незакрытая скобка"

    def test_comparison_inside_parens(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "metric", "id": 1},
            {"type": "op", "value": ">"},
            {"type": "number", "value": 5},
            {"type": "rparen"},
        ]
        source_metrics = {1: "number"}
        assert validate_formula(tokens, source_metrics) == (
            "Оператор сравнения нельзя использовать внутри скобок"
        )

    def test_more_than_one_comparison(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": ">"},
            {"type": "metric", "id": 2},
            {"type": "op", "value": "<"},
            {"type": "number", "value": 10},
        ]
        source_metrics = {1: "number", 2: "number"}
        assert validate_formula(tokens, source_metrics) == (
            "В формуле допустимо не более одного оператора сравнения"
        )

    def test_unknown_metric_id(self) -> None:
        tokens = [{"type": "metric", "id": 99}]
        assert validate_formula(tokens, {}) == "Метрика с id=99 не найдена"

    def test_computed_metric_ref(self) -> None:
        tokens = [{"type": "metric", "id": 5}]
        source_metrics = {5: "computed"}
        assert validate_formula(tokens, source_metrics) == (
            "Нельзя ссылаться на другие вычисляемые метрики"
        )

    def test_time_plus_numeric_mix(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 2},
        ]
        source_metrics = {1: "time", 2: "number"}
        assert validate_formula(tokens, source_metrics) == (
            "Нельзя смешивать время с числовыми типами в одной формуле"
        )

    def test_time_with_multiply_operator(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "*"},
            {"type": "metric", "id": 2},
        ]
        source_metrics = {1: "time", 2: "duration"}
        assert validate_formula(tokens, source_metrics) == (
            "Для времени допустимы только +, −, > и <"
        )

    def test_time_with_divide_operator(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "/"},
            {"type": "metric", "id": 2},
        ]
        source_metrics = {1: "time", 2: "duration"}
        assert validate_formula(tokens, source_metrics) == (
            "Для времени допустимы только +, −, > и <"
        )

    def test_time_with_number_constant(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 5},
        ]
        source_metrics = {1: "time"}
        assert validate_formula(tokens, source_metrics) == (
            "Нельзя использовать числовые константы в формуле с временем"
        )

    def test_operator_at_start(self) -> None:
        tokens = [
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
        ]
        assert validate_formula(tokens, {}) == "Оператор в неожиданной позиции"

    def test_operator_after_operator(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "op", "value": "+"},
            {"type": "op", "value": "-"},
            {"type": "number", "value": 2},
        ]
        assert validate_formula(tokens, {}) == "Оператор в неожиданной позиции"

    def test_operator_after_lparen(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 1},
            {"type": "rparen"},
        ]
        assert validate_formula(tokens, {}) == "Оператор в неожиданной позиции"

    def test_two_values_without_operator(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "number", "value": 2},
        ]
        assert validate_formula(tokens, {}) == "Два значения подряд без оператора"

    def test_metric_after_number(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "metric", "id": 5},
        ]
        source_metrics = {5: "number"}
        assert validate_formula(tokens, source_metrics) == (
            "Два значения подряд без оператора"
        )

    def test_lparen_after_value(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "lparen"},
            {"type": "number", "value": 2},
            {"type": "rparen"},
        ]
        assert validate_formula(tokens, {}) == "Скобка после значения без оператора"

    def test_rparen_after_operator(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "number", "value": 1},
            {"type": "op", "value": "+"},
            {"type": "rparen"},
        ]
        assert validate_formula(tokens, {}) == (
            "Закрывающая скобка в неожиданной позиции"
        )

    def test_rparen_after_lparen(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "rparen"},
        ]
        assert validate_formula(tokens, {}) == (
            "Закрывающая скобка в неожиданной позиции"
        )

    def test_ends_with_operator(self) -> None:
        tokens = [
            {"type": "number", "value": 1},
            {"type": "op", "value": "+"},
        ]
        assert validate_formula(tokens, {}) == (
            "Формула не может заканчиваться оператором или открывающей скобкой"
        )

    def test_ends_with_lparen(self) -> None:
        # Unbalanced paren check fires before sequence check
        tokens = [
            {"type": "number", "value": 1},
            {"type": "op", "value": "+"},
            {"type": "lparen"},
        ]
        assert validate_formula(tokens, {}) == "Незакрытая скобка"

    def test_valid_formula_returns_none(self) -> None:
        tokens = [
            {"type": "lparen"},
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 2},
            {"type": "rparen"},
            {"type": "op", "value": "*"},
            {"type": "number", "value": 10},
        ]
        source_metrics = {1: "number", 2: "number"}
        assert validate_formula(tokens, source_metrics) is None

    def test_valid_time_formula_with_duration(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 2},
        ]
        source_metrics = {1: "time", 2: "duration"}
        assert validate_formula(tokens, source_metrics) is None

    def test_valid_comparison_formula(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": ">"},
            {"type": "number", "value": 5},
        ]
        source_metrics = {1: "number"}
        assert validate_formula(tokens, source_metrics) is None


class TestConvertMetricValue:
    def test_none_input(self) -> None:
        assert convert_metric_value(None, "number") is None

    def test_bool_true(self) -> None:
        assert convert_metric_value(True, "bool") == 1.0

    def test_bool_false(self) -> None:
        assert convert_metric_value(False, "bool") == 0.0

    def test_number(self) -> None:
        assert convert_metric_value(42, "number") == 42.0

    def test_scale_with_min_max(self) -> None:
        # value=3, min=1, max=5 -> (3-1)/(5-1) = 0.5
        result = convert_metric_value(3, "scale", scale_min=1, scale_max=5)
        assert result == pytest.approx(0.5)

    def test_scale_default_min_max(self) -> None:
        # No min/max provided -> defaults 1.0, 5.0
        # value=3 -> (3-1)/(5-1) = 0.5
        result = convert_metric_value(3, "scale")
        assert result == pytest.approx(0.5)

    def test_scale_equal_min_max(self) -> None:
        result = convert_metric_value(5, "scale", scale_min=5, scale_max=5)
        assert result == 0.0

    def test_duration(self) -> None:
        assert convert_metric_value(120, "duration") == 120.0

    def test_time_hhmm(self) -> None:
        # "08:30" -> 8*60 + 30 = 510
        assert convert_metric_value("08:30", "time") == 510.0

    def test_time_non_string(self) -> None:
        assert convert_metric_value(123, "time") is None

    def test_unknown_type(self) -> None:
        assert convert_metric_value(42, "text") is None


class TestEvaluateFormula:
    def test_empty_tokens(self) -> None:
        assert evaluate_formula([], {}, "float") is None

    def test_simple_addition(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 2},
        ]
        values = {1: 3.0, 2: 7.0}
        assert evaluate_formula(tokens, values, "float") == pytest.approx(10.0)

    def test_operator_precedence_mul_before_add(self) -> None:
        # 2 + 3 * 4 = 2 + 12 = 14
        tokens = [
            {"type": "number", "value": 2},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 3},
            {"type": "op", "value": "*"},
            {"type": "number", "value": 4},
        ]
        assert evaluate_formula(tokens, {}, "float") == pytest.approx(14.0)

    def test_parentheses_override_precedence(self) -> None:
        # (2 + 3) * 4 = 20
        tokens = [
            {"type": "lparen"},
            {"type": "number", "value": 2},
            {"type": "op", "value": "+"},
            {"type": "number", "value": 3},
            {"type": "rparen"},
            {"type": "op", "value": "*"},
            {"type": "number", "value": 4},
        ]
        assert evaluate_formula(tokens, {}, "float") == pytest.approx(20.0)

    def test_division_by_zero_returns_none(self) -> None:
        tokens = [
            {"type": "number", "value": 10},
            {"type": "op", "value": "/"},
            {"type": "number", "value": 0},
        ]
        assert evaluate_formula(tokens, {}, "float") is None

    def test_missing_metric_value_returns_none(self) -> None:
        tokens = [
            {"type": "metric", "id": 1},
            {"type": "op", "value": "+"},
            {"type": "metric", "id": 2},
        ]
        values = {1: 5.0}  # metric 2 missing
        assert evaluate_formula(tokens, values, "float") is None

    def test_metric_value_none_returns_none(self) -> None:
        tokens = [{"type": "metric", "id": 1}]
        values = {1: None}
        assert evaluate_formula(tokens, values, "float") is None

    def test_comparison_greater(self) -> None:
        # 10 > 5 -> 1.0 -> True (as bool)
        tokens = [
            {"type": "number", "value": 10},
            {"type": "op", "value": ">"},
            {"type": "number", "value": 5},
        ]
        assert evaluate_formula(tokens, {}, "bool") is True

    def test_comparison_greater_false(self) -> None:
        # 3 > 5 -> 0.0 -> False (as bool)
        tokens = [
            {"type": "number", "value": 3},
            {"type": "op", "value": ">"},
            {"type": "number", "value": 5},
        ]
        assert evaluate_formula(tokens, {}, "bool") is False

    def test_comparison_less(self) -> None:
        # 3 < 5 -> 1.0 -> True
        tokens = [
            {"type": "number", "value": 3},
            {"type": "op", "value": "<"},
            {"type": "number", "value": 5},
        ]
        assert evaluate_formula(tokens, {}, "bool") is True

    def test_subtraction(self) -> None:
        tokens = [
            {"type": "number", "value": 10},
            {"type": "op", "value": "-"},
            {"type": "number", "value": 3},
        ]
        assert evaluate_formula(tokens, {}, "int") == 7

    def test_division(self) -> None:
        tokens = [
            {"type": "number", "value": 10},
            {"type": "op", "value": "/"},
            {"type": "number", "value": 4},
        ]
        assert evaluate_formula(tokens, {}, "float") == pytest.approx(2.5)


class TestFormatResult:
    def test_bool_positive(self) -> None:
        assert _format_result(5.0, "bool") is True

    def test_bool_zero(self) -> None:
        assert _format_result(0.0, "bool") is False

    def test_bool_negative(self) -> None:
        assert _format_result(-1.0, "bool") is False

    def test_int_rounding(self) -> None:
        assert _format_result(3.7, "int") == 4

    def test_int_rounding_down(self) -> None:
        assert _format_result(3.2, "int") == 3

    def test_float_rounding(self) -> None:
        assert _format_result(3.14159265, "float") == pytest.approx(3.1416)

    def test_time_normal(self) -> None:
        # 510 minutes = 8h 30m -> "08:30"
        assert _format_result(510.0, "time") == "08:30"

    def test_time_midnight(self) -> None:
        assert _format_result(0.0, "time") == "00:00"

    def test_time_overflow_wraps(self) -> None:
        # 1500 minutes = 1500 % 1440 = 60 -> "01:00"
        assert _format_result(1500.0, "time") == "01:00"

    def test_time_negative_wraps(self) -> None:
        # int(-60) % 1440 = -60; -60 < 0 -> -60 + 1440 = 1380 -> 23:00
        assert _format_result(-60.0, "time") == "23:00"

    def test_duration_normal(self) -> None:
        # 150 minutes = 2h 30m
        assert _format_result(150.0, "duration") == "2ч 30м"

    def test_duration_zero(self) -> None:
        assert _format_result(0.0, "duration") == "0ч 0м"

    def test_duration_negative_clamps_to_zero(self) -> None:
        # max(0, ...) clamps negative to 0
        assert _format_result(-30.0, "duration") == "0ч 0м"

    def test_unknown_type_returns_float(self) -> None:
        assert _format_result(3.14159, "unknown") == pytest.approx(3.1416)
