"""Unit tests for correlation_config.py — TOML config loading and merging."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.correlation_config import (
    AutoSourcesConfig,
    CorrelationConfig,
    QualityFiltersConfig,
    load_config,
)


class TestLoadDefaultConfig(unittest.TestCase):
    """When TOML file does not exist, returns all defaults."""

    def test_defaults_returned(self) -> None:
        cfg = load_config(env="prod", path=Path("/nonexistent/path.toml"))
        self.assertEqual(cfg, CorrelationConfig())

    def test_default_auto_sources_all_enabled(self) -> None:
        cfg = load_config(env="prod", path=Path("/nonexistent/path.toml"))
        src = cfg.auto_sources
        for field_name in AutoSourcesConfig.__dataclass_fields__:
            val = getattr(src, field_name)
            if field_name == "rolling_avg_windows":
                self.assertEqual(val, (3, 7, 14))
            else:
                self.assertTrue(val, f"{field_name} should be True by default")

    def test_default_quality_filters_all_enabled(self) -> None:
        cfg = load_config(env="prod", path=Path("/nonexistent/path.toml"))
        qf = cfg.quality_filters
        for field_name in QualityFiltersConfig.__dataclass_fields__:
            self.assertTrue(getattr(qf, field_name), f"{field_name} should be True by default")


class TestLoadProdConfig(unittest.TestCase):
    """Parsing prod section from TOML."""

    def test_parse_prod_all_enabled(self) -> None:
        toml_content = b"""
[prod.auto_sources.nonzero]
enabled = true
description = "test"

[prod.auto_sources.streak]
enabled = false
description = "disabled"

[prod.quality_filters.wide_ci]
enabled = false
description = "disabled"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        self.assertTrue(cfg.auto_sources.nonzero)
        self.assertFalse(cfg.auto_sources.streak)
        self.assertFalse(cfg.quality_filters.wide_ci)
        # Unspecified fields stay True (default)
        self.assertTrue(cfg.auto_sources.rolling_avg)
        self.assertTrue(cfg.quality_filters.high_p_value)

    def test_rolling_avg_windows_parsed(self) -> None:
        toml_content = b"""
[prod.auto_sources.rolling_avg]
enabled = true
windows = [5, 10, 20]
description = "custom windows"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        self.assertTrue(cfg.auto_sources.rolling_avg)
        self.assertEqual(cfg.auto_sources.rolling_avg_windows, (5, 10, 20))


class TestLocalInheritsProd(unittest.TestCase):
    """Local without overrides should equal prod."""

    def test_local_equals_prod_when_no_overrides(self) -> None:
        toml_content = b"""
[prod.auto_sources.nonzero]
enabled = true
description = "test"

[prod.auto_sources.streak]
enabled = false
description = "off in prod"

[prod.quality_filters.wide_ci]
enabled = false
description = "off in prod"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg_prod = load_config(env="prod", path=Path(f.name))
            cfg_local = load_config(env="local", path=Path(f.name))

        self.assertEqual(cfg_prod, cfg_local)


class TestLocalOverridesProd(unittest.TestCase):
    """Local section overrides specific prod values."""

    def test_local_overrides_auto_source(self) -> None:
        toml_content = b"""
[prod.auto_sources.streak]
enabled = false
description = "off in prod"

[prod.auto_sources.nonzero]
enabled = true
description = "on"

[local.auto_sources.streak]
enabled = true
description = "re-enabled locally"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg_prod = load_config(env="prod", path=Path(f.name))
            cfg_local = load_config(env="local", path=Path(f.name))

        self.assertFalse(cfg_prod.auto_sources.streak)
        self.assertTrue(cfg_local.auto_sources.streak)
        # Non-overridden values inherited from prod
        self.assertTrue(cfg_local.auto_sources.nonzero)

    def test_local_overrides_quality_filter(self) -> None:
        toml_content = b"""
[prod.quality_filters.high_p_value]
enabled = true
description = "on"

[local.quality_filters.high_p_value]
enabled = false
description = "off locally"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="local", path=Path(f.name))

        self.assertFalse(cfg.quality_filters.high_p_value)


class TestRollingAvgWindowsOverride(unittest.TestCase):
    """Local can override rolling_avg windows."""

    def test_local_overrides_windows(self) -> None:
        toml_content = b"""
[prod.auto_sources.rolling_avg]
enabled = true
windows = [3, 7, 14]
description = "prod windows"

[local.auto_sources.rolling_avg]
enabled = true
windows = [7]
description = "only 7-day locally"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg_prod = load_config(env="prod", path=Path(f.name))
            cfg_local = load_config(env="local", path=Path(f.name))

        self.assertEqual(cfg_prod.auto_sources.rolling_avg_windows, (3, 7, 14))
        self.assertEqual(cfg_local.auto_sources.rolling_avg_windows, (7,))

    def test_local_can_disable_rolling_avg(self) -> None:
        toml_content = b"""
[prod.auto_sources.rolling_avg]
enabled = true
windows = [3, 7, 14]
description = "on"

[local.auto_sources.rolling_avg]
enabled = false
description = "off locally"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="local", path=Path(f.name))

        self.assertFalse(cfg.auto_sources.rolling_avg)
        # windows keeps prod value since local didn't specify it
        # but since table-level override replaces the whole table,
        # rolling_avg_windows falls back to default
        self.assertEqual(cfg.auto_sources.rolling_avg_windows, (3, 7, 14))


class TestUnknownKeysIgnored(unittest.TestCase):
    """Unknown keys in TOML should not break loading."""

    def test_unknown_auto_source_ignored(self) -> None:
        toml_content = b"""
[prod.auto_sources.nonzero]
enabled = true
description = "known"

[prod.auto_sources.future_feature]
enabled = true
description = "unknown source type"

[prod.quality_filters.future_filter]
enabled = true
description = "unknown filter"
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        self.assertTrue(cfg.auto_sources.nonzero)
        # Should not raise — unknown keys silently ignored

    def test_extra_fields_in_source_ignored(self) -> None:
        toml_content = b"""
[prod.auto_sources.nonzero]
enabled = true
description = "test"
some_extra_field = 42
"""
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        self.assertTrue(cfg.auto_sources.nonzero)


class TestEmptyToml(unittest.TestCase):
    """Empty TOML file returns defaults."""

    def test_empty_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(b"")
            f.flush()
            cfg = load_config(env="prod", path=Path(f.name))

        self.assertEqual(cfg, CorrelationConfig())


class TestConfigImmutable(unittest.TestCase):
    """Config dataclasses are frozen."""

    def test_cannot_mutate_auto_sources(self) -> None:
        cfg = CorrelationConfig()
        with self.assertRaises(AttributeError):
            cfg.auto_sources.nonzero = False  # type: ignore[misc]

    def test_cannot_mutate_quality_filters(self) -> None:
        cfg = CorrelationConfig()
        with self.assertRaises(AttributeError):
            cfg.quality_filters.wide_ci = False  # type: ignore[misc]
