from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import TYPE_CHECKING

from app.analytics.auto_sources.registry import AutoSourceInput, compute_auto_source
from app.analytics.value_converter import ValueConverter
from app.analytics.value_fetcher import ValueFetcher
from app.domain.constants import SECONDS_PER_HOUR
from app.domain.enums import MetricType
from app.formula import get_referenced_metric_ids
from app.source_key import AutoSourceType, SourceKey, STREAK_TYPES, _DELTA_TYPES

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

        # Delta: fetch start/end checkpoint slot data
        if sk.auto_type == AutoSourceType.DELTA:
            return await self._reconstruct_delta(sk, start_date, end_date, user_id, all_dates)

        # Trend/Range: fetch ordered slot data
        if sk.auto_type in (AutoSourceType.TREND, AutoSourceType.RANGE):
            slot_data = await self._fetch_ordered_slot_data(sk, start_date, end_date, user_id)
            inp = AutoSourceInput(all_dates=all_dates, slot_data=slot_data)
            return compute_auto_source(sk.auto_type, inp)

        parent_data = await self._fetch_parent_data(sk, start_date, end_date, user_id)
        slot_data = await self._fetch_slot_data(sk, start_date, end_date, user_id)

        inp = AutoSourceInput(
            all_dates=all_dates,
            parent_data=parent_data,
            slot_data=slot_data,
            option_id=sk.auto_option_id,
        )
        return compute_auto_source(sk.auto_type, inp)

    async def _reconstruct_delta(
        self, sk: SourceKey, start_date: date_type, end_date: date_type,
        user_id: int, all_dates: list[str],
    ) -> dict[str, float]:
        """Reconstruct delta auto-source from DB."""
        if sk.auto_parent_metric_id is None or sk.auto_option_id is None:
            return {}
        parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
        if not parent:
            return {}
        ordered_slots = await self._repo.get_ordered_slot_ids(sk.auto_parent_metric_id)
        if sk.auto_option_id not in ordered_slots:
            return {}
        start_idx = ordered_slots.index(sk.auto_option_id)
        if start_idx + 1 >= len(ordered_slots):
            return {}
        end_slot_id = ordered_slots[start_idx + 1]
        start_data = await self._fetcher.values_by_date_for_slot(
            parent["id"], parent["type"], start_date, end_date, user_id, slot_id=sk.auto_option_id,
        )
        end_data = await self._fetcher.values_by_date_for_slot(
            parent["id"], parent["type"], start_date, end_date, user_id, slot_id=end_slot_id,
        )
        inp = AutoSourceInput(all_dates=all_dates, start_slot_data=start_data, end_slot_data=end_data)
        return compute_auto_source(AutoSourceType.DELTA, inp)

    async def _fetch_ordered_slot_data(
        self, sk: SourceKey, start_date: date_type, end_date: date_type, user_id: int,
    ) -> list[dict[str, float]] | None:
        """Fetch slot data ordered by sort_order for trend/range."""
        if sk.auto_parent_metric_id is None:
            return None
        parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
        if not parent:
            return None
        ordered_slots = await self._repo.get_ordered_slot_ids(sk.auto_parent_metric_id)
        if not ordered_slots:
            return None
        result: list[dict[str, float]] = []
        for sid in ordered_slots:
            sd = await self._fetcher.values_by_date_for_slot(
                parent["id"], parent["type"], start_date, end_date, user_id, slot_id=sid,
            )
            result.append(sd)
        return result

    async def _fetch_parent_data(
        self, sk: SourceKey, start_date: date_type, end_date: date_type, user_id: int,
    ) -> dict[str, float] | None:
        """Fetch parent time-series data from DB for an auto source."""
        if sk.auto_type == AutoSourceType.AW_ACTIVE:
            rows = await self._repo.get_aw_active_seconds(start_date, end_date)
            return {str(r["date"]): r["active_seconds"] / SECONDS_PER_HOUR for r in rows}

        if sk.auto_type == AutoSourceType.NOTE_COUNT and sk.auto_parent_metric_id is not None:
            return await self._fetcher.fetch_note_counts(
                sk.auto_parent_metric_id, user_id, start_date, end_date,
            )

        if sk.auto_parent_metric_id is None:
            return None

        # Streak for enum option — fetch enum option data
        if sk.auto_type in STREAK_TYPES and sk.auto_option_id is not None:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return None
            return await self._fetcher.values_by_date_for_enum_option(
                parent["id"], sk.auto_option_id, start_date, end_date, user_id,
            )

        # Rolling avg for computed metrics
        if sk.auto_type == AutoSourceType.ROLLING_AVG:
            parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
            if not parent:
                return None
            if parent["type"] == MetricType.computed:
                cfg = await self._repo.get_computed_config(sk.auto_parent_metric_id)
                if not cfg or not cfg["formula"]:
                    return None
                formula = ValueConverter.parse_formula(cfg["formula"])
                rt = cfg["result_type"] or "float"
                ref_ids = get_referenced_metric_ids(formula)
                return await self._fetcher.values_by_date_for_computed(
                    formula, rt, ref_ids, start_date, end_date, user_id,
                )

        # Default: fetch metric aggregate data
        parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
        if not parent:
            return None
        return await self._fetcher.values_by_date_for_slot(
            parent["id"], parent["type"], start_date, end_date, user_id,
        )

    async def _fetch_slot_data(
        self, sk: SourceKey, start_date: date_type, end_date: date_type, user_id: int,
    ) -> list[dict[str, float]] | None:
        """Fetch slot time-series for slot_max/slot_min auto sources."""
        if sk.auto_type not in (AutoSourceType.SLOT_MAX, AutoSourceType.SLOT_MIN):
            return None
        if sk.auto_parent_metric_id is None:
            return None
        parent = await self._repo.get_metric_type_by_id(sk.auto_parent_metric_id)
        if not parent:
            return None
        slot_ids = await self._repo.get_enabled_slot_ids(sk.auto_parent_metric_id)
        if not slot_ids:
            return None
        result: list[dict[str, float]] = []
        for sid in slot_ids:
            sd = await self._fetcher.values_by_date_for_slot(
                parent["id"], parent["type"], start_date, end_date, user_id, slot_id=sid,
            )
            result.append(sd)
        return result
