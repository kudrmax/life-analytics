"""Deterministic source keys for correlation pairs.

SourceKey encodes which data source a correlation side refers to:
- metric:{id}                                           — plain metric (aggregate)
- metric:{id}:checkpoint:{cp_id}                        — metric at checkpoint
- metric:{id}:interval:{iv_id}                          — metric for interval
- metric:{id}:enum_opt:{opt_id}                         — enum option (aggregate)
- metric:{id}:enum_opt:{opt_id}:checkpoint:{cp_id}      — enum option at checkpoint
- metric:{id}:enum_opt:{opt_id}:interval:{iv_id}        — enum option for interval
- auto:nonzero:metric:{id}                              — nonzero for a metric
- auto:note_count:metric:{id}                           — note count for text metric
- auto:checkpoint_max:metric:{id}                       — max across checkpoints for a metric
- auto:checkpoint_min:metric:{id}                       — min across checkpoints for a metric
- auto:rolling_avg:metric:{id}:opt:{window}             — rolling average (window = days)
- auto:streak_true:metric:{id}                          — streak (consecutive True days)
- auto:streak_false:metric:{id}                         — streak (consecutive False days)
- auto:streak_true:metric:{id}:opt:{oid}                — streak for enum option (True)
- auto:streak_false:metric:{id}:opt:{oid}               — streak for enum option (False)
- auto:day_of_week:opt:{N}                              — calendar (enum-like boolean per option)
- auto:month:opt:{N}
- auto:is_workday:opt:{N}
- auto:aw_active                                        — ActivityWatch active screen time
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AutoSourceType(str, Enum):
    NONZERO = "nonzero"
    NOTE_COUNT = "note_count"
    DAY_OF_WEEK = "day_of_week"
    MONTH = "month"
    CHECKPOINT_MAX = "checkpoint_max"
    CHECKPOINT_MIN = "checkpoint_min"
    ROLLING_AVG = "rolling_avg"
    STREAK_TRUE = "streak_true"
    STREAK_FALSE = "streak_false"
    WEEK_NUMBER = "week_number"  # kept for backward compat parsing old reports
    AW_ACTIVE = "aw_active"
    IS_WORKDAY = "is_workday"
    DELTA = "delta"
    TREND = "trend"
    RANGE = "range"
    FREE_CP_MAX = "free_cp_max"
    FREE_CP_MIN = "free_cp_min"
    FREE_CP_RANGE = "free_cp_range"


ROLLING_AVG_WINDOWS: list[int] = [3, 7, 14]

STREAK_TYPES: frozenset[AutoSourceType] = frozenset({
    AutoSourceType.STREAK_TRUE,
    AutoSourceType.STREAK_FALSE,
})


AUTO_DISPLAY_NAMES: dict[AutoSourceType, str] = {
    AutoSourceType.DAY_OF_WEEK: "День недели",
    AutoSourceType.MONTH: "Месяц",
    AutoSourceType.IS_WORKDAY: "Календарный тип",
    AutoSourceType.AW_ACTIVE: "Экранное время (активное)",
}

AUTO_ICONS: dict[AutoSourceType, str] = {
    AutoSourceType.DAY_OF_WEEK: "📅",
    AutoSourceType.MONTH: "🗓️",
    AutoSourceType.IS_WORKDAY: "🏢",
}

CALENDAR_OPTION_LABELS: dict[AutoSourceType, dict[int, str]] = {
    AutoSourceType.DAY_OF_WEEK: {
        1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс",
    },
    AutoSourceType.MONTH: {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
    },
    AutoSourceType.IS_WORKDAY: {
        1: "Рабочий день", 2: "Выходной",
    },
}

_CALENDAR_TYPES: frozenset[AutoSourceType] = frozenset({
    AutoSourceType.DAY_OF_WEEK,
    AutoSourceType.MONTH,
    AutoSourceType.IS_WORKDAY,
})

_ROLLING_AVG_TYPES: frozenset[AutoSourceType] = frozenset({AutoSourceType.ROLLING_AVG})

_DELTA_TYPES: frozenset[AutoSourceType] = frozenset({
    AutoSourceType.DELTA,
    AutoSourceType.TREND,
    AutoSourceType.RANGE,
    AutoSourceType.FREE_CP_MAX,
    AutoSourceType.FREE_CP_MIN,
    AutoSourceType.FREE_CP_RANGE,
})

# Legacy auto source type values for backward compat parsing
_LEGACY_AUTO_TYPE_MAP: dict[str, str] = {
    "slot_max": "checkpoint_max",
    "slot_min": "checkpoint_min",
}


@dataclass(frozen=True, slots=True)
class SourceKey:
    metric_id: int | None = None
    checkpoint_id: int | None = None
    interval_id: int | None = None
    enum_option_id: int | None = None
    auto_type: AutoSourceType | None = None
    auto_parent_metric_id: int | None = None
    auto_option_id: int | None = None

    @property
    def is_auto(self) -> bool:
        return self.auto_type is not None

    def to_str(self) -> str:
        if self.auto_type is not None:
            base: str
            if self.auto_parent_metric_id is not None:
                base = f"auto:{self.auto_type.value}:metric:{self.auto_parent_metric_id}"
            else:
                base = f"auto:{self.auto_type.value}"
            if self.auto_option_id is not None:
                return f"{base}:opt:{self.auto_option_id}"
            return base

        parts: list[str] = [f"metric:{self.metric_id}"]
        if self.enum_option_id is not None:
            parts.append(f"enum_opt:{self.enum_option_id}")
        if self.checkpoint_id is not None:
            parts.append(f"checkpoint:{self.checkpoint_id}")
        if self.interval_id is not None:
            parts.append(f"interval:{self.interval_id}")
        return ":".join(parts)

    @staticmethod
    def parse(key: str) -> SourceKey:
        if key.startswith("auto:"):
            rest = key[5:]
            auto_option_id: int | None = None
            # Extract :opt:N suffix if present
            if ":opt:" in rest:
                rest, _, opt_str = rest.rpartition(":opt:")
                auto_option_id = int(opt_str)
            # auto:{type}:metric:{id} or auto:{type}
            if ":metric:" in rest:
                type_str, _, mid_str = rest.partition(":metric:")
                # Backward compat: slot_max → checkpoint_max
                type_str = _LEGACY_AUTO_TYPE_MAP.get(type_str, type_str)
                return SourceKey(
                    auto_type=AutoSourceType(type_str),
                    auto_parent_metric_id=int(mid_str),
                    auto_option_id=auto_option_id,
                )
            type_str = rest
            type_str = _LEGACY_AUTO_TYPE_MAP.get(type_str, type_str)
            return SourceKey(auto_type=AutoSourceType(type_str), auto_option_id=auto_option_id)

        # metric:{id}[:enum_opt:{oid}][:checkpoint:{cpid}][:interval:{ivid}]
        # Legacy: metric:{id}[:enum_opt:{oid}][:slot:{sid}]
        tokens = key.split(":")
        metric_id: int | None = None
        checkpoint_id: int | None = None
        interval_id: int | None = None
        enum_option_id: int | None = None

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "metric" and i + 1 < len(tokens):
                metric_id = int(tokens[i + 1])
                i += 2
            elif tok == "checkpoint" and i + 1 < len(tokens):
                checkpoint_id = int(tokens[i + 1])
                i += 2
            elif tok == "interval" and i + 1 < len(tokens):
                interval_id = int(tokens[i + 1])
                i += 2
            elif tok == "slot" and i + 1 < len(tokens):
                # Legacy: treat slot as checkpoint
                checkpoint_id = int(tokens[i + 1])
                i += 2
            elif tok == "enum_opt" and i + 1 < len(tokens):
                enum_option_id = int(tokens[i + 1])
                i += 2
            else:
                i += 1

        return SourceKey(
            metric_id=metric_id,
            checkpoint_id=checkpoint_id,
            interval_id=interval_id,
            enum_option_id=enum_option_id,
        )
