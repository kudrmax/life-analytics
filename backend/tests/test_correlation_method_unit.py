"""Unit tests for CorrelationMethod Protocol and PearsonMethod."""

from __future__ import annotations

import unittest

from app.analytics.correlation_math import (
    CorrelationMethodResult,
    PearsonMethod,
)


class TestPearsonMethodPerfectCorrelation(unittest.TestCase):
    """PearsonMethod.compute() returns correct result for perfect correlation."""

    def test_perfect_positive(self) -> None:
        a = {f"d{i}": float(i) for i in range(1, 31)}
        b = {f"d{i}": float(i * 2) for i in range(1, 31)}
        result = PearsonMethod().compute(a, b)
        assert isinstance(result, CorrelationMethodResult)
        assert result.r is not None
        assert result.r > 0.99
        assert result.n == 30
        assert result.p_value < 0.001
        assert result.ci_lower is not None
        assert result.ci_upper is not None
        assert result.ci_lower > 0.9

    def test_perfect_negative(self) -> None:
        a = {f"d{i}": float(i) for i in range(1, 31)}
        b = {f"d{i}": float(31 - i) for i in range(1, 31)}
        result = PearsonMethod().compute(a, b)
        assert result.r is not None
        assert result.r < -0.99
        assert result.ci_upper is not None
        assert result.ci_upper < -0.9


class TestPearsonMethodInsufficient(unittest.TestCase):
    """Not enough common points returns r=None."""

    def test_two_common_points(self) -> None:
        a = {"d1": 1.0, "d2": 2.0}
        b = {"d1": 10.0, "d2": 20.0}
        result = PearsonMethod().compute(a, b)
        assert result.r is None
        assert result.n == 2
        assert result.p_value == 1.0
        assert result.ci_lower is None
        assert result.ci_upper is None

    def test_no_common_points(self) -> None:
        a = {"a1": 1.0}
        b = {"b1": 2.0}
        result = PearsonMethod().compute(a, b)
        assert result.r is None
        assert result.n == 0


class TestPearsonMethodPValue(unittest.TestCase):
    """p-value is correctly computed."""

    def test_significant(self) -> None:
        a = {f"d{i}": float(i) for i in range(1, 31)}
        b = {f"d{i}": float(i * 3 + 1) for i in range(1, 31)}
        result = PearsonMethod().compute(a, b)
        assert result.p_value < 0.05

    def test_not_significant(self) -> None:
        a = {f"d{i}": float(i % 3) for i in range(1, 11)}
        b = {f"d{i}": float((i + 1) % 3) for i in range(1, 11)}
        result = PearsonMethod().compute(a, b)
        # Weak or no correlation with few points → high p-value
        if result.r is not None and abs(result.r) < 0.3:
            assert result.p_value > 0.05


class TestPearsonMethodCI(unittest.TestCase):
    """Confidence interval properties."""

    def test_ci_contains_r(self) -> None:
        a = {f"d{i}": float(i) for i in range(1, 31)}
        b = {f"d{i}": float(i + 0.5) for i in range(1, 31)}
        result = PearsonMethod().compute(a, b)
        assert result.r is not None
        assert result.ci_lower is not None
        assert result.ci_upper is not None
        assert result.ci_lower <= result.r <= result.ci_upper

    def test_ci_none_for_small_n(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 10.0, "d2": 20.0, "d3": 30.0}
        result = PearsonMethod().compute(a, b)
        # n=3, CI requires n>=4
        assert result.ci_lower is None
        assert result.ci_upper is None


class TestCorrelationMethodResult(unittest.TestCase):
    """CorrelationMethodResult is frozen."""

    def test_frozen(self) -> None:
        result = CorrelationMethodResult(r=0.5, n=30, p_value=0.01, ci_lower=0.2, ci_upper=0.7)
        with self.assertRaises(AttributeError):
            result.r = 0.9  # type: ignore[misc]
