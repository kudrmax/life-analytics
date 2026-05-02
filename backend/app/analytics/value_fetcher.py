from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from statistics import mean
from typing import TYPE_CHECKING

from app.analytics.value_converter import ValueConverter
from app.domain.enums import MetricType
from app.formula import evaluate_formula

if TYPE_CHECKING:
    from app.repositories.analytics_repository import AnalyticsRepository


class ValueFetcher:
    """Извлекает значения метрик из БД, возвращает dict[str, float] (date->value)."""

    def __init__(self, repo: AnalyticsRepository) -> None:
        self._repo = repo

    async def values_by_date_for_checkpoint(
        self,
        metric_id: int,
        metric_type: str,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
        checkpoint_id: int | None = None,
        *,
        free_interval_only: bool = False,
    ) -> dict[str, float]:
        """Get values by date for a metric, optionally filtered by checkpoint."""
        value_table, extra_cols = ValueConverter.get_value_table(metric_type)
        rows = await self._repo.fetch_entries_values_with_checkpoint(
            metric_id, value_table, extra_cols, start_date, end_date, checkpoint_id,
            free_interval_only=free_interval_only,
        )
        return ValueConverter.aggregate_by_date(rows, metric_type)

    async def values_by_date_for_interval(
        self,
        metric_id: int,
        metric_type: str,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
        interval_id: int | None = None,
    ) -> dict[str, float]:
        """Get values by date for a metric, optionally filtered by interval."""
        value_table, extra_cols = ValueConverter.get_value_table(metric_type)
        rows = await self._repo.fetch_entries_values_with_interval(
            metric_id, value_table, extra_cols, start_date, end_date, interval_id,
        )
        return ValueConverter.aggregate_by_date(rows, metric_type)

    async def raw_values_by_date(
        self,
        metric_id: int,
        metric_type: str,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
    ) -> dict[str, float]:
        """Get values by date using scale→0..1 normalization (for computed metric evaluation)."""
        value_table, extra_cols = ValueConverter.get_value_table(metric_type)

        scale_min, scale_max = None, None
        if metric_type == MetricType.scale:
            scale_min, scale_max = await self._repo.get_scale_config_bounds(metric_id)

        rows = await self._repo.fetch_entries_values_with_checkpoint(
            metric_id, value_table, extra_cols, start_date, end_date,
        )

        day_values: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            raw = r["value"]
            if metric_type == MetricType.time:
                cv = raw.hour * 60 + raw.minute if raw else None
            elif metric_type == MetricType.bool:
                cv = 1.0 if raw else 0.0
            elif metric_type == MetricType.scale:
                s_min = r.get("scale_min", scale_min) if r.get("scale_min") is not None else scale_min
                s_max = r.get("scale_max", scale_max) if r.get("scale_max") is not None else scale_max
                s_min_f = float(s_min) if s_min is not None else 1.0
                s_max_f = float(s_max) if s_max is not None else 5.0
                cv = (float(raw) - s_min_f) / (s_max_f - s_min_f) if s_max_f != s_min_f else 0.0
            else:
                cv = float(raw) if raw is not None else None
            if cv is not None:
                day_values[str(r["date"])].append(cv)

        result: dict[str, float] = {}
        for d, vals in day_values.items():
            if metric_type == MetricType.bool:
                result[d] = 1.0 if any(v == 1.0 for v in vals) else 0.0
            else:
                result[d] = mean(vals) if vals else 0.0
        return result

    async def values_list_by_date(
        self,
        metric_id: int,
        metric_type: str,
        start_date: date_type,
        end_date: date_type,
        *,
        free_interval_only: bool = False,
    ) -> dict[str, list[float]]:
        """Get per-day list of numeric values WITHOUT aggregation.

        Used by FREE_CP_MAX/MIN/RANGE and FREE_IV auto-sources to compute
        max/min/range from free_checkpoint/free_interval entries.
        """
        value_table, extra_cols = ValueConverter.get_value_table(metric_type)
        rows = await self._repo.fetch_entries_values_with_checkpoint(
            metric_id, value_table, extra_cols, start_date, end_date,
            free_interval_only=free_interval_only,
        )
        day_values: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            v = ValueConverter.extract_numeric(r, metric_type)
            if v is not None:
                day_values[str(r["date"])].append(v)
        return dict(day_values)

    async def values_by_date_for_computed(
        self,
        formula: list,
        result_type: str,
        ref_ids: list[int],
        start_date: date_type,
        end_date: date_type,
        user_id: int,
    ) -> dict[str, float]:
        """Evaluate a computed metric for each date in range."""
        if not ref_ids:
            return {}

        source_types = await self._repo.get_metric_types_by_ids(ref_ids)

        source_data: dict[int, dict[str, float]] = {}
        for mid in ref_ids:
            mt = source_types.get(mid)
            if not mt:
                continue
            source_data[mid] = await self.raw_values_by_date(
                mid, mt, start_date, end_date, user_id,
            )

        all_dates: set[str] = set()
        for d in source_data.values():
            all_dates.update(d.keys())

        result: dict[str, float] = {}
        for d in sorted(all_dates):
            values_for_day = {mid: source_data.get(mid, {}).get(d) for mid in ref_ids}
            raw = evaluate_formula(formula, values_for_day, result_type)
            if raw is not None:
                if result_type == MetricType.bool:
                    result[d] = 1.0 if raw else 0.0
                elif result_type == MetricType.time:
                    if isinstance(raw, str) and ":" in raw:
                        h, m = map(int, raw.split(":"))
                        result[d] = float(h * 60 + m)
                    else:
                        result[d] = float(raw)
                elif result_type == MetricType.duration:
                    if isinstance(raw, str) and "ч" in raw:
                        parts = raw.replace("м", "").split("ч")
                        result[d] = float(int(parts[0].strip()) * 60 + int(parts[1].strip()))
                    else:
                        result[d] = float(raw)
                else:
                    result[d] = float(raw)
        return result

    async def time_ranges_by_date(
        self,
        metric_id: int,
        start_date: date_type,
        end_date: date_type,
    ) -> dict[str, list[float]]:
        """Load free interval durations in minutes, grouped by date."""
        rows = await self._repo.conn.fetch(
            "SELECT date, time_start, time_end FROM entries "
            "WHERE metric_id = $1 AND user_id = $2 AND date >= $3 AND date <= $4 "
            "AND is_free_interval = true AND time_start IS NOT NULL AND time_end IS NOT NULL",
            metric_id, self._repo.user_id, start_date, end_date,
        )
        result: dict[str, list[float]] = {}
        for r in rows:
            d = str(r["date"])
            ts = r["time_start"]
            te = r["time_end"]
            dur = (te.hour * 60 + te.minute) - (ts.hour * 60 + ts.minute)
            if dur < 0:
                dur += 24 * 60  # handle overnight intervals
            result.setdefault(d, []).append(float(dur))
        return result

    async def values_by_date_for_enum_option(
        self,
        metric_id: int,
        option_id: int,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
        checkpoint_id: int | None = None,
    ) -> dict[str, float]:
        """For a single enum option, return 1.0 if selected, 0.0 if entry exists but not selected."""
        rows = await self._repo.fetch_enum_entries_with_checkpoint(
            metric_id, start_date, end_date, checkpoint_id,
        )

        day_values: dict[str, list[bool]] = defaultdict(list)
        for r in rows:
            day_values[str(r["date"])].append(option_id in r["selected_option_ids"])

        result: dict[str, float] = {}
        for d, bools in day_values.items():
            result[d] = 1.0 if any(bools) else 0.0
        return result

    async def values_by_date_for_enum_option_interval(
        self,
        metric_id: int,
        option_id: int,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
        interval_id: int | None = None,
    ) -> dict[str, float]:
        """For a single enum option with interval, return 1.0 if selected, 0.0 otherwise."""
        rows = await self._repo.fetch_enum_entries_with_interval(
            metric_id, start_date, end_date, interval_id,
        )

        day_values: dict[str, list[bool]] = defaultdict(list)
        for r in rows:
            day_values[str(r["date"])].append(option_id in r["selected_option_ids"])

        result: dict[str, float] = {}
        for d, bools in day_values.items():
            result[d] = 1.0 if any(bools) else 0.0
        return result

    async def fetch_note_counts(
        self,
        metric_id: int,
        user_id: int,
        start_date: date_type,
        end_date: date_type,
    ) -> dict[str, float]:
        """Count notes per day for a text metric."""
        rows = await self._repo.fetch_note_counts(metric_id, start_date, end_date)
        return {str(r["date"]): float(r["cnt"]) for r in rows}
