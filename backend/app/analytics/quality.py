from __future__ import annotations

from enum import Enum
from typing import ClassVar

from app.correlation_config import CorrelationConfig, correlation_config


class QualityIssue(str, Enum):
    LOW_DATA_POINTS = "low_data_points"
    INSUFFICIENT_VARIANCE = "insufficient_variance"
    LOW_BINARY_DATA_POINTS = "low_binary_data_points"
    HIGH_P_VALUE = "high_p_value"
    FISHER_EXACT_HIGH_P = "fisher_exact_high_p"
    WIDE_CI = "wide_ci"
    LOW_STREAK_RESETS = "low_streak_resets"


class QualityAssessor:
    """Оценка качества корреляционных пар."""

    LABELS: ClassVar[dict[str, str]] = {
        QualityIssue.LOW_DATA_POINTS: "Мало данных (менее 10 дней)",
        QualityIssue.INSUFFICIENT_VARIANCE: "Недостаточная дисперсия (значение почти не меняется)",
        QualityIssue.LOW_BINARY_DATA_POINTS: "Мало наблюдений в группе бинарного источника (менее 5)",
        QualityIssue.HIGH_P_VALUE: "Статистически незначимо (p ≥ 0.05)",
        QualityIssue.FISHER_EXACT_HIGH_P: "Совпадение бинарных значений может быть случайным (точный тест Фишера, p ≥ 0.05)",
        QualityIssue.WIDE_CI: "Широкий доверительный интервал",
        QualityIssue.LOW_STREAK_RESETS: "Серия сбрасывалась слишком редко (< 2 раз за период)",
    }

    SEVERITY: ClassVar[dict[str, str]] = {
        QualityIssue.LOW_DATA_POINTS: "bad",
        QualityIssue.INSUFFICIENT_VARIANCE: "bad",
        QualityIssue.LOW_BINARY_DATA_POINTS: "bad",
        QualityIssue.HIGH_P_VALUE: "bad",
        QualityIssue.FISHER_EXACT_HIGH_P: "maybe",
        QualityIssue.WIDE_CI: "maybe",
        QualityIssue.LOW_STREAK_RESETS: "bad",
    }

    def __init__(self, config: CorrelationConfig | None = None) -> None:
        cfg = config or correlation_config
        self._qf = cfg.quality_filters
        self._thresholds = cfg.thresholds

    def determine_issue(
        self,
        n: int,
        p_value: float,
        *,
        low_variance: bool = False,
        small_binary_group: bool = False,
        wide_ci: bool = False,
        fisher_high_p: bool = False,
        low_streak_resets: bool = False,
    ) -> str | None:
        """Определяет quality issue по приоритету. Первый match выигрывает."""
        checks = [
            (n < self._thresholds.min_data_points and self._qf.low_data_points, QualityIssue.LOW_DATA_POINTS),
            (small_binary_group and self._qf.low_binary_data_points, QualityIssue.LOW_BINARY_DATA_POINTS),
            (low_streak_resets and self._qf.low_streak_resets, QualityIssue.LOW_STREAK_RESETS),
            (low_variance and self._qf.insufficient_variance, QualityIssue.INSUFFICIENT_VARIANCE),
            (p_value >= self._thresholds.p_value_significance and self._qf.high_p_value, QualityIssue.HIGH_P_VALUE),
            (fisher_high_p and self._qf.fisher_exact_high_p, QualityIssue.FISHER_EXACT_HIGH_P),
            (wide_ci and self._qf.wide_ci, QualityIssue.WIDE_CI),
        ]
        return next((issue.value for cond, issue in checks if cond), None)
