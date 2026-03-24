"""Registry of auto-source compute functions.

Single source of truth for auto-source data computation.
Both CorrelationEngine and SourceReconstructor call compute_auto_source()
after preparing the input data from their respective contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type

from app.analytics.time_series import TimeSeriesTransform
from app.source_key import AutoSourceType, STREAK_TYPES


@dataclass(frozen=True, slots=True)
class AutoSourceInput:
    """Universal input for auto-source computation.

    Callers (engine / reconstructor) are responsible for populating
    the relevant fields before calling compute_auto_source().
    """

    all_dates: list[str]
    parent_data: dict[str, float] | None = None
    slot_data: list[dict[str, float]] | None = None
    option_id: int | None = None
    target_value: bool | None = None  # for streak: True=streak_true, False=streak_false


def compute_auto_source(
    auto_type: AutoSourceType,
    inp: AutoSourceInput,
) -> dict[str, float]:
    """Compute time-series data for an auto-source type.

    Pure function — no DB access, no side effects.
    For DB-dependent sources (note_count, aw_active), data must be
    pre-fetched and passed via parent_data.
    """
    if auto_type == AutoSourceType.NONZERO:
        return _compute_nonzero(inp)
    if auto_type == AutoSourceType.DAY_OF_WEEK:
        return _compute_day_of_week(inp)
    if auto_type == AutoSourceType.MONTH:
        return _compute_month(inp)
    if auto_type == AutoSourceType.IS_WORKDAY:
        return _compute_is_workday(inp)
    if auto_type in (AutoSourceType.SLOT_MAX, AutoSourceType.SLOT_MIN):
        return _compute_slot_agg(auto_type, inp)
    if auto_type == AutoSourceType.ROLLING_AVG:
        return _compute_rolling_avg(inp)
    if auto_type in STREAK_TYPES:
        return _compute_streak(auto_type, inp)
    if auto_type == AutoSourceType.NOTE_COUNT:
        # Data pre-fetched by caller and passed as parent_data
        return inp.parent_data or {}
    if auto_type == AutoSourceType.AW_ACTIVE:
        # Data pre-fetched by caller and passed as parent_data
        return inp.parent_data or {}
    if auto_type == AutoSourceType.WEEK_NUMBER:
        return {}  # deprecated, kept for backward compat
    return {}


# ── Pure compute functions ────────────────────────────────────────


def _compute_nonzero(inp: AutoSourceInput) -> dict[str, float]:
    if not inp.parent_data:
        return {}
    return {d: (1.0 if v > 0 else 0.0) for d, v in inp.parent_data.items()}


def _compute_day_of_week(inp: AutoSourceInput) -> dict[str, float]:
    if inp.option_id is None:
        return {}
    return {
        d: (1.0 if date_type.fromisoformat(d).isoweekday() == inp.option_id else 0.0)
        for d in inp.all_dates
    }


def _compute_month(inp: AutoSourceInput) -> dict[str, float]:
    if inp.option_id is None:
        return {}
    return {
        d: (1.0 if date_type.fromisoformat(d).month == inp.option_id else 0.0)
        for d in inp.all_dates
    }


def _compute_is_workday(inp: AutoSourceInput) -> dict[str, float]:
    if inp.option_id is None:
        return {}
    if inp.option_id == 1:
        return {d: (1.0 if date_type.fromisoformat(d).isoweekday() <= 5 else 0.0) for d in inp.all_dates}
    return {d: (1.0 if date_type.fromisoformat(d).isoweekday() > 5 else 0.0) for d in inp.all_dates}


def _compute_slot_agg(auto_type: AutoSourceType, inp: AutoSourceInput) -> dict[str, float]:
    if not inp.slot_data:
        return {}
    agg_fn = max if auto_type == AutoSourceType.SLOT_MAX else min
    all_dates_set: set[str] = set()
    for sd in inp.slot_data:
        all_dates_set.update(sd.keys())
    result: dict[str, float] = {}
    for d in all_dates_set:
        vals = [sd[d] for sd in inp.slot_data if d in sd]
        if vals:
            result[d] = agg_fn(vals)
    return result


def _compute_rolling_avg(inp: AutoSourceInput) -> dict[str, float]:
    if not inp.parent_data or inp.option_id is None:
        return {}
    return TimeSeriesTransform.rolling_avg(inp.parent_data, inp.option_id)


def _compute_streak(auto_type: AutoSourceType, inp: AutoSourceInput) -> dict[str, float]:
    if not inp.parent_data:
        return {}
    target = auto_type == AutoSourceType.STREAK_TRUE
    if inp.target_value is not None:
        target = inp.target_value
    return TimeSeriesTransform.streak(inp.parent_data, inp.all_dates, target)
