"""Blacklist for correlation pairs that should be skipped."""

# Auto types that are calendar-based
_CALENDAR_TYPES = {"day_of_week", "month", "week_number"}


def should_skip_pair(i, j, sources, auto_info, enum_source_info=None):
    """Check if a correlation pair should be skipped.

    Rules:
    - Same metric (different slots) — skip
    - Same metric enum sources with different options — DON'T skip (independent data)
    - Auto metric and its parent — skip
    - Two auto metrics from the same parent — skip
    - Two calendar metrics (day_of_week, month, week_number) — skip
    """
    # Same metric (different slots)
    if sources[i][0] == sources[j][0] and sources[i][0] is not None:
        # Exception: enum option sources from the same metric with different option_ids
        if enum_source_info and i in enum_source_info and j in enum_source_info:
            opt_i = enum_source_info[i][0]
            opt_j = enum_source_info[j][0]
            if opt_i != opt_j:
                return False  # different options = independent data
        return True

    ai = auto_info.get(i)
    aj = auto_info.get(j)

    if not ai and not aj:
        return False

    # Both auto
    if ai and aj:
        # Same parent — skip
        if ai[1] is not None and ai[1] == aj[1]:
            return True
        # Both calendar — skip (бессмысленные пары типа день недели ↔ месяц)
        if ai[0] in _CALENDAR_TYPES and aj[0] in _CALENDAR_TYPES:
            return True
        return False

    # One auto, one regular — skip if regular is auto's parent
    auto, regular_idx = (ai, j) if ai else (aj, i)
    if auto[1] is not None and sources[regular_idx][0] == auto[1]:
        return True

    return False
