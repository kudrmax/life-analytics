"""Unit tests for CorrelationEngine internal logic (no DB)."""
from __future__ import annotations

import unittest
from collections import defaultdict
from datetime import date
from unittest.mock import MagicMock

from app.analytics.correlation_engine import CorrelationEngine, CorrelationPairResult
from app.repositories.analytics_repository import AnalyticsRepository
from app.source_key import AutoSourceType, SourceKey


def _make_engine(**state_overrides: object) -> CorrelationEngine:
    """Create engine with mock conn and manually set internal state."""
    mock_conn = MagicMock()
    mock_repo = MagicMock(spec=AnalyticsRepository)
    mock_repo.conn = mock_conn
    mock_repo.user_id = 1
    engine = CorrelationEngine(
        repo=mock_repo,
        report_id=1,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )
    for key, value in state_overrides.items():
        setattr(engine, f"_{key}", value)
    return engine


# ─── _check_small_binary_group ─────────────────────────────────


class TestCheckSmallBinaryGroup(unittest.TestCase):
    def test_neither_binary_returns_false(self) -> None:
        engine = _make_engine(binary_sources=set())
        data_a = {"d1": 5.0, "d2": 10.0}
        data_b = {"d1": 3.0, "d2": 7.0}
        assert engine._check_small_binary_group(data_a, data_b, 0, 1) is False

    def test_balanced_binary_returns_false(self) -> None:
        engine = _make_engine(binary_sources={0})
        # 10 True, 10 False — balanced, both groups >= 5
        data_a = {f"d{i}": 1.0 if i < 10 else 0.0 for i in range(20)}
        data_b = {f"d{i}": float(i) for i in range(20)}
        assert engine._check_small_binary_group(data_a, data_b, 0, 1) is False

    def test_unbalanced_binary_returns_true(self) -> None:
        engine = _make_engine(binary_sources={0})
        # 2 True, 18 False — min group < 5
        data_a = {f"d{i}": 1.0 if i < 2 else 0.0 for i in range(20)}
        data_b = {f"d{i}": float(i) for i in range(20)}
        assert engine._check_small_binary_group(data_a, data_b, 0, 1) is True

    def test_both_binary_one_unbalanced(self) -> None:
        engine = _make_engine(binary_sources={0, 1})
        data_a = {f"d{i}": 1.0 if i < 10 else 0.0 for i in range(20)}  # balanced
        data_b = {f"d{i}": 1.0 if i < 1 else 0.0 for i in range(20)}   # unbalanced
        assert engine._check_small_binary_group(data_a, data_b, 0, 1) is True

    def test_no_common_dates(self) -> None:
        engine = _make_engine(binary_sources={0})
        data_a = {"a1": 1.0, "a2": 0.0}
        data_b = {"b1": 1.0, "b2": 0.0}
        # No common dates — common is empty, min(0, 0) < 5 → True
        assert engine._check_small_binary_group(data_a, data_b, 0, 1) is True


# ─── _check_low_streak_resets ──────────────────────────────────


class TestCheckLowStreakResets(unittest.TestCase):
    def test_neither_streak_returns_false(self) -> None:
        engine = _make_engine(streak_sources=set())
        data_a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        data_b = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        assert engine._check_low_streak_resets(data_a, data_b, 0, 1) is False

    def test_monotonic_streak_no_drops(self) -> None:
        """Streak that only grows — 0 drops → True (< 2 min_resets)."""
        engine = _make_engine(streak_sources={0})
        data_a = {"d1": 1.0, "d2": 2.0, "d3": 3.0, "d4": 4.0, "d5": 5.0}
        data_b = {"d1": 1.0, "d2": 1.0, "d3": 1.0, "d4": 1.0, "d5": 1.0}
        assert engine._check_low_streak_resets(data_a, data_b, 0, 1) is True

    def test_one_drop_returns_true(self) -> None:
        """1 drop < 2 min_resets → True."""
        engine = _make_engine(streak_sources={0})
        data_a = {"d1": 1.0, "d2": 2.0, "d3": 0.0, "d4": 1.0, "d5": 2.0}
        data_b = {"d1": 1.0, "d2": 1.0, "d3": 1.0, "d4": 1.0, "d5": 1.0}
        assert engine._check_low_streak_resets(data_a, data_b, 0, 1) is True

    def test_three_drops_returns_false(self) -> None:
        """3 drops >= 2 min_resets → False."""
        engine = _make_engine(streak_sources={0})
        data_a = {"d1": 2.0, "d2": 0.0, "d3": 3.0, "d4": 1.0, "d5": 4.0, "d6": 0.0}
        data_b = {"d1": 1.0, "d2": 1.0, "d3": 1.0, "d4": 1.0, "d5": 1.0, "d6": 1.0}
        assert engine._check_low_streak_resets(data_a, data_b, 0, 1) is False

    def test_less_than_2_common_dates(self) -> None:
        engine = _make_engine(streak_sources={0})
        data_a = {"d1": 1.0}
        data_b = {"d1": 1.0}
        assert engine._check_low_streak_resets(data_a, data_b, 0, 1) is False


# ─── _eval_single_pair ────────────────────────────────────────


class TestEvalSinglePair(unittest.TestCase):
    def _setup_engine(self, **overrides: object) -> CorrelationEngine:
        defaults = {
            "binary_sources": set(),
            "streak_sources": set(),
            "low_var_sources": set(),
        }
        defaults.update(overrides)
        return _make_engine(**defaults)

    def test_strong_positive_correlation(self) -> None:
        engine = self._setup_engine()
        data_a = {f"2025-01-{i:02d}": float(i) for i in range(1, 31)}
        data_b = {f"2025-01-{i:02d}": float(i * 2) for i in range(1, 31)}
        sk_a = SourceKey(metric_id=1)
        sk_b = SourceKey(metric_id=2)
        result = engine._eval_single_pair(data_a, data_b, sk_a, sk_b, "number", "number", 0, 1, 0, False, False)
        assert isinstance(result, CorrelationPairResult)
        assert result.correlation > 0.99

    def test_not_enough_common_points_returns_none(self) -> None:
        engine = self._setup_engine()
        data_a = {"2025-01-01": 1.0, "2025-01-02": 2.0}
        data_b = {"2025-01-01": 1.0, "2025-01-03": 3.0}
        sk_a = SourceKey(metric_id=1)
        sk_b = SourceKey(metric_id=2)
        result = engine._eval_single_pair(data_a, data_b, sk_a, sk_b, "number", "number", 0, 1, 0, False, False)
        assert result is None

    def test_low_var_produces_quality_issue(self) -> None:
        engine = self._setup_engine()
        data_a = {f"2025-01-{i:02d}": float(i) for i in range(1, 20)}
        data_b = {f"2025-01-{i:02d}": float(i) * 0.001 for i in range(1, 20)}
        sk_a = SourceKey(metric_id=1)
        sk_b = SourceKey(metric_id=2)
        result = engine._eval_single_pair(data_a, data_b, sk_a, sk_b, "number", "number", 0, 1, 0, True, False)
        assert result is not None
        assert result.quality_issue == "insufficient_variance"

    def test_uncorrelated_high_p(self) -> None:
        """Random-like data → high p-value quality issue."""
        engine = self._setup_engine()
        data_a = {f"2025-01-{i:02d}": float(i % 3) for i in range(1, 31)}
        data_b = {f"2025-01-{i:02d}": float((i + 1) % 3) for i in range(1, 31)}
        sk_a = SourceKey(metric_id=1)
        sk_b = SourceKey(metric_id=2)
        result = engine._eval_single_pair(data_a, data_b, sk_a, sk_b, "number", "number", 0, 1, 0, False, False)
        if result is not None:
            if result.p_value >= 0.05:
                assert result.quality_issue == "high_p_value"

    def test_result_dataclass_fields(self) -> None:
        engine = self._setup_engine()
        data_a = {f"2025-01-{i:02d}": float(i) for i in range(1, 31)}
        data_b = {f"2025-01-{i:02d}": float(i * 3) for i in range(1, 31)}
        sk_a = SourceKey(metric_id=1, slot_id=5)
        sk_b = SourceKey(metric_id=2)
        result = engine._eval_single_pair(data_a, data_b, sk_a, sk_b, "number", "scale", 0, 1, 1, False, False)
        assert isinstance(result, CorrelationPairResult)
        assert result.report_id == 1
        assert result.metric_a_id == 1
        assert result.metric_b_id == 2
        assert result.slot_a_id == 5
        assert result.slot_b_id is None
        assert result.type_a == "number"
        assert result.type_b == "scale"
        assert result.lag_days == 1


# ─── _build_sources ───────────────────────────────────────────


class TestBuildSources(unittest.TestCase):
    def _setup_engine(self, metrics_rows: list, slots: dict | None = None,
                      enum_opts: dict | None = None) -> CorrelationEngine:
        engine = _make_engine()
        engine._metrics_rows = metrics_rows
        engine._slots_by_metric = defaultdict(list, slots or {})
        engine._enum_opts_by_metric = defaultdict(list, enum_opts or {})
        return engine

    def test_bool_no_slots(self) -> None:
        engine = self._setup_engine([{"id": 1, "type": "bool", "name": "X"}])
        engine._build_sources()
        assert len(engine._sources) == 1
        sk, mt = engine._sources[0]
        assert sk.metric_id == 1
        assert mt == "bool"

    def test_bool_with_slots(self) -> None:
        engine = self._setup_engine(
            [{"id": 1, "type": "bool", "name": "X"}],
            slots={1: [{"id": 10}, {"id": 11}]},
        )
        engine._build_sources()
        assert len(engine._sources) == 3  # aggregate + 2 slots

    def test_enum_with_options(self) -> None:
        engine = self._setup_engine(
            [{"id": 1, "type": "enum", "name": "X"}],
            enum_opts={1: [{"id": 100}, {"id": 101}]},
        )
        engine._build_sources()
        assert len(engine._sources) == 2
        assert all(mt == "enum_bool" for _, mt in engine._sources)

    def test_computed_metric(self) -> None:
        engine = self._setup_engine([{"id": 1, "type": "computed", "name": "X"}])
        engine._build_sources()
        assert len(engine._sources) == 1
        assert engine._sources[0][1] == "computed"

    def test_text_metric_skipped(self) -> None:
        engine = self._setup_engine([{"id": 1, "type": "text", "name": "X"}])
        engine._build_sources()
        assert len(engine._sources) == 0


# ─── _precompute_quality_flags ─────────────────────────────────


class TestPrecomputeQualityFlags(unittest.TestCase):
    def test_constant_data_is_low_var(self) -> None:
        engine = _make_engine()
        engine._sources = [(SourceKey(metric_id=1), "number")]
        engine._source_data = {0: {"d1": 5.0, "d2": 5.0, "d3": 5.0}}
        engine._precompute_quality_flags()
        assert 0 in engine._low_var_sources

    def test_balanced_binary_is_binary_not_low_var(self) -> None:
        engine = _make_engine()
        engine._sources = [(SourceKey(metric_id=1), "bool")]
        engine._source_data = {0: {f"d{i}": 1.0 if i < 10 else 0.0 for i in range(20)}}
        engine._precompute_quality_flags()
        assert 0 not in engine._low_var_sources
        assert 0 in engine._binary_sources

    def test_very_unbalanced_binary_is_low_var(self) -> None:
        engine = _make_engine()
        engine._sources = [(SourceKey(metric_id=1), "bool")]
        # 1 True, 19 False → variance ≈ 0.05 ≤ 0.10
        engine._source_data = {0: {f"d{i}": 1.0 if i == 0 else 0.0 for i in range(20)}}
        engine._precompute_quality_flags()
        assert 0 in engine._low_var_sources

    def test_empty_data_not_added(self) -> None:
        engine = _make_engine()
        engine._sources = [(SourceKey(metric_id=1), "number")]
        engine._source_data = {0: {}}
        engine._precompute_quality_flags()
        assert 0 not in engine._low_var_sources
        assert 0 not in engine._binary_sources

    def test_streak_sources_detected(self) -> None:
        engine = _make_engine()
        engine._sources = [
            (SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=1), "number"),
            (SourceKey(metric_id=2), "number"),
        ]
        engine._source_data = {
            0: {"d1": 1.0, "d2": 2.0, "d3": 3.0},
            1: {"d1": 10.0, "d2": 20.0, "d3": 30.0},
        }
        engine._precompute_quality_flags()
        assert 0 in engine._streak_sources
        assert 1 not in engine._streak_sources

    def test_rolling_avg_sources_detected(self) -> None:
        engine = _make_engine()
        engine._sources = [
            (SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=1, auto_option_id=7), "number"),
        ]
        engine._source_data = {0: {"d1": 5.0, "d2": 6.0, "d3": 7.0}}
        engine._precompute_quality_flags()
        assert 0 in engine._rolling_avg_sources

    def test_single_value_is_low_var(self) -> None:
        engine = _make_engine()
        engine._sources = [(SourceKey(metric_id=1), "number")]
        engine._source_data = {0: {"d1": 42.0}}
        engine._precompute_quality_flags()
        assert 0 in engine._low_var_sources
