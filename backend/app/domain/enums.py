"""Domain enums — единый источник правды для всех строковых перечислений."""

from enum import Enum


class MetricType(str, Enum):
    """Тип метрики (metric_definitions.type)."""
    bool = "bool"
    enum = "enum"
    time = "time"
    number = "number"
    scale = "scale"
    computed = "computed"
    integration = "integration"
    duration = "duration"
    text = "text"

class IntervalBinding(str, Enum):
    """Привязка факта к времени (metric_definitions.interval_binding)."""
    ALL_DAY = "all_day"
    BY_INTERVAL = "by_interval"
    FREE_CHECKPOINTS = "free_checkpoints"


class PairStatus(str, Enum):
    """Статус корреляционной пары (correlation_pair_statuses.status)."""
    FAVORITE = "favorite"
    ARCHIVED = "archived"


__all__ = [
    "MetricType",
    "IntervalBinding",
    "PairStatus",
    "ReportStatus",
    "CorrelationStrength",
    "ConditionType",
    "IntegrationProvider",
    "AWSourceType",
    "ComputedResultType",
]


class ReportStatus(str, Enum):
    """Статус корреляционного отчёта (correlation_reports.status)."""
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class CorrelationStrength(str, Enum):
    """Категория силы корреляции для фильтрации пар."""
    SIG_STRONG = "sig_strong"
    SIG_MEDIUM = "sig_medium"
    SIG_WEAK = "sig_weak"
    MAYBE = "maybe"
    INSIGNIFICANT = "insig"


class ConditionType(str, Enum):
    """Тип условия показа/скрытия метрики (metric_condition.condition_type)."""
    FILLED = "filled"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    NONE_SELECTED = "none_selected"
    ANY_SELECTED = "any_selected"


class IntegrationProvider(str, Enum):
    """Провайдеры интеграций (user_integrations.provider)."""
    TODOIST = "todoist"
    ACTIVITYWATCH = "activitywatch"


class AWSourceType(str, Enum):
    """Тип источника данных ActivityWatch (activitywatch_app_usage.source)."""
    WINDOW = "window"
    WEB = "web"


class ComputedResultType(str, Enum):
    """Тип результата вычисляемой метрики (computed_config.result_type)."""
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    TIME = "time"
    DURATION = "duration"
