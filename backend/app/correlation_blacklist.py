"""Blacklist for correlation pairs that should be skipped."""

from app.source_key import (
    AutoSourceType, SourceKey, _CALENDAR_TYPES, STREAK_TYPES, _ROLLING_AVG_TYPES, _DELTA_TYPES,
)

# Pairs of auto-source type groups that should not be correlated.
# Each entry: (group_A, group_B) — if one source is in A and other in B, skip.
# Order doesn't matter: (A, B) also matches (B, A).
_SKIP_AUTO_PAIRS: list[tuple[frozenset[AutoSourceType], frozenset[AutoSourceType]]] = [
    (_CALENDAR_TYPES, _CALENDAR_TYPES),    # calendar × calendar
    (STREAK_TYPES, STREAK_TYPES),          # streak × streak
    (STREAK_TYPES, _ROLLING_AVG_TYPES),    # streak × rolling_avg
    (_DELTA_TYPES, _DELTA_TYPES),          # delta × delta / trend × range / etc.
    (_DELTA_TYPES, _ROLLING_AVG_TYPES),    # delta × rolling_avg (derived series)
]


def should_skip_pair(
    a: SourceKey,
    b: SourceKey,
    single_select_metric_ids: set[int] | None = None,
) -> bool:
    """Check if a correlation pair should be skipped.

    Rules:
    - Same metric (different checkpoints/intervals) — skip
    - Same metric enum sources with different options — DON'T skip (independent data)
      EXCEPT single-select enums where options are mutually exclusive — skip
    - Auto metric and its parent — skip
    - Two auto metrics from the same parent — skip
    - Incompatible auto-type pairs (see _SKIP_AUTO_PAIRS) — skip
    """
    # Same metric (different checkpoints/intervals)
    if a.metric_id is not None and a.metric_id == b.metric_id and not a.is_auto and not b.is_auto:
        # Exception: enum option sources from the same metric with different option_ids
        if a.enum_option_id is not None and b.enum_option_id is not None:
            if a.enum_option_id != b.enum_option_id:
                # Single-select enums: options are mutually exclusive, correlation is predetermined
                if single_select_metric_ids and a.metric_id in single_select_metric_ids:
                    return True
                return False  # multi-select: different options = independent data
        return True

    if not a.is_auto and not b.is_auto:
        return False

    # Both auto
    if a.is_auto and b.is_auto:
        # Same parent — skip
        if a.auto_parent_metric_id is not None and a.auto_parent_metric_id == b.auto_parent_metric_id:
            return True
        # Incompatible auto-type pairs — skip
        for group_a, group_b in _SKIP_AUTO_PAIRS:
            if (a.auto_type in group_a and b.auto_type in group_b) or \
               (a.auto_type in group_b and b.auto_type in group_a):
                return True
        return False

    # One auto, one regular — skip if regular is auto's parent
    auto, regular = (a, b) if a.is_auto else (b, a)
    if auto.auto_parent_metric_id is not None and regular.metric_id == auto.auto_parent_metric_id:
        # Streak for specific enum option → only skip if same option
        if auto.auto_type in STREAK_TYPES and auto.auto_option_id is not None:
            return regular.enum_option_id == auto.auto_option_id
        return True

    return False
