"""Unit tests for ThresholdsConfig — TOML parsing and usage in QualityAssessor / engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.analytics.quality import QualityAssessor
from app.correlation_config import (
    CorrelationConfig,
    ThresholdsConfig,
    load_config,
)


class TestThresholdsConfigDefaults(unittest.TestCase):
    """Default values match previously hardcoded constants."""

    def test_default_values(self) -> None:
        t = ThresholdsConfig()
        assert t.min_data_points == 10
        assert t.p_value_significance == 0.05
        assert t.ci_width == 0.5
        assert t.strong_correlation == 0.7
        assert t.moderate_correlation == 0.3
        assert t.binary_var_threshold == 0.10
        assert t.zero_var_eps == 1e-9
        assert t.min_binary_group_size == 5

    def test_config_has_thresholds(self) -> None:
        cfg = CorrelationConfig()
        assert isinstance(cfg.thresholds, ThresholdsConfig)

    def test_frozen(self) -> None:
        t = ThresholdsConfig()
        with self.assertRaises(AttributeError):
            t.min_data_points = 20  # type: ignore[misc]


class TestThresholdsTOMLParsing(unittest.TestCase):
    """TOML parsing reads thresholds correctly."""

    def test_parse_custom_thresholds(self) -> None:
        toml_content = b"""
[prod.thresholds]
min_data_points = 20
p_value_significance = 0.01
strong_correlation = 0.8
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        assert cfg.thresholds.min_data_points == 20
        assert cfg.thresholds.p_value_significance == 0.01
        assert cfg.thresholds.strong_correlation == 0.8
        # Non-specified fields keep defaults
        assert cfg.thresholds.moderate_correlation == 0.3
        assert cfg.thresholds.ci_width == 0.5

    def test_local_overrides_prod_thresholds(self) -> None:
        toml_content = b"""
[prod.thresholds]
min_data_points = 15

[local.thresholds]
min_data_points = 5
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="local", path=Path(f.name))

        assert cfg.thresholds.min_data_points == 5

    def test_prod_env_ignores_local(self) -> None:
        toml_content = b"""
[prod.thresholds]
min_data_points = 15

[local.thresholds]
min_data_points = 5
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        assert cfg.thresholds.min_data_points == 15

    def test_missing_thresholds_section_uses_defaults(self) -> None:
        toml_content = b"""
[prod.auto_sources.nonzero]
enabled = true
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        assert cfg.thresholds == ThresholdsConfig()


class TestQualityAssessorUsesThresholds(unittest.TestCase):
    """QualityAssessor reads thresholds from config, not from constants."""

    def test_custom_min_data_points(self) -> None:
        """With min_data_points=5, n=7 should NOT trigger low_data_points."""
        cfg = CorrelationConfig(thresholds=ThresholdsConfig(min_data_points=5))
        qa = QualityAssessor(config=cfg)
        result = qa.determine_issue(n=7, p_value=0.01)
        assert result is None  # 7 >= 5, so no issue

    def test_default_min_data_points(self) -> None:
        """With default min_data_points=10, n=7 should trigger low_data_points."""
        cfg = CorrelationConfig()
        qa = QualityAssessor(config=cfg)
        result = qa.determine_issue(n=7, p_value=0.01)
        assert result == "low_data_points"

    def test_custom_p_value_threshold(self) -> None:
        """With p_value_significance=0.10, p=0.07 should NOT trigger high_p_value."""
        cfg = CorrelationConfig(thresholds=ThresholdsConfig(p_value_significance=0.10))
        qa = QualityAssessor(config=cfg)
        result = qa.determine_issue(n=30, p_value=0.07)
        assert result is None  # 0.07 < 0.10, so no issue

    def test_stricter_p_value_threshold(self) -> None:
        """With p_value_significance=0.01, p=0.03 should trigger high_p_value."""
        cfg = CorrelationConfig(thresholds=ThresholdsConfig(p_value_significance=0.01))
        qa = QualityAssessor(config=cfg)
        result = qa.determine_issue(n=30, p_value=0.03)
        assert result == "high_p_value"


class TestCategoryFilterSql(unittest.TestCase):
    """PairFormatter.category_filter_sql uses thresholds."""

    def test_custom_thresholds_in_sql(self) -> None:
        from app.analytics.pair_formatter import PairFormatter

        thresholds = ThresholdsConfig(strong_correlation=0.8, moderate_correlation=0.4)
        sql = PairFormatter.category_filter_sql("sig_strong", thresholds)
        assert "0.8" in sql
        assert "0.4" not in sql

    def test_sig_medium_uses_both_thresholds(self) -> None:
        from app.analytics.pair_formatter import PairFormatter

        thresholds = ThresholdsConfig(strong_correlation=0.8, moderate_correlation=0.4)
        sql = PairFormatter.category_filter_sql("sig_medium", thresholds)
        assert "0.8" in sql
        assert "0.4" in sql

    def test_unknown_category_returns_empty(self) -> None:
        from app.analytics.pair_formatter import PairFormatter

        sql = PairFormatter.category_filter_sql("nonexistent", ThresholdsConfig())
        assert sql == ""
