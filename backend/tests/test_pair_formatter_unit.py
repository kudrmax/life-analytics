"""Unit tests for PairFormatter class."""
from __future__ import annotations

import unittest

from app.analytics.pair_formatter import PairFormatter
from app.source_key import AutoSourceType, SourceKey


def _make_pair(**overrides: object) -> dict:
    """Create a minimal pair dict with sensible defaults."""
    base = {
        "pair_id": 1,
        "correlation": 0.75,
        "data_points": 30,
        "lag_days": 0,
        "p_value": 0.001,
        "type_a": "number",
        "type_b": "number",
        "source_key_a": "metric:1",
        "source_key_b": "metric:2",
        "name_a": "MetricA",
        "name_b": "MetricB",
        "icon_a": "💪",
        "icon_b": "🏃",
        "metric_a_id": 1,
        "metric_b_id": 2,
        "checkpoint_a_id": None,
        "checkpoint_b_id": None,
        "interval_a_id": None,
        "interval_b_id": None,
        "private_a": False,
        "private_b": False,
        "quality_issue": None,
    }
    base.update(overrides)
    return base


def _make_formatter(**overrides: object) -> PairFormatter:
    defaults = {
        "metric_icons": {},
        "enum_labels": {},
        "parent_names": {},
        "privacy_mode": False,
        "metrics_with_checkpoints": None,
    }
    defaults.update(overrides)
    return PairFormatter(**defaults)


# ─── corr_type_words ──────────────────────────────────────────


class TestCorrTypeWords(unittest.TestCase):
    def test_bool(self) -> None:
        assert PairFormatter.corr_type_words("bool") == ("да", "нет")

    def test_enum_bool(self) -> None:
        assert PairFormatter.corr_type_words("enum_bool") == ("да", "нет")

    def test_time(self) -> None:
        assert PairFormatter.corr_type_words("time") == ("позже", "раньше")

    def test_scale(self) -> None:
        assert PairFormatter.corr_type_words("scale") == ("выше", "ниже")

    def test_number(self) -> None:
        assert PairFormatter.corr_type_words("number") == ("больше", "меньше")

    def test_duration(self) -> None:
        assert PairFormatter.corr_type_words("duration") == ("больше", "меньше")

    def test_unknown(self) -> None:
        assert PairFormatter.corr_type_words("whatever") == ("больше", "меньше")


# ─── corr_hint_words ──────────────────────────────────────────


class TestCorrHintWords(unittest.TestCase):
    def test_bool_bool_positive(self) -> None:
        result = PairFormatter.corr_hint_words("bool", "bool", 0.8)
        assert result == ("да", True, "да", True)

    def test_bool_bool_negative(self) -> None:
        result = PairFormatter.corr_hint_words("bool", "bool", -0.8)
        assert result == ("да", True, "нет", False)

    def test_time_number_positive(self) -> None:
        result = PairFormatter.corr_hint_words("time", "number", 0.5)
        assert result == ("позже", True, "больше", True)

    def test_scale_scale_negative(self) -> None:
        result = PairFormatter.corr_hint_words("scale", "scale", -0.3)
        assert result == ("выше", True, "ниже", False)

    def test_empty_type_a(self) -> None:
        result = PairFormatter.corr_hint_words("", "bool", 0.5)
        assert result == ("", True, "", True)

    def test_empty_type_b(self) -> None:
        result = PairFormatter.corr_hint_words("bool", "", 0.5)
        assert result == ("", True, "", True)


# ─── build_display_label ──────────────────────────────────────


class TestBuildDisplayLabel(unittest.TestCase):
    """build_display_label returns only the metric name (no qualifiers)."""

    def test_regular_metric(self) -> None:
        result = PairFormatter.build_display_label("metric:5", "Настроение", None)
        assert result == "Настроение"

    def test_deleted_metric(self) -> None:
        result = PairFormatter.build_display_label("metric:5", None, None)
        assert result == "Удалённая метрика"

    def test_bool_with_checkpoints_aggregate(self) -> None:
        result = PairFormatter.build_display_label(
            "metric:5", "Спорт", None, metric_type="bool", has_checkpoints=True,
        )
        assert result == "Спорт"

    def test_bool_with_checkpoints_deleted(self) -> None:
        result = PairFormatter.build_display_label(
            "metric:5", None, None, metric_type="bool", has_checkpoints=True,
        )
        assert result == "Удалённая метрика"

    def test_bool_with_checkpoint_id_no_annotation(self) -> None:
        result = PairFormatter.build_display_label(
            "metric:5:checkpoint:3", "Спорт", None, metric_type="bool", has_checkpoints=True,
        )
        assert result == "Спорт"

    def test_auto_nonzero(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Калории")
        assert result == "Калории"

    def test_auto_note_count(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Дневник")
        assert result == "Дневник"

    def test_auto_checkpoint_max(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Давление")
        assert result == "Давление"

    def test_auto_checkpoint_min(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Давление")
        assert result == "Давление"

    def test_auto_rolling_avg(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Вес")
        assert result == "Вес"

    def test_auto_streak_true(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Медитация")
        assert result == "Медитация"

    def test_auto_streak_false(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=5)
        result = PairFormatter.build_display_label(sk.to_str(), None, "Медитация")
        assert result == "Медитация"

    def test_auto_day_of_week_with_option(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        result = PairFormatter.build_display_label(sk.to_str(), None, None)
        assert result == "День недели: Пн"

    def test_auto_month_with_option(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.MONTH, auto_option_id=6)
        result = PairFormatter.build_display_label(sk.to_str(), None, None)
        assert result == "Месяц: Июнь"

    def test_auto_is_workday(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.IS_WORKDAY, auto_option_id=1)
        result = PairFormatter.build_display_label(sk.to_str(), None, None)
        assert result == "Календарный тип: Рабочий день"

    def test_auto_without_parent_name(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=99)
        result = PairFormatter.build_display_label(sk.to_str(), None, None)
        assert result == "Авто-источник"


# ─── build_source_tag ────────────────────────────────────────


class TestBuildSourceTag(unittest.TestCase):
    def test_regular_metric(self) -> None:
        assert PairFormatter.build_source_tag("metric:5") == ""

    def test_nonzero(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "не ноль"

    def test_note_count(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "кол-во заметок"

    def test_checkpoint_max(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "максимум"

    def test_checkpoint_min(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "минимум"

    def test_rolling_avg(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        assert PairFormatter.build_source_tag(sk.to_str()) == "среднее 7 дн."

    def test_streak_true(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "серия подряд (да)"

    def test_streak_false(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "серия подряд (нет)"

    def test_delta(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DELTA, auto_parent_metric_id=5, auto_option_id=10)
        assert PairFormatter.build_source_tag(sk.to_str()) == "Δ"

    def test_trend(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.TREND, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "тренд"

    def test_range(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.RANGE, auto_parent_metric_id=5)
        assert PairFormatter.build_source_tag(sk.to_str()) == "размах"

    def test_calendar_no_tag(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        assert PairFormatter.build_source_tag(sk.to_str()) == ""

    def test_bool_aggregate_with_checkpoints(self) -> None:
        result = PairFormatter.build_source_tag("metric:5", metric_type="bool", has_checkpoints=True)
        assert result == "хоть раз"

    def test_bool_with_checkpoint_id_no_tag(self) -> None:
        result = PairFormatter.build_source_tag(
            "metric:5:checkpoint:3", metric_type="bool", has_checkpoints=True,
        )
        assert result == ""


# ─── build_delta_labels ──────────────────────────────────────


class TestBuildDeltaLabels(unittest.TestCase):
    def test_non_delta_returns_empty(self) -> None:
        assert PairFormatter.build_delta_labels("metric:5") == ("", "")

    def test_delta_with_ordering(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DELTA, auto_parent_metric_id=5, auto_option_id=10)
        result = PairFormatter.build_delta_labels(
            sk.to_str(),
            checkpoint_labels={10: "Утро", 20: "День"},
            checkpoint_ordering={5: [10, 20]},
        )
        assert result == ("Утро", "День")

    def test_delta_without_ordering(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DELTA, auto_parent_metric_id=5, auto_option_id=10)
        result = PairFormatter.build_delta_labels(sk.to_str())
        assert result == ("", "")


# ─── resolve_icon ─────────────────────────────────────────────


class TestResolveIcon(unittest.TestCase):
    def test_db_icon_takes_priority(self) -> None:
        fmt = _make_formatter()
        assert fmt.resolve_icon("metric:1", "🎯") == "🎯"

    def test_auto_with_known_icon(self) -> None:
        from app.source_key import AUTO_ICONS
        fmt = _make_formatter()
        sk = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        result = fmt.resolve_icon(sk.to_str(), None)
        assert result == AUTO_ICONS[AutoSourceType.DAY_OF_WEEK]

    def test_auto_with_parent_icon(self) -> None:
        fmt = _make_formatter(metric_icons={5: "💪"})
        sk = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=5)
        assert fmt.resolve_icon(sk.to_str(), None) == "💪"

    def test_regular_no_icon(self) -> None:
        fmt = _make_formatter()
        assert fmt.resolve_icon("metric:1", None) == ""


# ─── build_display_stats ─────────────────────────────────────


class TestBuildDisplayStats(unittest.TestCase):
    def test_bool(self) -> None:
        stats = {"fill_rate": 80.0, "yes_percent": 60.0}
        result = PairFormatter.build_display_stats(stats, "bool")
        assert result[0] == {"label": "Заполнение", "value": "80.0%"}
        assert result[1] == {"label": "Да", "value": "60.0%"}

    def test_time(self) -> None:
        stats = {"fill_rate": 90.0, "average": "08:30"}
        result = PairFormatter.build_display_stats(stats, "time")
        assert len(result) == 2
        assert result[1] == {"label": "Среднее", "value": "08:30"}

    def test_scale(self) -> None:
        stats = {"fill_rate": 70.0, "average": 65.5}
        result = PairFormatter.build_display_stats(stats, "scale")
        assert result[1] == {"label": "Среднее", "value": "65.5%"}

    def test_duration(self) -> None:
        stats = {"fill_rate": 50.0, "average": "1ч 30м"}
        result = PairFormatter.build_display_stats(stats, "duration")
        assert result[1] == {"label": "Среднее", "value": "1ч 30м"}

    def test_text(self) -> None:
        stats = {"fill_rate": 40.0, "average_per_day": 2.5}
        result = PairFormatter.build_display_stats(stats, "text")
        assert result[1] == {"label": "Среднее/день", "value": "2.5"}

    def test_enum(self) -> None:
        stats = {"fill_rate": 60.0, "most_common": "Хорошо"}
        result = PairFormatter.build_display_stats(stats, "enum")
        assert result[1] == {"label": "Частый", "value": "Хорошо"}

    def test_number_with_range(self) -> None:
        stats = {"fill_rate": 100.0, "average": 42.5, "min": 10, "max": 80}
        result = PairFormatter.build_display_stats(stats, "number")
        assert result[1] == {"label": "Среднее", "value": "42.5"}
        assert result[2] == {"label": "Диапазон", "value": "10 – 80"}

    def test_computed_bool(self) -> None:
        stats = {"fill_rate": 80.0, "yes_percent": 50.0, "result_type": "bool"}
        result = PairFormatter.build_display_stats(stats, "computed")
        assert result[1] == {"label": "Да", "value": "50.0%"}

    def test_computed_time(self) -> None:
        stats = {"fill_rate": 80.0, "average": "12:00", "result_type": "time"}
        result = PairFormatter.build_display_stats(stats, "computed")
        assert result[1] == {"label": "Среднее", "value": "12:00"}

    def test_only_fill_rate_when_no_data(self) -> None:
        stats = {"fill_rate": 0.0}
        result = PairFormatter.build_display_stats(stats, "bool")
        assert len(result) == 1
        assert result[0]["label"] == "Заполнение"


# ─── format_pair ──────────────────────────────────────────────


class TestFormatPair(unittest.TestCase):
    def test_basic_pair(self) -> None:
        fmt = _make_formatter()
        result = fmt.format_pair(_make_pair())
        assert result["label_a"] == "MetricA"
        assert result["label_b"] == "MetricB"
        assert result["source_tag_a"] == ""
        assert result["source_tag_b"] == ""
        assert result["delta_start_a"] == ""
        assert result["delta_end_a"] == ""
        assert result["delta_start_b"] == ""
        assert result["delta_end_b"] == ""
        assert result["correlation"] == 0.75
        assert result["data_points"] == 30
        assert result["pair_id"] == 1
        assert result["p_value"] == 0.001

    def test_privacy_blocked_a(self) -> None:
        fmt = _make_formatter(privacy_mode=True)
        pair = _make_pair(private_a=True)
        result = fmt.format_pair(pair)
        assert result["label_a"] == "***"
        assert result["icon_a"] == "🔒"
        assert result["hint_a"] == ""
        assert result["description_a"] == ""

    def test_privacy_blocked_both(self) -> None:
        fmt = _make_formatter(privacy_mode=True)
        pair = _make_pair(private_a=True, private_b=True)
        result = fmt.format_pair(pair)
        assert result["label_a"] == "***"
        assert result["label_b"] == "***"

    def test_not_blocked_when_privacy_off(self) -> None:
        fmt = _make_formatter(privacy_mode=False)
        pair = _make_pair(private_a=True)
        result = fmt.format_pair(pair)
        assert result["label_a"] == "MetricA"

    def test_p_value_fallback_computed(self) -> None:
        """When p_value is None, it should be computed from r and n."""
        fmt = _make_formatter()
        pair = _make_pair(p_value=None, correlation=0.9, data_points=50)
        result = fmt.format_pair(pair)
        assert result["p_value"] is not None
        assert result["p_value"] < 0.01

    def test_p_value_none_when_no_correlation(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(p_value=None, correlation=None)
        result = fmt.format_pair(pair)
        assert result["p_value"] is None

    def test_ci_computed(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(correlation=0.5, data_points=100)
        result = fmt.format_pair(pair)
        assert result["ci_lower"] is not None
        assert result["ci_upper"] is not None
        assert result["ci_lower"] < 0.5 < result["ci_upper"]

    def test_ci_none_when_no_correlation(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(correlation=None)
        result = fmt.format_pair(pair)
        assert result["ci_lower"] is None
        assert result["ci_upper"] is None

    def test_quality_issue_label_and_severity(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(quality_issue="high_p_value")
        result = fmt.format_pair(pair)
        assert result["quality_issue"] == "high_p_value"
        assert result["quality_issue_label"] is not None
        assert result["quality_severity"] == "bad"

    def test_no_quality_issue(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(quality_issue=None)
        result = fmt.format_pair(pair)
        assert result["quality_issue_label"] is None
        assert result["quality_severity"] is None

    def test_enum_option_label(self) -> None:
        fmt = _make_formatter(enum_labels={10: "Хорошо"})
        pair = _make_pair(source_key_a="metric:1:enum_opt:10")
        result = fmt.format_pair(pair)
        assert result["option_a"] == "Хорошо"

    def test_enum_option_blocked(self) -> None:
        fmt = _make_formatter(privacy_mode=True, enum_labels={10: "Хорошо"})
        pair = _make_pair(source_key_a="metric:1:enum_opt:10", private_a=True)
        result = fmt.format_pair(pair)
        assert result["option_a"] == ""

    def test_binding_labels_passed_through(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(checkpoint_a_id=1, checkpoint_b_id=2)
        result = fmt.format_pair(pair)
        assert "binding_label_a" in result
        assert "binding_label_b" in result

    def test_hints_with_positive_correlation(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(type_a="bool", type_b="number", correlation=0.8)
        result = fmt.format_pair(pair)
        assert result["hint_a"] == "да"
        assert result["hint_b"] == "больше"
        assert result["hint_b_positive"] is True

    def test_hints_with_negative_correlation(self) -> None:
        fmt = _make_formatter()
        pair = _make_pair(type_a="bool", type_b="number", correlation=-0.8)
        result = fmt.format_pair(pair)
        assert result["hint_b"] == "меньше"
        assert result["hint_b_positive"] is False


# ─── CATEGORY_FILTERS ─────────────────────────────────────────


class TestCategoryFilters(unittest.TestCase):
    def test_all_categories_present(self) -> None:
        expected = {"sig_strong", "sig_medium", "sig_weak", "maybe", "insig", "all"}
        assert set(PairFormatter.CATEGORY_FILTERS.keys()) == expected

    def test_all_is_empty(self) -> None:
        assert PairFormatter.CATEGORY_FILTERS["all"] == ""

    def test_sig_strong_has_07_threshold(self) -> None:
        assert "0.7" in PairFormatter.CATEGORY_FILTERS["sig_strong"]
