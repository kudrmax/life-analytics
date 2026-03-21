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
    slot_max: bool = True
    slot_min: bool = True
    rolling_avg: bool = True
    rolling_avg_windows: tuple[int, ...] = (3, 7, 14)
    streak: bool = True
    day_of_week: bool = True
    month: bool = True
    is_workday: bool = True
    aw_active: bool = True


@dataclass(frozen=True)
class QualityFiltersConfig:
    low_data_points: bool = True
    insufficient_variance: bool = True
    low_binary_data_points: bool = True
    high_p_value: bool = True
    fisher_exact_high_p: bool = True
    wide_ci: bool = True
    low_streak_resets: bool = True


@dataclass(frozen=True)
class CorrelationConfig:
    auto_sources: AutoSourcesConfig = field(default_factory=AutoSourcesConfig)
    quality_filters: QualityFiltersConfig = field(default_factory=QualityFiltersConfig)


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
    """Extract enabled flags from quality_filters tables."""
    kwargs: dict[str, bool] = {}
    for name, obj in tables.items():
        if name in QualityFiltersConfig.__dataclass_fields__:
            kwargs[name] = obj.get("enabled", True)  # type: ignore[assignment]
    return QualityFiltersConfig(**kwargs)


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

    # Merge local on top if env=local (table-level override)
    if env == "local":
        local_sources = raw.get("local", {}).get("auto_sources", {})
        local_quality = raw.get("local", {}).get("quality_filters", {})
        merged_sources = {**prod_sources, **local_sources}
        merged_quality = {**prod_quality, **local_quality}
    else:
        merged_sources = prod_sources
        merged_quality = prod_quality

    return CorrelationConfig(
        auto_sources=_parse_auto_sources(merged_sources),
        quality_filters=_parse_quality_filters(merged_quality),
    )


correlation_config: CorrelationConfig = load_config()
