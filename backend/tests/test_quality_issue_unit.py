"""Unit tests for quality issue functions in analytics router.

Tests: _confidence_interval, _determine_quality_issue, QualityIssue,
       QUALITY_ISSUE_LABELS, QUALITY_SEVERITY,
       _build_contingency_table, _fisher_exact_p.
"""
from __future__ import annotations

from app.routers.analytics import (
    QualityIssue,
    QUALITY_ISSUE_LABELS,
    QUALITY_SEVERITY,
    _build_contingency_table,
    _confidence_interval,
    _determine_quality_issue,
    _fisher_exact_p,
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

    def test_fisher_high_p(self) -> None:
        result = _determine_quality_issue(n=30, p_value=0.01, fisher_high_p=True)
        assert result == "fisher_exact_high_p"

    def test_high_p_value_beats_fisher(self) -> None:
        """high_p_value has higher priority than fisher_exact_high_p."""
        result = _determine_quality_issue(n=30, p_value=0.10, fisher_high_p=True)
        assert result == "high_p_value"

    def test_fisher_beats_wide_ci(self) -> None:
        """fisher_exact_high_p has higher priority than wide_ci."""
        result = _determine_quality_issue(n=30, p_value=0.01, fisher_high_p=True, wide_ci=True)
        assert result == "fisher_exact_high_p"

    def test_fisher_only_when_set(self) -> None:
        """fisher_high_p=False should not trigger the issue."""
        result = _determine_quality_issue(n=30, p_value=0.01, fisher_high_p=False)
        assert result is None

    def test_low_streak_resets_detected(self) -> None:
        result = _determine_quality_issue(n=30, p_value=0.01, low_streak_resets=True)
        assert result == "low_streak_resets"

    def test_low_streak_resets_disabled(self) -> None:
        """When filter is disabled via config, issue should not be returned."""
        from unittest.mock import patch, PropertyMock
        from app.correlation_config import QualityFiltersConfig
        disabled = QualityFiltersConfig(low_streak_resets=False)
        with patch("app.routers.analytics.correlation_config") as mock_cfg:
            type(mock_cfg).quality_filters = PropertyMock(return_value=disabled)
            result = _determine_quality_issue(n=30, p_value=0.01, low_streak_resets=True)
        assert result is None

    def test_low_streak_resets_priority_over_variance(self) -> None:
        """low_streak_resets has higher priority than insufficient_variance."""
        result = _determine_quality_issue(
            n=30, p_value=0.01, low_variance=True, low_streak_resets=True,
        )
        assert result == "low_streak_resets"

    def test_low_data_points_priority_over_streak(self) -> None:
        """low_data_points has higher priority than low_streak_resets."""
        result = _determine_quality_issue(n=5, p_value=0.01, low_streak_resets=True)
        assert result == "low_data_points"


# ---------------------------------------------------------------------------
# _build_contingency_table
# ---------------------------------------------------------------------------

class TestBuildContingencyTable:

    def test_perfect_overlap(self) -> None:
        """Both True on same days, both False on same days."""
        a = {"d1": 1.0, "d2": 1.0, "d3": 0.0, "d4": 0.0}
        b = {"d1": 1.0, "d2": 1.0, "d3": 0.0, "d4": 0.0}
        ct_a, ct_b, ct_c, ct_d, n = _build_contingency_table(a, b)
        assert (ct_a, ct_b, ct_c, ct_d, n) == (2, 0, 0, 2, 4)

    def test_no_overlap(self) -> None:
        """A True when B False and vice versa."""
        a = {"d1": 1.0, "d2": 1.0, "d3": 0.0, "d4": 0.0}
        b = {"d1": 0.0, "d2": 0.0, "d3": 1.0, "d4": 1.0}
        ct_a, ct_b, ct_c, ct_d, n = _build_contingency_table(a, b)
        assert (ct_a, ct_b, ct_c, ct_d, n) == (0, 2, 2, 0, 4)

    def test_only_common_dates(self) -> None:
        """Dates not in both dicts are ignored."""
        a = {"d1": 1.0, "d2": 0.0, "d3": 1.0}
        b = {"d1": 1.0, "d2": 0.0, "d5": 1.0}
        ct_a, ct_b, ct_c, ct_d, n = _build_contingency_table(a, b)
        assert n == 2  # only d1 and d2 are common
        assert (ct_a, ct_b, ct_c, ct_d) == (1, 0, 0, 1)

    def test_empty_data(self) -> None:
        ct_a, ct_b, ct_c, ct_d, n = _build_contingency_table({}, {})
        assert n == 0

    def test_threshold_at_05(self) -> None:
        """Values >= 0.5 count as True."""
        a = {"d1": 0.5, "d2": 0.4}
        b = {"d1": 0.5, "d2": 0.4}
        ct_a, ct_b, ct_c, ct_d, n = _build_contingency_table(a, b)
        assert (ct_a, ct_b, ct_c, ct_d) == (1, 0, 0, 1)


# ---------------------------------------------------------------------------
# _fisher_exact_p
# ---------------------------------------------------------------------------

class TestFisherExactP:

    def test_single_coincidence_high_p(self) -> None:
        """1 coincidence out of 10 days — should be p >= 0.05 (random)."""
        a: dict[str, float] = {}
        b: dict[str, float] = {}
        for i in range(1, 11):
            d = f"2026-01-{i:02d}"
            a[d] = 1.0 if i == 1 else 0.0
            b[d] = 1.0 if i == 1 else 0.0
        p = _fisher_exact_p(a, b)
        assert p >= 0.05

    def test_empty_data_returns_1(self) -> None:
        assert _fisher_exact_p({}, {}) == 1.0

    def test_all_same_degenerate(self) -> None:
        """All True — one marginal is 0, table is degenerate."""
        data = {f"d{i}": 1.0 for i in range(10)}
        p = _fisher_exact_p(data, data)
        assert p == 1.0

    def test_all_false_degenerate(self) -> None:
        """All False — also degenerate."""
        data = {f"d{i}": 0.0 for i in range(10)}
        p = _fisher_exact_p(data, data)
        assert p == 1.0

    def test_strong_association_low_p(self) -> None:
        """Strong association: both True on same 10 days, both False on other 10."""
        a: dict[str, float] = {}
        b: dict[str, float] = {}
        for i in range(1, 21):
            d = f"d{i}"
            val = 1.0 if i <= 10 else 0.0
            a[d] = val
            b[d] = val
        p = _fisher_exact_p(a, b)
        assert p < 0.01

    def test_p_between_0_and_1(self) -> None:
        """P-value is always in [0, 1]."""
        a = {f"d{i}": 1.0 if i % 3 == 0 else 0.0 for i in range(1, 16)}
        b = {f"d{i}": 1.0 if i % 4 == 0 else 0.0 for i in range(1, 16)}
        p = _fisher_exact_p(a, b)
        assert 0.0 <= p <= 1.0


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

    def test_fisher_exact_high_p_is_maybe(self) -> None:
        assert QUALITY_SEVERITY[QualityIssue.FISHER_EXACT_HIGH_P] == "maybe"

    def test_others_are_bad(self) -> None:
        _MAYBE_ISSUES = {QualityIssue.WIDE_CI, QualityIssue.FISHER_EXACT_HIGH_P}
        for issue in QualityIssue:
            if issue not in _MAYBE_ISSUES:
                assert QUALITY_SEVERITY[issue] == "bad", f"{issue} should be 'bad'"
