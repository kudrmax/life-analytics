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
    start_slot_data: dict[str, float] | None = None  # for delta: start checkpoint values
    end_slot_data: dict[str, float] | None = None  # for delta: end checkpoint values


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
    if auto_type == AutoSourceType.DELTA:
        return _compute_delta(inp)
    if auto_type == AutoSourceType.TREND:
        return _compute_trend(inp)
    if auto_type == AutoSourceType.RANGE:
        return _compute_range(inp)
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


def _compute_delta(inp: AutoSourceInput) -> dict[str, float]:
    """Delta = end_checkpoint_value - start_checkpoint_value per day."""
    if not inp.start_slot_data or not inp.end_slot_data:
        return {}
    return {
        d: inp.end_slot_data[d] - inp.start_slot_data[d]
        for d in inp.start_slot_data
        if d in inp.end_slot_data
    }


def _compute_trend(inp: AutoSourceInput) -> dict[str, float]:
    """Trend = last checkpoint - first checkpoint per day."""
    if not inp.slot_data or len(inp.slot_data) < 2:
        return {}
    first, last = inp.slot_data[0], inp.slot_data[-1]
    return {d: last[d] - first[d] for d in first if d in last}


def _compute_range(inp: AutoSourceInput) -> dict[str, float]:
    """Range = max - min across all checkpoints per day."""
    if not inp.slot_data:
        return {}
    max_d = _compute_slot_agg(AutoSourceType.SLOT_MAX, inp)
    min_d = _compute_slot_agg(AutoSourceType.SLOT_MIN, inp)
    return {d: max_d[d] - min_d[d] for d in max_d if d in min_d}


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
