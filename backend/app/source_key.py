"""Deterministic source keys for correlation pairs.

SourceKey encodes which data source a correlation side refers to:
- metric:{id}                                    — plain metric (aggregate)
- metric:{id}:slot:{slot_id}                     — metric with slot
- metric:{id}:enum_opt:{opt_id}                  — enum option (aggregate)
- metric:{id}:enum_opt:{opt_id}:slot:{slot_id}   — enum option with slot
- auto:nonzero:metric:{id}                       — nonzero for a metric
- auto:note_count:metric:{id}                    — note count for text metric
- auto:day_of_week                               — calendar
- auto:month
- auto:week_number
- auto:aw_active                                 — ActivityWatch active screen time
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AutoSourceType(str, Enum):
    NONZERO = "nonzero"
    NOTE_COUNT = "note_count"
    DAY_OF_WEEK = "day_of_week"
    MONTH = "month"
    WEEK_NUMBER = "week_number"
    AW_ACTIVE = "aw_active"


AUTO_DISPLAY_NAMES: dict[AutoSourceType, str] = {
    AutoSourceType.DAY_OF_WEEK: "День недели",
    AutoSourceType.MONTH: "Месяц",
    AutoSourceType.WEEK_NUMBER: "Неделя года",
    AutoSourceType.AW_ACTIVE: "Экранное время (активное)",
}

AUTO_ICONS: dict[AutoSourceType, str] = {
    AutoSourceType.DAY_OF_WEEK: "📅",
    AutoSourceType.MONTH: "🗓️",
    AutoSourceType.WEEK_NUMBER: "📆",
}

_CALENDAR_TYPES: frozenset[AutoSourceType] = frozenset({
    AutoSourceType.DAY_OF_WEEK,
    AutoSourceType.MONTH,
    AutoSourceType.WEEK_NUMBER,
})


@dataclass(frozen=True, slots=True)
class SourceKey:
    metric_id: int | None = None
    slot_id: int | None = None
    enum_option_id: int | None = None
    auto_type: AutoSourceType | None = None
    auto_parent_metric_id: int | None = None

    @property
    def is_auto(self) -> bool:
        return self.auto_type is not None

    def to_str(self) -> str:
        if self.auto_type is not None:
            if self.auto_parent_metric_id is not None:
                return f"auto:{self.auto_type.value}:metric:{self.auto_parent_metric_id}"
            return f"auto:{self.auto_type.value}"

        parts: list[str] = [f"metric:{self.metric_id}"]
        if self.enum_option_id is not None:
            parts.append(f"enum_opt:{self.enum_option_id}")
        if self.slot_id is not None:
            parts.append(f"slot:{self.slot_id}")
        return ":".join(parts)

    @staticmethod
    def parse(key: str) -> SourceKey:
        if key.startswith("auto:"):
            rest = key[5:]
            # auto:{type}:metric:{id} or auto:{type}
            if ":metric:" in rest:
                type_str, _, mid_str = rest.partition(":metric:")
                return SourceKey(
                    auto_type=AutoSourceType(type_str),
                    auto_parent_metric_id=int(mid_str),
                )
            return SourceKey(auto_type=AutoSourceType(rest))

        # metric:{id}[:enum_opt:{oid}][:slot:{sid}]
        tokens = key.split(":")
        metric_id: int | None = None
        slot_id: int | None = None
        enum_option_id: int | None = None

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "metric" and i + 1 < len(tokens):
                metric_id = int(tokens[i + 1])
                i += 2
            elif tok == "slot" and i + 1 < len(tokens):
                slot_id = int(tokens[i + 1])
                i += 2
            elif tok == "enum_opt" and i + 1 < len(tokens):
                enum_option_id = int(tokens[i + 1])
                i += 2
            else:
                i += 1

        return SourceKey(
            metric_id=metric_id,
            slot_id=slot_id,
            enum_option_id=enum_option_id,
        )
