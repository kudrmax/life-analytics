from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean
from typing import Any

from app.domain.enums import MetricType


class ValueConverter:
    """Конвертация значений метрик из БД-формата в числовой."""

    @staticmethod
    def parse_formula(raw: Any) -> list:
        """Parse formula from DB — may be JSON string or list."""
        if raw is None:
            return []
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    @staticmethod
    def extract_numeric(value_row: Any, metric_type: str = "bool") -> float | None:
        """Extract a numeric value from a value row.

        For bool: True=1, False=0.
        For time: minutes from midnight (e.g. 23:30 -> 1410).
        For scale: normalized to 0-100%.
        """
        if not value_row:
            return None
        v = value_row["value"]
        if metric_type == MetricType.time:
            # v is a datetime (TIMESTAMPTZ)
            return v.hour * 60 + v.minute
        elif metric_type == MetricType.number or metric_type == MetricType.duration:
            return float(v)
        elif metric_type == MetricType.scale:
            v_min = value_row["scale_min"]
            v_max = value_row["scale_max"]
            if v_max == v_min:
                return 0.0
            return (float(v) - v_min) / (v_max - v_min) * 100
        return 1.0 if v else 0.0

    @staticmethod
    def aggregate_by_date(rows: Any, metric_type: str) -> dict[str, float]:
        """Group rows by date, aggregate multiple entries per day (multi-checkpoint).

        For number/scale/time: mean of values per day.
        For bool: 1.0 if any True, else 0.0.
        """
        day_values: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            v = ValueConverter.extract_numeric(r, metric_type)
            if v is not None:
                day_values[str(r["date"])].append(v)

        result: dict[str, float] = {}
        for d, vals in day_values.items():
            if metric_type == MetricType.bool:
                result[d] = 1.0 if any(v == 1.0 for v in vals) else 0.0
            else:
                result[d] = mean(vals)
        return result

    @staticmethod
    def get_value_table(mt: str) -> tuple[str, str]:
        """Return (table_name, extra_cols) for a metric type."""
        if mt == MetricType.time:
            return "values_time", ""
        elif mt == MetricType.number:
            return "values_number", ""
        elif mt == MetricType.duration:
            return "values_duration", ""
        elif mt == MetricType.scale:
            return "values_scale", ", v.scale_min, v.scale_max, v.scale_step"
        elif mt == MetricType.enum:
            return "values_enum", ""
        return "values_bool", ""
