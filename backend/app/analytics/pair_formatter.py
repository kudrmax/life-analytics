from __future__ import annotations

from typing import Any, ClassVar

from app.analytics.correlation_math import confidence_interval_from_r, p_value_from_r
from app.analytics.quality import QualityAssessor
from app.correlation_config import ThresholdsConfig
from app.domain.constants import CORRELATION_THRESHOLD_MODERATE, CORRELATION_THRESHOLD_STRONG
from app.domain.enums import MetricType
from app.domain.privacy import is_blocked, PRIVATE_MASK, PRIVATE_ICON
from app.source_key import (
    AutoSourceType, SourceKey, AUTO_DISPLAY_NAMES, AUTO_ICONS,
    CALENDAR_OPTION_LABELS, STREAK_TYPES,
)


class PairFormatter:
    """Форматирование корреляционных пар для отображения."""

    CATEGORY_FILTERS: ClassVar[dict[str, str]] = {
        "sig_strong": f"AND quality_issue IS NULL AND ABS(correlation) > {CORRELATION_THRESHOLD_STRONG}",
        "sig_medium": f"AND quality_issue IS NULL AND ABS(correlation) > {CORRELATION_THRESHOLD_MODERATE} AND ABS(correlation) <= {CORRELATION_THRESHOLD_STRONG}",
        "sig_weak": f"AND quality_issue IS NULL AND ABS(correlation) <= {CORRELATION_THRESHOLD_MODERATE}",
        "maybe": "AND quality_issue IN ('wide_ci', 'fisher_exact_high_p', 'fdr_high_p_value')",
        "insig": "AND quality_issue IS NOT NULL AND quality_issue NOT IN ('wide_ci', 'fisher_exact_high_p', 'fdr_high_p_value')",
        "all": "",
    }

    @staticmethod
    def category_filter_sql(category: str, thresholds: ThresholdsConfig) -> str:
        """Build SQL WHERE clause for a category using configurable thresholds."""
        strong = thresholds.strong_correlation
        moderate = thresholds.moderate_correlation
        filters: dict[str, str] = {
            "sig_strong": f"AND quality_issue IS NULL AND ABS(correlation) > {strong}",
            "sig_medium": f"AND quality_issue IS NULL AND ABS(correlation) > {moderate} AND ABS(correlation) <= {strong}",
            "sig_weak": f"AND quality_issue IS NULL AND ABS(correlation) <= {moderate}",
            "maybe": "AND quality_issue IN ('wide_ci', 'fisher_exact_high_p', 'fdr_high_p_value')",
            "insig": "AND quality_issue IS NOT NULL AND quality_issue NOT IN ('wide_ci', 'fisher_exact_high_p', 'fdr_high_p_value')",
            "all": "",
        }
        return filters.get(category, "")

    def __init__(
        self,
        *,
        metric_icons: dict[int, str],
        enum_labels: dict[int, str],
        parent_names: dict[int, str],
        privacy_mode: bool = False,
        metrics_with_checkpoints: set[int] | None = None,
        checkpoint_labels: dict[int, str] | None = None,
        checkpoint_ordering: dict[int, list[int]] | None = None,
        interval_labels: dict[int, str] | None = None,
    ) -> None:
        self._icons = metric_icons
        self._enum_labels = enum_labels
        self._parent_names = parent_names
        self._privacy_mode = privacy_mode
        self._metrics_with_checkpoints = metrics_with_checkpoints or set()
        self._checkpoint_labels = checkpoint_labels or {}
        self._checkpoint_ordering = checkpoint_ordering or {}
        self._interval_labels = interval_labels or {}

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
            metric_type=p["type_a"], has_checkpoints=(p["metric_a_id"] in self._metrics_with_checkpoints if p["metric_a_id"] else False),
            checkpoint_labels=self._checkpoint_labels, checkpoint_ordering=self._checkpoint_ordering,
            interval_labels=self._interval_labels,
        )
        label_b = PRIVATE_MASK if blocked_b else self.build_display_label(
            p["source_key_b"], p["name_b"], self._parent_names.get(sk_b.auto_parent_metric_id),
            metric_type=p["type_b"], has_checkpoints=(p["metric_b_id"] in self._metrics_with_checkpoints if p["metric_b_id"] else False),
            checkpoint_labels=self._checkpoint_labels, checkpoint_ordering=self._checkpoint_ordering,
            interval_labels=self._interval_labels,
        )
        source_tag_a = "" if blocked_a else self.build_source_tag(
            p["source_key_a"], metric_type=p["type_a"],
            has_checkpoints=(p["metric_a_id"] in self._metrics_with_checkpoints if p["metric_a_id"] else False),
        )
        source_tag_b = "" if blocked_b else self.build_source_tag(
            p["source_key_b"], metric_type=p["type_b"],
            has_checkpoints=(p["metric_b_id"] in self._metrics_with_checkpoints if p["metric_b_id"] else False),
        )
        delta_a = ("", "") if blocked_a else self.build_delta_labels(
            p["source_key_a"], self._checkpoint_labels, self._checkpoint_ordering,
        )
        delta_b = ("", "") if blocked_b else self.build_delta_labels(
            p["source_key_b"], self._checkpoint_labels, self._checkpoint_ordering,
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
            "source_key_a": p["source_key_a"],
            "source_key_b": p["source_key_b"],
            "status": p.get("pair_status"),
            "source_tag_a": source_tag_a,
            "source_tag_b": source_tag_b,
            "delta_start_a": delta_a[0],
            "delta_end_a": delta_a[1],
            "delta_start_b": delta_b[0],
            "delta_end_b": delta_b[1],
            "option_a": option_a,
            "option_b": option_b,
            "type_a": p["type_a"],
            "type_b": p["type_b"],
            "icon_a": icon_a,
            "icon_b": icon_b,
            "binding_label_a": self._resolve_binding_label(p, "a"),
            "binding_label_b": self._resolve_binding_label(p, "b"),
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
            "adjusted_p_value": p.get("adjusted_p_value"),
        }

    def _resolve_binding_label(self, p: dict[str, Any], side: str) -> str:
        # Direct labels from SQL JOIN (fetch_pairs_page)
        cp_label = p.get(f"checkpoint_label_{side}")
        if cp_label:
            return cp_label
        iv_start = p.get(f"interval_start_label_{side}")
        iv_end = p.get(f"interval_end_label_{side}")
        if iv_start and iv_end:
            return f"{iv_start} → {iv_end}"
        # Fallback to loaded label dicts
        checkpoint_id = p.get(f"checkpoint_{side}_id")
        if checkpoint_id and checkpoint_id in self._checkpoint_labels:
            return self._checkpoint_labels[checkpoint_id]
        interval_id = p.get(f"interval_{side}_id")
        if interval_id and interval_id in self._interval_labels:
            return self._interval_labels[interval_id]
        return ""

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
        has_checkpoints: bool = False,
        checkpoint_labels: dict[int, str] | None = None,
        checkpoint_ordering: dict[int, list[int]] | None = None,
        interval_labels: dict[int, str] | None = None,
    ) -> str:
        """Build human-readable label — pure metric name only.

        Qualifiers (auto-source tags, checkpoint/interval suffixes) are returned
        separately by build_source_tag() and build_delta_labels().
        """
        sk = SourceKey.parse(source_key_str)
        if sk.auto_type:
            # Calendar auto-sources (no parent metric) — keep full display name
            display = AUTO_DISPLAY_NAMES.get(sk.auto_type)
            if display:
                if sk.auto_option_id is not None:
                    option_labels = CALENDAR_OPTION_LABELS.get(sk.auto_type, {})
                    opt_label = option_labels.get(sk.auto_option_id, str(sk.auto_option_id))
                    return f"{display}: {opt_label}"
                return display
            # Metric-derived auto-sources — return only parent name
            if parent_metric_name:
                return parent_metric_name
            return "Авто-источник"
        return metric_name or "Удалённая метрика"

    @staticmethod
    def build_source_tag(
        source_key_str: str,
        metric_type: str | None = None,
        has_checkpoints: bool = False,
    ) -> str:
        """Build qualifier tag for a correlation source (shown as badge)."""
        sk = SourceKey.parse(source_key_str)
        if sk.auto_type:
            # Calendar auto-sources have no tag (label already contains full info)
            if AUTO_DISPLAY_NAMES.get(sk.auto_type):
                return ""
            tag_map: dict[AutoSourceType, str] = {
                AutoSourceType.NONZERO: "не ноль",
                AutoSourceType.NOTE_COUNT: "кол-во заметок",
                AutoSourceType.CHECKPOINT_MAX: "максимум",
                AutoSourceType.CHECKPOINT_MIN: "минимум",
                AutoSourceType.STREAK_TRUE: "серия подряд (да)",
                AutoSourceType.STREAK_FALSE: "серия подряд (нет)",
                AutoSourceType.DELTA: "Δ",
                AutoSourceType.TREND: "тренд",
                AutoSourceType.RANGE: "размах",
                AutoSourceType.FREE_CP_MAX: "максимум",
                AutoSourceType.FREE_CP_MIN: "минимум",
                AutoSourceType.FREE_CP_RANGE: "размах",
                AutoSourceType.FREE_IV_MAX: "максимум",
                AutoSourceType.FREE_IV_MIN: "минимум",
                AutoSourceType.FREE_IV_RANGE: "размах",
                AutoSourceType.FREE_IV_COUNT: "кол-во записей",
                AutoSourceType.FREE_IV_AVG_DUR: "ср. длительность",
                AutoSourceType.FREE_IV_MAX_DUR: "макс. длительность",
                AutoSourceType.FREE_IV_MIN_DUR: "мин. длительность",
            }
            if sk.auto_type in tag_map:
                return tag_map[sk.auto_type]
            if sk.auto_type == AutoSourceType.ROLLING_AVG and sk.auto_option_id:
                return f"среднее {sk.auto_option_id} дн."
            return ""
        # Bool aggregate with checkpoints
        if metric_type == MetricType.bool and has_checkpoints and sk.checkpoint_id is None:
            return "хоть раз"
        return ""

    @staticmethod
    def build_delta_labels(
        source_key_str: str,
        checkpoint_labels: dict[int, str] | None = None,
        checkpoint_ordering: dict[int, list[int]] | None = None,
    ) -> tuple[str, str]:
        """Return (start_label, end_label) for delta auto-sources."""
        sk = SourceKey.parse(source_key_str)
        if sk.auto_type != AutoSourceType.DELTA:
            return ("", "")
        if not checkpoint_labels or not checkpoint_ordering or sk.auto_parent_metric_id is None:
            return ("", "")
        ordered = checkpoint_ordering.get(sk.auto_parent_metric_id, [])
        start_label = checkpoint_labels.get(sk.auto_option_id, "?") if sk.auto_option_id else "?"
        end_label = "?"
        if sk.auto_option_id is not None:
            for idx_s, cid in enumerate(ordered):
                if cid == sk.auto_option_id and idx_s + 1 < len(ordered):
                    end_label = checkpoint_labels.get(ordered[idx_s + 1], "?")
                    break
        return (start_label, end_label)

    @staticmethod
    def corr_type_words(type_: str) -> tuple[str, str]:
        """Return (positive_word, negative_word) for a metric type in correlation context."""
        if type_ in (MetricType.bool, "enum_bool"):
            return ("да", "нет")
        if type_ == MetricType.time:
            return ("позже", "раньше")
        if type_ == MetricType.scale:
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
        if mt == MetricType.bool or (mt == MetricType.computed and rt == MetricType.bool):
            if "yes_percent" in stats:
                rows.append({"label": "Да", "value": f"{stats['yes_percent']}%"})
        elif mt == MetricType.time or (mt == MetricType.computed and rt == MetricType.time):
            if stats.get("average"):
                rows.append({"label": "Среднее", "value": str(stats["average"])})
        elif mt == MetricType.scale:
            if stats.get("average") is not None:
                rows.append({"label": "Среднее", "value": f"{stats['average']}%"})
        elif mt == MetricType.duration or (mt == MetricType.computed and rt == MetricType.duration):
            if stats.get("average"):
                rows.append({"label": "Среднее", "value": str(stats["average"])})
        elif mt == MetricType.text:
            if stats.get("average_per_day") is not None:
                rows.append({"label": "Среднее/день", "value": str(stats["average_per_day"])})
        elif mt == MetricType.enum:
            if stats.get("most_common"):
                rows.append({"label": "Частый", "value": str(stats["most_common"])})
        else:
            # number, computed float/int
            if stats.get("average") is not None:
                rows.append({"label": "Среднее", "value": str(stats["average"])})
            if stats.get("min") is not None and stats.get("max") is not None:
                rows.append({"label": "Диапазон", "value": f"{stats['min']} – {stats['max']}"})
        return rows
