"""Unit tests for quality issue functions in analytics router.

Tests: _confidence_interval, _determine_quality_issue, QualityIssue,
       QUALITY_ISSUE_LABELS, QUALITY_SEVERITY.
"""
from __future__ import annotations

from app.routers.analytics import (
    QualityIssue,
    QUALITY_ISSUE_LABELS,
    QUALITY_SEVERITY,
    _confidence_interval,
    _determine_quality_issue,
)


# ---------------------------------------------------------------------------
# _confidence_interval
# ---------------------------------------------------------------------------

class TestConfidenceInterval:

    def test_n_less_than_4_returns_none(self) -> None:
        assert _confidence_interval(0.5, 3) is None

    def test_returns_tuple_for_valid_n(self) -> None:
        result = _confidence_interval(0.5, 30)
        assert result is not None
        lo, hi = result
        assert lo < 0.5 < hi

    def test_perfect_correlation(self) -> None:
        result = _confidence_interval(1.0, 10)
        assert result is not None
        assert result == (1.0, 1.0)

    def test_zero_correlation_symmetric(self) -> None:
        result = _confidence_interval(0.0, 30)
        assert result is not None
        lo, hi = result
        assert abs(lo + hi) < 1e-6

    def test_ci_narrows_with_more_data(self) -> None:
        ci_10 = _confidence_interval(0.5, 10)
        ci_100 = _confidence_interval(0.5, 100)
        assert ci_10 is not None and ci_100 is not None
        width_10 = ci_10[1] - ci_10[0]
        width_100 = ci_100[1] - ci_100[0]
        assert width_10 > width_100


# ---------------------------------------------------------------------------
# _determine_quality_issue
# ---------------------------------------------------------------------------

class TestDetermineQualityIssue:

    def test_all_good_returns_none(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.01) is None

    def test_low_data_points_priority(self) -> None:
        assert _determine_quality_issue(n=5, p_value=0.01) == "low_data_points"

    def test_insufficient_variance(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.01, low_variance=True) == "insufficient_variance"

    def test_high_p_value(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.10) == "high_p_value"

    def test_wide_ci(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.01, wide_ci=True) == "wide_ci"

    def test_p_boundary_at_005(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.05) == "high_p_value"

    def test_p_boundary_below_005(self) -> None:
        assert _determine_quality_issue(n=30, p_value=0.049) is None

    def test_priority_order_low_data_wins(self) -> None:
        """n < 10 has higher priority than low_variance."""
        result = _determine_quality_issue(n=5, p_value=0.10, low_variance=True)
        assert result == "low_data_points"

    def test_low_binary_data_points(self) -> None:
        result = _determine_quality_issue(n=15, p_value=0.01, small_binary_group=True)
        assert result == "low_binary_data_points"

    def test_small_binary_group_beats_low_variance(self) -> None:
        result = _determine_quality_issue(n=15, p_value=0.01, low_variance=True, small_binary_group=True)
        assert result == "low_binary_data_points"

    def test_low_data_points_beats_small_binary_group(self) -> None:
        result = _determine_quality_issue(n=5, p_value=0.01, small_binary_group=True)
        assert result == "low_data_points"

    def test_small_binary_group_beats_high_p_value(self) -> None:
        result = _determine_quality_issue(n=15, p_value=0.10, small_binary_group=True)
        assert result == "low_binary_data_points"


# ---------------------------------------------------------------------------
# QualityIssue mappings
# ---------------------------------------------------------------------------

class TestQualityIssueMappings:

    def test_all_values_have_labels(self) -> None:
        for issue in QualityIssue:
            assert issue.value in QUALITY_ISSUE_LABELS, f"Missing label for {issue}"

    def test_all_values_have_severity(self) -> None:
        for issue in QualityIssue:
            assert issue.value in QUALITY_SEVERITY, f"Missing severity for {issue}"

    def test_wide_ci_is_maybe(self) -> None:
        assert QUALITY_SEVERITY[QualityIssue.WIDE_CI] == "maybe"

    def test_others_are_bad(self) -> None:
        for issue in QualityIssue:
            if issue != QualityIssue.WIDE_CI:
                assert QUALITY_SEVERITY[issue] == "bad", f"{issue} should be 'bad'"
