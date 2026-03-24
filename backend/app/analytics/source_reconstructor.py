from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import TYPE_CHECKING

from app.analytics.time_series import TimeSeriesTransform
from app.analytics.value_converter import ValueConverter
from app.analytics.value_fetcher import ValueFetcher
from app.domain.constants import SECONDS_PER_HOUR
from app.domain.enums import MetricType
from app.formula import get_referenced_metric_ids
from app.source_key import AutoSourceType, SourceKey, STREAK_TYPES

if TYPE_CHECKING:
    from app.repositories.analytics_repository import AnalyticsRepository


class SourceReconstructor:
    """Восстанавливает time-series по source_key для графика корреляционной пары."""

    def __init__(self, repo: AnalyticsRepository) -> None:
        self._repo = repo
        self._fetcher = ValueFetcher(repo)

    async def reconstruct(
        self,
        source_key_str: str,
        source_type: str,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
    ) -> dict[str, float]:
        """Reconstruct time-series data for a correlation source from its stored source_key."""
        sk = SourceKey.parse(source_key_str)

        if sk.is_auto:
            return await self._reconstruct_auto(sk, start_date, end_date, user_id)

        # Enum option source
        if sk.enum_option_id is not None and sk.metric_id is not None:
            return await self._fetcher.values_by_date_for_enum_option(
                sk.metric_id, sk.enum_option_id, start_date, end_date, user_id, slot_id=sk.slot_id,
            )

        # Computed metric
        if source_type == MetricType.computed and sk.metric_id is not None:
            cfg = await self._repo.get_computed_config(sk.metric_id)
            if not cfg or not cfg["formula"]:
                return {}
            formula = ValueConverter.parse_formula(cfg["formula"])
            rt = cfg["result_type"] or "float"
            ref_ids = get_referenced_metric_ids(formula)
            return await self._fetcher.values_by_date_for_computed(
                formula, rt, ref_ids, start_date, end_date, user_id,
            )

        # Regular metric
        if sk.metric_id is not None:
            return await self._fetcher.values_by_date_for_slot(
                sk.metric_id, source_type, start_date, end_date, user_id, slot_id=sk.slot_id,
            )

        return {}

    async def _reconstruct_auto(
        self,
        sk: SourceKey,
        start_date: date_type,
        end_date: date_type,
        user_id: int,
    ) -> dict[str, float]:
        all_dates = [
            str(start_date + timedelta(days=i))
            for i in range((end_date - start_date).days + 1)
        ]

        if sk.auto_type == AutoSourceType.DAY_OF_WEEK:
            if sk.auto_option_id is not None:
                return {d: (1.0 if date_type.fromisoformat(d).isoweekday() == sk.auto_option_id else 0.0) for d in all_dates}
            return {}
        if sk.auto_type == AutoSourceType.MONTH:
            if sk.auto_option_id is not None:
                return {d: (1.0 if date_type.fromisoformat(d).month == sk.auto_option_id else 0.0) for d in all_dates}
            return {}
        if sk.auto_type == AutoSourceType.IS_WORKDAY:
            if sk.auto_option_id is not None:
                if sk.auto_option_id == 1:
                    return {d: (1.0 if date_type.fromisoformat(d).isoweekday() <= 5 else 0.0) for d in all_dates}
                return {d: (1.0 if date_type.fromisoformat(d).isoweekday() > 5 else 0.0) for d in all_dates}
            return {}
        if sk.auto_type == AutoSourceType.WEEK_NUMBER:
            return {}  # deprecated, kept for backward compat
        if sk.auto_type == AutoSourceType.AW_ACTIVE:
            rows = await self._repo.get_aw_active_seconds(start_date, end_date)
            return {str(r["date"]): r["active_seconds"] / SECONDS_PER_HOUR for r in rows}
        if sk.auto_type == AutoSourceType.NONZERO and sk.auto_parent_metric_id is not None:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return {}
            raw = await self._fetcher.values_by_date_for_slot(
                parent["id"], parent["type"], start_date, end_date, user_id,
            )
            return {d: (1.0 if v > 0 else 0.0) for d, v in raw.items()}
        if sk.auto_type == AutoSourceType.NOTE_COUNT and sk.auto_parent_metric_id is not None:
            return await self._fetcher.fetch_note_counts(
                sk.auto_parent_metric_id, user_id, start_date, end_date,
            )
        if sk.auto_type in (AutoSourceType.SLOT_MAX, AutoSourceType.SLOT_MIN) and sk.auto_parent_metric_id is not None:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return {}
            slot_ids = await self._repo.get_enabled_slot_ids(sk.auto_parent_metric_id)
            if not slot_ids:
                return {}
            slot_data: list[dict[str, float]] = []
            for sid in slot_ids:
                sd = await self._fetcher.values_by_date_for_slot(
                    parent["id"], parent["type"], start_date, end_date, user_id, slot_id=sid,
                )
                slot_data.append(sd)
            all_dates_set: set[str] = set()
            for sd in slot_data:
                all_dates_set.update(sd.keys())
            agg_fn = max if sk.auto_type == AutoSourceType.SLOT_MAX else min
            result: dict[str, float] = {}
            for d in all_dates_set:
                vals = [sd[d] for sd in slot_data if d in sd]
                if vals:
                    result[d] = agg_fn(vals)
            return result
        if sk.auto_type == AutoSourceType.ROLLING_AVG and sk.auto_parent_metric_id is not None and sk.auto_option_id is not None:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return {}
            parent_type = parent["type"]
            if parent_type == MetricType.computed:
                cfg = await self._repo.get_computed_config(sk.auto_parent_metric_id)
                if not cfg or not cfg["formula"]:
                    return {}
                formula = ValueConverter.parse_formula(cfg["formula"])
                rt = cfg["result_type"] or "float"
                ref_ids = get_referenced_metric_ids(formula)
                parent_data = await self._fetcher.values_by_date_for_computed(
                    formula, rt, ref_ids, start_date, end_date, user_id,
                )
            else:
                parent_data = await self._fetcher.values_by_date_for_slot(
                    parent["id"], parent_type, start_date, end_date, user_id,
                )
            return TimeSeriesTransform.rolling_avg(parent_data, sk.auto_option_id)
        if sk.auto_type in STREAK_TYPES and sk.auto_parent_metric_id is not None:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return {}
            if sk.auto_option_id is not None:
                parent_data = await self._fetcher.values_by_date_for_enum_option(
                    parent["id"], sk.auto_option_id, start_date, end_date, user_id,
                )
            else:
                parent_data = await self._fetcher.values_by_date_for_slot(
                    parent["id"], parent["type"], start_date, end_date, user_id,
                )
            target = sk.auto_type == AutoSourceType.STREAK_TRUE
            return TimeSeriesTransform.streak(parent_data, all_dates, target)
        return {}
