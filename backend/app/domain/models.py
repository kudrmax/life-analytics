"""Domain models — pure data structures without framework dependencies.

These models represent core domain concepts. They can be used as
intermediate representations between DB records and API responses.
No dependencies on FastAPI, asyncpg, or HTTP concepts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.enums import MetricType


@dataclass(frozen=True)
class Metric:
    """Core metric definition."""
    id: int
    slug: str
    name: str
    type: MetricType
    enabled: bool
    sort_order: int
    icon: str = ""
    description: str | None = None
    category_id: int | None = None
    private: bool = False
    hide_in_cards: bool = False


@dataclass(frozen=True)
class Entry:
    """A single metric entry for a specific date."""
    id: int
    metric_id: int
    user_id: int
    date: date
    recorded_at: datetime
    value: bool | str | int | list[int] | float | None = None
    slot_id: int | None = None
    slot_label: str = ""


@dataclass(frozen=True)
class DailyMetricItem:
    """One metric's data within a daily summary."""
    metric_id: int
    name: str
    icon: str
    type: str
    value: bool | str | int | list[int] | float | None = None
    display_value: str = ""
    is_blocked: bool = False


@dataclass
class DailySummary:
    """Summary of all metrics for a single day."""
    date: str
    metrics: list[DailyMetricItem] = field(default_factory=list)
    progress: float = 0.0
    filled_count: int = 0
    total_count: int = 0


@dataclass(frozen=True)
class CorrelationResult:
    """A single correlation pair result."""
    source_key_a: str
    source_key_b: str
    correlation: float
    data_points: int
    lag_days: int = 0
    p_value: float | None = None
    quality_issue: str | None = None
