"""Blacklist for correlation pairs that should be skipped."""

from app.source_key import AutoSourceType, SourceKey, _CALENDAR_TYPES


def should_skip_pair(a: SourceKey, b: SourceKey) -> bool:
    """Check if a correlation pair should be skipped.

    Rules:
    - Same metric (different slots) — skip
    - Same metric enum sources with different options — DON'T skip (independent data)
    - Auto metric and its parent — skip
    - Two auto metrics from the same parent — skip
    - Two calendar metrics (day_of_week, month, week_number) — skip
    """
    # Same metric (different slots)
    if a.metric_id is not None and a.metric_id == b.metric_id and not a.is_auto and not b.is_auto:
        # Exception: enum option sources from the same metric with different option_ids
        if a.enum_option_id is not None and b.enum_option_id is not None:
            if a.enum_option_id != b.enum_option_id:
                return False  # different options = independent data
        return True

    if not a.is_auto and not b.is_auto:
        return False

    # Both auto
    if a.is_auto and b.is_auto:
        # Same parent — skip
        if a.auto_parent_metric_id is not None and a.auto_parent_metric_id == b.auto_parent_metric_id:
            return True
        # Both calendar — skip
        if a.auto_type in _CALENDAR_TYPES and b.auto_type in _CALENDAR_TYPES:
            return True
        return False

    # One auto, one regular — skip if regular is auto's parent
    auto, regular = (a, b) if a.is_auto else (b, a)
    if auto.auto_parent_metric_id is not None and regular.metric_id == auto.auto_parent_metric_id:
        return True

    return False
