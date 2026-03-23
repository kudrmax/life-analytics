from __future__ import annotations

from typing import Any, ClassVar

from app.analytics.correlation_math import confidence_interval_from_r, p_value_from_r
from app.analytics.quality import QualityAssessor
from app.metric_helpers import is_blocked, PRIVATE_MASK, PRIVATE_ICON
from app.source_key import (
    AutoSourceType, SourceKey, AUTO_DISPLAY_NAMES, AUTO_ICONS,
    CALENDAR_OPTION_LABELS, STREAK_TYPES,
)


class PairFormatter:
    """Форматирование корреляционных пар для отображения."""

    CATEGORY_FILTERS: ClassVar[dict[str, str]] = {
        "sig_strong": "AND quality_issue IS NULL AND ABS(correlation) > 0.7",
        "sig_medium": "AND quality_issue IS NULL AND ABS(correlation) > 0.3 AND ABS(correlation) <= 0.7",
        "sig_weak": "AND quality_issue IS NULL AND ABS(correlation) <= 0.3",
        "maybe": "AND quality_issue IN ('wide_ci', 'fisher_exact_high_p')",
        "insig": "AND quality_issue IS NOT NULL AND quality_issue NOT IN ('wide_ci', 'fisher_exact_high_p')",
        "all": "",
    }

    def __init__(
        self,
        *,
        metric_icons: dict[int, str],
        enum_labels: dict[int, str],
        parent_names: dict[int, str],
        privacy_mode: bool = False,
        metrics_with_slots: set[int] | None = None,
    ) -> None:
        self._icons = metric_icons
        self._enum_labels = enum_labels
        self._parent_names = parent_names
        self._privacy_mode = privacy_mode
        self._metrics_with_slots = metrics_with_slots or set()

    def format_pair(self, p: dict[str, Any]) -> dict[str, Any]:
        """Полное форматирование одной пары: лейблы, иконки, хинты, CI, quality."""
        priv_a = p.get("private_a", False)
        priv_b = p.get("private_b", False)
        blocked_a = is_blocked(priv_a, self._privacy_mode)
        blocked_b = is_blocked(priv_b, self._privacy_mode)
        corr = p["correlation"]
        if corr is not None:
            hint_a, hint_a_pos, hint_b, hint_b_pos = self.corr_hint_words(p["type_a"], p["type_b"], corr)
        else:
            hint_a, hint_a_pos, hint_b, hint_b_pos = "", True, "", True

        sk_a = SourceKey.parse(p["source_key_a"])
        sk_b = SourceKey.parse(p["source_key_b"])

        label_a = PRIVATE_MASK if blocked_a else self.build_display_label(
            p["source_key_a"], p["name_a"], self._parent_names.get(sk_a.auto_parent_metric_id),
            metric_type=p["type_a"], has_slots=(p["metric_a_id"] in self._metrics_with_slots if p["metric_a_id"] else False),
        )
        label_b = PRIVATE_MASK if blocked_b else self.build_display_label(
            p["source_key_b"], p["name_b"], self._parent_names.get(sk_b.auto_parent_metric_id),
            metric_type=p["type_b"], has_slots=(p["metric_b_id"] in self._metrics_with_slots if p["metric_b_id"] else False),
        )
        icon_a = PRIVATE_ICON if blocked_a else self.resolve_icon(p["source_key_a"], p["icon_a"])
        icon_b = PRIVATE_ICON if blocked_b else self.resolve_icon(p["source_key_b"], p["icon_b"])

        def _option_label(sk: SourceKey, blocked: bool) -> str:
            if blocked:
                return ""
            if sk.auto_option_id is not None:
                if sk.auto_type in STREAK_TYPES:
                    return self._enum_labels.get(sk.auto_option_id, "")
                assert sk.auto_type is not None
                return CALENDAR_OPTION_LABELS.get(sk.auto_type, {}).get(sk.auto_option_id, "")
            if sk.enum_option_id:
                return self._enum_labels.get(sk.enum_option_id, "")
            return ""

        option_a = _option_label(sk_a, blocked_a)
        option_b = _option_label(sk_b, blocked_b)

        ci = confidence_interval_from_r(corr, p["data_points"]) if corr is not None else None

        return {
            "label_a": label_a,
            "label_b": label_b,
            "option_a": option_a,
            "option_b": option_b,
            "type_a": p["type_a"],
            "type_b": p["type_b"],
            "icon_a": icon_a,
            "icon_b": icon_b,
            "slot_label_a": p["slot_label_a"] or "",
            "slot_label_b": p["slot_label_b"] or "",
            "correlation": corr,
            "data_points": p["data_points"],
            "lag_days": p["lag_days"],
            "p_value": p["p_value"] if p["p_value"] is not None else (round(p_value_from_r(corr, p["data_points"]), 4) if corr is not None else None),
            "ci_lower": ci[0] if ci else None,
            "ci_upper": ci[1] if ci else None,
            "metric_a_id": p["metric_a_id"],
            "metric_b_id": p["metric_b_id"],
            "pair_id": p["pair_id"],
            "hint_a": "" if blocked_a else hint_a,
            "hint_b": "" if blocked_b else hint_b,
            "hint_a_positive": hint_a_pos,
            "hint_b_positive": hint_b_pos,
            "description_a": "" if blocked_a else (p.get("description_a") or ""),
            "description_b": "" if blocked_b else (p.get("description_b") or ""),
            "private_a": priv_a,
            "private_b": priv_b,
            "quality_issue": p.get("quality_issue"),
            "quality_issue_label": QualityAssessor.LABELS.get(p.get("quality_issue")) if p.get("quality_issue") else None,
            "quality_severity": QualityAssessor.SEVERITY.get(p.get("quality_issue")) if p.get("quality_issue") else None,
        }

    def resolve_icon(self, source_key_str: str, db_icon: str | None) -> str:
        """Resolve icon from source_key or metric ID."""
        if db_icon:
            return db_icon
        sk = SourceKey.parse(source_key_str)
        if sk.auto_type and sk.auto_type in AUTO_ICONS:
            return AUTO_ICONS[sk.auto_type]
        if sk.auto_parent_metric_id is not None:
            return self._icons.get(sk.auto_parent_metric_id, "")
        return ""

    @staticmethod
    def build_display_label(
        source_key_str: str,
        metric_name: str | None,
        parent_metric_name: str | None,
        metric_type: str | None = None,
        has_slots: bool = False,
    ) -> str:
        """Build human-readable label for a correlation source."""
        sk = SourceKey.parse(source_key_str)
        if sk.auto_type:
            display = AUTO_DISPLAY_NAMES.get(sk.auto_type)
            if display:
                if sk.auto_option_id is not None:
                    option_labels = CALENDAR_OPTION_LABELS.get(sk.auto_type, {})
                    opt_label = option_labels.get(sk.auto_option_id, str(sk.auto_option_id))
                    return f"{display}: {opt_label}"
                return display
            if sk.auto_type == AutoSourceType.NONZERO and parent_metric_name:
                return f"{parent_metric_name}: не ноль"
            if sk.auto_type == AutoSourceType.NOTE_COUNT and parent_metric_name:
                return f"{parent_metric_name}: кол-во заметок"
            if sk.auto_type == AutoSourceType.SLOT_MAX and parent_metric_name:
                return f"{parent_metric_name}: максимум"
            if sk.auto_type == AutoSourceType.SLOT_MIN and parent_metric_name:
                return f"{parent_metric_name}: минимум"
            if sk.auto_type == AutoSourceType.ROLLING_AVG and sk.auto_option_id and parent_metric_name:
                return f"{parent_metric_name}: среднее {sk.auto_option_id} дн."
            if sk.auto_type == AutoSourceType.STREAK_TRUE and parent_metric_name:
                return f"{parent_metric_name}: серия подряд (да)"
            if sk.auto_type == AutoSourceType.STREAK_FALSE and parent_metric_name:
                return f"{parent_metric_name}: серия подряд (нет)"
            return "Авто-источник"
        # Bool aggregate with slots — annotate "(хоть раз)"
        if metric_type == "bool" and has_slots and sk.slot_id is None:
            return f"{metric_name} (хоть раз)" if metric_name else "Удалённая метрика"
        return metric_name or "Удалённая метрика"

    @staticmethod
    def corr_type_words(type_: str) -> tuple[str, str]:
        """Return (positive_word, negative_word) for a metric type in correlation context."""
        if type_ in ("bool", "enum_bool"):
            return ("да", "нет")
        if type_ == "time":
            return ("позже", "раньше")
        if type_ == "scale":
            return ("выше", "ниже")
        return ("больше", "меньше")

    @staticmethod
    def corr_hint_words(type_a: str, type_b: str, r: float) -> tuple[str, bool, str, bool]:
        """Return (hint_a, hint_a_positive, hint_b, hint_b_positive)."""
        if not type_a or not type_b:
            return ("", True, "", True)
        pos_a, _ = PairFormatter.corr_type_words(type_a)
        pos_b, neg_b = PairFormatter.corr_type_words(type_b)
        hint_a = pos_a
        hint_b = pos_b if r > 0 else neg_b
        return (hint_a, True, hint_b, r > 0)

    @staticmethod
    def build_display_stats(stats: dict[str, Any], mt: str) -> list[dict[str, str]]:
        """Build a list of {label, value} for UI display based on metric type."""
        rows: list[dict[str, str]] = []
        rows.append({"label": "Заполнение", "value": f"{stats['fill_rate']}%"})
        rt = stats.get("result_type")
        if mt == "bool" or (mt == "computed" and rt == "bool"):
            if "yes_percent" in stats:
                rows.append({"label": "Да", "value": f"{stats['yes_percent']}%"})
        elif mt == "time" or (mt == "computed" and rt == "time"):
            if stats.get("average"):
                rows.append({"label": "Среднее", "value": str(stats["average"])})
        elif mt == "scale":
            if stats.get("average") is not None:
                rows.append({"label": "Среднее", "value": f"{stats['average']}%"})
        elif mt == "duration" or (mt == "computed" and rt == "duration"):
            if stats.get("average"):
                rows.append({"label": "Среднее", "value": str(stats["average"])})
        elif mt == "text":
            if stats.get("average_per_day") is not None:
                rows.append({"label": "Среднее/день", "value": str(stats["average_per_day"])})
        elif mt == "enum":
            if stats.get("most_common"):
                rows.append({"label": "Частый", "value": str(stats["most_common"])})
        else:
            # number, computed float/int
            if stats.get("average") is not None:
                rows.append({"label": "Среднее", "value": str(stats["average"])})
            if stats.get("min") is not None and stats.get("max") is not None:
                rows.append({"label": "Диапазон", "value": f"{stats['min']} – {stats['max']}"})
        return rows
