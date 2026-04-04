"""Load and merge correlation engine configuration from TOML."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "correlation.toml"


@dataclass(frozen=True)
class AutoSourcesConfig:
    nonzero: bool = True
    note_count: bool = True
    checkpoint_max: bool = True
    checkpoint_min: bool = True
    rolling_avg: bool = True
    rolling_avg_windows: tuple[int, ...] = (3, 7, 14)
    streak: bool = False
    day_of_week: bool = True
    month: bool = True
    is_workday: bool = True
    aw_active: bool = True
    delta: bool = True
    trend: bool = True
    range: bool = True
    free_cp_max: bool = True
    free_cp_min: bool = True
    free_cp_range: bool = True


@dataclass(frozen=True)
class QualityFiltersConfig:
    low_data_points: bool = True
    insufficient_variance: bool = True
    low_binary_data_points: bool = True
    high_p_value: bool = True
    fisher_exact_high_p: bool = True
    wide_ci: bool = True
    low_streak_resets: bool = True
    low_streak_resets_min_resets: int = 2


@dataclass(frozen=True)
class ThresholdsConfig:
    min_data_points: int = 10
    p_value_significance: float = 0.05
    ci_width: float = 0.5
    strong_correlation: float = 0.7
    moderate_correlation: float = 0.3
    binary_var_threshold: float = 0.10
    zero_var_eps: float = 1e-9
    min_binary_group_size: int = 5


@dataclass(frozen=True)
class CorrelationConfig:
    auto_sources: AutoSourcesConfig = field(default_factory=AutoSourcesConfig)
    quality_filters: QualityFiltersConfig = field(default_factory=QualityFiltersConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    method: str = "pearson"


def _parse_auto_sources(tables: dict[str, dict[str, object]]) -> AutoSourcesConfig:
    """Extract enabled flags and extra fields from auto_sources tables."""
    kwargs: dict[str, object] = {}
    for name, obj in tables.items():
        if name not in AutoSourcesConfig.__dataclass_fields__:
            if name == "rolling_avg":
                pass  # handled below via special key
            else:
                continue
        if name == "rolling_avg":
            kwargs["rolling_avg"] = obj.get("enabled", True)
            if "windows" in obj:
                kwargs["rolling_avg_windows"] = tuple(obj["windows"])  # type: ignore[arg-type]
        else:
            kwargs[name] = obj.get("enabled", True)
    return AutoSourcesConfig(**kwargs)  # type: ignore[arg-type]


def _parse_quality_filters(tables: dict[str, dict[str, object]]) -> QualityFiltersConfig:
    """Extract enabled flags and extra fields from quality_filters tables."""
    kwargs: dict[str, object] = {}
    for name, obj in tables.items():
        if name not in QualityFiltersConfig.__dataclass_fields__:
            continue
        if name == "low_streak_resets":
            kwargs["low_streak_resets"] = obj.get("enabled", True)
            if "min_resets" in obj:
                kwargs["low_streak_resets_min_resets"] = obj["min_resets"]
        else:
            kwargs[name] = obj.get("enabled", True)
    return QualityFiltersConfig(**kwargs)  # type: ignore[arg-type]


def _parse_thresholds(raw_thresholds: dict[str, object]) -> ThresholdsConfig:
    """Extract threshold values from flat TOML table."""
    kwargs: dict[str, object] = {}
    for name in ThresholdsConfig.__dataclass_fields__:
        if name in raw_thresholds:
            kwargs[name] = raw_thresholds[name]
    return ThresholdsConfig(**kwargs)  # type: ignore[arg-type]


def load_config(env: str | None = None, path: Path | None = None) -> CorrelationConfig:
    """Load config: prod as base, local overrides on top (if env=local)."""
    if env is None:
        env = os.environ.get("LA_ENV", "local")

    config_path = path if path is not None else _CONFIG_PATH

    if not config_path.exists():
        return CorrelationConfig()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    # Start with prod tables
    prod_sources = raw.get("prod", {}).get("auto_sources", {})
    prod_quality = raw.get("prod", {}).get("quality_filters", {})
    prod_thresholds = raw.get("prod", {}).get("thresholds", {})
    prod_method = raw.get("prod", {}).get("method", "pearson")

    # Merge local on top if env=local (table-level override)
    if env == "local":
        local_sources = raw.get("local", {}).get("auto_sources", {})
        local_quality = raw.get("local", {}).get("quality_filters", {})
        local_thresholds = raw.get("local", {}).get("thresholds", {})
        merged_sources = {**prod_sources, **local_sources}
        merged_quality = {**prod_quality, **local_quality}
        merged_thresholds = {**prod_thresholds, **local_thresholds}
        method = raw.get("local", {}).get("method", prod_method)
    else:
        merged_sources = prod_sources
        merged_quality = prod_quality
        merged_thresholds = prod_thresholds
        method = prod_method

    return CorrelationConfig(
        auto_sources=_parse_auto_sources(merged_sources),
        quality_filters=_parse_quality_filters(merged_quality),
        thresholds=_parse_thresholds(merged_thresholds),
        method=method,
    )


correlation_config: CorrelationConfig = load_config()
