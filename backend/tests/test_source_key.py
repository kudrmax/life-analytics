"""Unit tests for app.source_key module."""

import unittest

from app.source_key import (
    AUTO_DISPLAY_NAMES,
    AUTO_ICONS,
    CALENDAR_OPTION_LABELS,
    ROLLING_AVG_WINDOWS,
    AutoSourceType,
    SourceKey,
    _CALENDAR_TYPES,
)


class TestAutoSourceType(unittest.TestCase):
    """Tests for AutoSourceType enum."""

    def test_nonzero_value(self) -> None:
        self.assertEqual(AutoSourceType.NONZERO.value, "nonzero")

    def test_note_count_value(self) -> None:
        self.assertEqual(AutoSourceType.NOTE_COUNT.value, "note_count")

    def test_day_of_week_value(self) -> None:
        self.assertEqual(AutoSourceType.DAY_OF_WEEK.value, "day_of_week")

    def test_month_value(self) -> None:
        self.assertEqual(AutoSourceType.MONTH.value, "month")

    def test_week_number_value(self) -> None:
        self.assertEqual(AutoSourceType.WEEK_NUMBER.value, "week_number")

    def test_aw_active_value(self) -> None:
        self.assertEqual(AutoSourceType.AW_ACTIVE.value, "aw_active")

    def test_is_workday_value(self) -> None:
        self.assertEqual(AutoSourceType.IS_WORKDAY.value, "is_workday")

    def test_slot_max_value(self) -> None:
        self.assertEqual(AutoSourceType.SLOT_MAX.value, "slot_max")

    def test_slot_min_value(self) -> None:
        self.assertEqual(AutoSourceType.SLOT_MIN.value, "slot_min")

    def test_rolling_avg_value(self) -> None:
        self.assertEqual(AutoSourceType.ROLLING_AVG.value, "rolling_avg")

    def test_total_member_count(self) -> None:
        self.assertEqual(len(AutoSourceType), 10)

    def test_is_str_subclass(self) -> None:
        self.assertIsInstance(AutoSourceType.NONZERO, str)


class TestAutoDisplayNames(unittest.TestCase):
    """Tests for AUTO_DISPLAY_NAMES dict."""

    def test_has_four_entries(self) -> None:
        self.assertEqual(len(AUTO_DISPLAY_NAMES), 4)

    def test_keys_are_auto_source_type(self) -> None:
        for key in AUTO_DISPLAY_NAMES:
            self.assertIsInstance(key, AutoSourceType)

    def test_day_of_week_display_name(self) -> None:
        self.assertEqual(AUTO_DISPLAY_NAMES[AutoSourceType.DAY_OF_WEEK], "День недели")

    def test_month_display_name(self) -> None:
        self.assertEqual(AUTO_DISPLAY_NAMES[AutoSourceType.MONTH], "Месяц")

    def test_is_workday_display_name(self) -> None:
        self.assertEqual(AUTO_DISPLAY_NAMES[AutoSourceType.IS_WORKDAY], "Календарный тип")

    def test_aw_active_display_name(self) -> None:
        self.assertEqual(
            AUTO_DISPLAY_NAMES[AutoSourceType.AW_ACTIVE],
            "Экранное время (активное)",
        )

    def test_week_number_not_in_display_names(self) -> None:
        self.assertNotIn(AutoSourceType.WEEK_NUMBER, AUTO_DISPLAY_NAMES)


class TestAutoIcons(unittest.TestCase):
    """Tests for AUTO_ICONS dict."""

    def test_has_three_entries(self) -> None:
        self.assertEqual(len(AUTO_ICONS), 3)

    def test_keys_are_auto_source_type(self) -> None:
        for key in AUTO_ICONS:
            self.assertIsInstance(key, AutoSourceType)

    def test_aw_active_not_in_icons(self) -> None:
        self.assertNotIn(AutoSourceType.AW_ACTIVE, AUTO_ICONS)

    def test_is_workday_icon(self) -> None:
        self.assertEqual(AUTO_ICONS[AutoSourceType.IS_WORKDAY], "🏢")

    def test_week_number_not_in_icons(self) -> None:
        self.assertNotIn(AutoSourceType.WEEK_NUMBER, AUTO_ICONS)


class TestCalendarTypes(unittest.TestCase):
    """Tests for _CALENDAR_TYPES frozenset."""

    def test_is_frozenset(self) -> None:
        self.assertIsInstance(_CALENDAR_TYPES, frozenset)

    def test_contains_day_of_week(self) -> None:
        self.assertIn(AutoSourceType.DAY_OF_WEEK, _CALENDAR_TYPES)

    def test_contains_month(self) -> None:
        self.assertIn(AutoSourceType.MONTH, _CALENDAR_TYPES)

    def test_contains_is_workday(self) -> None:
        self.assertIn(AutoSourceType.IS_WORKDAY, _CALENDAR_TYPES)

    def test_does_not_contain_nonzero(self) -> None:
        self.assertNotIn(AutoSourceType.NONZERO, _CALENDAR_TYPES)

    def test_does_not_contain_week_number(self) -> None:
        self.assertNotIn(AutoSourceType.WEEK_NUMBER, _CALENDAR_TYPES)

    def test_size_is_three(self) -> None:
        self.assertEqual(len(_CALENDAR_TYPES), 3)


class TestCalendarOptionLabels(unittest.TestCase):
    """Tests for CALENDAR_OPTION_LABELS dict."""

    def test_has_three_calendar_types(self) -> None:
        self.assertEqual(len(CALENDAR_OPTION_LABELS), 3)

    def test_day_of_week_has_seven_options(self) -> None:
        self.assertEqual(len(CALENDAR_OPTION_LABELS[AutoSourceType.DAY_OF_WEEK]), 7)

    def test_month_has_twelve_options(self) -> None:
        self.assertEqual(len(CALENDAR_OPTION_LABELS[AutoSourceType.MONTH]), 12)

    def test_is_workday_has_two_options(self) -> None:
        self.assertEqual(len(CALENDAR_OPTION_LABELS[AutoSourceType.IS_WORKDAY]), 2)

    def test_day_of_week_monday(self) -> None:
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.DAY_OF_WEEK][1], "Пн")

    def test_day_of_week_sunday(self) -> None:
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.DAY_OF_WEEK][7], "Вс")

    def test_month_january(self) -> None:
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.MONTH][1], "Январь")

    def test_month_december(self) -> None:
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.MONTH][12], "Декабрь")

    def test_is_workday_labels(self) -> None:
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.IS_WORKDAY][1], "Рабочий день")
        self.assertEqual(CALENDAR_OPTION_LABELS[AutoSourceType.IS_WORKDAY][2], "Выходной")


class TestSourceKeyToStr(unittest.TestCase):
    """Tests for SourceKey.to_str() serialization."""

    def test_plain_metric(self) -> None:
        sk = SourceKey(metric_id=42)
        self.assertEqual(sk.to_str(), "metric:42")

    def test_metric_with_slot(self) -> None:
        sk = SourceKey(metric_id=10, slot_id=3)
        self.assertEqual(sk.to_str(), "metric:10:slot:3")

    def test_metric_with_enum_opt(self) -> None:
        sk = SourceKey(metric_id=7, enum_option_id=15)
        self.assertEqual(sk.to_str(), "metric:7:enum_opt:15")

    def test_metric_with_enum_opt_and_slot(self) -> None:
        sk = SourceKey(metric_id=5, slot_id=2, enum_option_id=9)
        self.assertEqual(sk.to_str(), "metric:5:enum_opt:9:slot:2")

    def test_auto_without_parent(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK)
        self.assertEqual(sk.to_str(), "auto:day_of_week")

    def test_auto_with_parent(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=100
        )
        self.assertEqual(sk.to_str(), "auto:nonzero:metric:100")

    def test_auto_note_count_with_parent(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=55
        )
        self.assertEqual(sk.to_str(), "auto:note_count:metric:55")

    def test_auto_aw_active_without_parent(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.AW_ACTIVE)
        self.assertEqual(sk.to_str(), "auto:aw_active")

    def test_auto_with_option_id(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=3)
        self.assertEqual(sk.to_str(), "auto:day_of_week:opt:3")

    def test_auto_month_with_option_id(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.MONTH, auto_option_id=12)
        self.assertEqual(sk.to_str(), "auto:month:opt:12")

    def test_auto_is_workday_with_option_id(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.IS_WORKDAY, auto_option_id=1)
        self.assertEqual(sk.to_str(), "auto:is_workday:opt:1")

    def test_auto_slot_max_with_parent(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.SLOT_MAX, auto_parent_metric_id=42
        )
        self.assertEqual(sk.to_str(), "auto:slot_max:metric:42")

    def test_auto_slot_min_with_parent(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.SLOT_MIN, auto_parent_metric_id=42
        )
        self.assertEqual(sk.to_str(), "auto:slot_min:metric:42")

    def test_auto_rolling_avg_with_parent_and_window(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.ROLLING_AVG,
            auto_parent_metric_id=5,
            auto_option_id=7,
        )
        self.assertEqual(sk.to_str(), "auto:rolling_avg:metric:5:opt:7")

    def test_auto_rolling_avg_window_3(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.ROLLING_AVG,
            auto_parent_metric_id=10,
            auto_option_id=3,
        )
        self.assertEqual(sk.to_str(), "auto:rolling_avg:metric:10:opt:3")

    def test_auto_rolling_avg_window_14(self) -> None:
        sk = SourceKey(
            auto_type=AutoSourceType.ROLLING_AVG,
            auto_parent_metric_id=1,
            auto_option_id=14,
        )
        self.assertEqual(sk.to_str(), "auto:rolling_avg:metric:1:opt:14")


class TestSourceKeyParse(unittest.TestCase):
    """Tests for SourceKey.parse() deserialization."""

    def test_parse_plain_metric(self) -> None:
        sk = SourceKey.parse("metric:42")
        self.assertEqual(sk.metric_id, 42)
        self.assertIsNone(sk.slot_id)
        self.assertIsNone(sk.enum_option_id)
        self.assertIsNone(sk.auto_type)

    def test_parse_metric_with_slot(self) -> None:
        sk = SourceKey.parse("metric:10:slot:3")
        self.assertEqual(sk.metric_id, 10)
        self.assertEqual(sk.slot_id, 3)
        self.assertIsNone(sk.enum_option_id)

    def test_parse_metric_with_enum_opt(self) -> None:
        sk = SourceKey.parse("metric:7:enum_opt:15")
        self.assertEqual(sk.metric_id, 7)
        self.assertEqual(sk.enum_option_id, 15)
        self.assertIsNone(sk.slot_id)

    def test_parse_metric_with_enum_opt_and_slot(self) -> None:
        sk = SourceKey.parse("metric:5:enum_opt:9:slot:2")
        self.assertEqual(sk.metric_id, 5)
        self.assertEqual(sk.enum_option_id, 9)
        self.assertEqual(sk.slot_id, 2)

    def test_parse_auto_without_parent(self) -> None:
        sk = SourceKey.parse("auto:day_of_week")
        self.assertEqual(sk.auto_type, AutoSourceType.DAY_OF_WEEK)
        self.assertIsNone(sk.auto_parent_metric_id)
        self.assertIsNone(sk.metric_id)
        self.assertIsNone(sk.auto_option_id)

    def test_parse_auto_with_parent(self) -> None:
        sk = SourceKey.parse("auto:nonzero:metric:100")
        self.assertEqual(sk.auto_type, AutoSourceType.NONZERO)
        self.assertEqual(sk.auto_parent_metric_id, 100)

    def test_parse_auto_month(self) -> None:
        sk = SourceKey.parse("auto:month")
        self.assertEqual(sk.auto_type, AutoSourceType.MONTH)
        self.assertIsNone(sk.auto_parent_metric_id)

    def test_parse_auto_with_option_id(self) -> None:
        sk = SourceKey.parse("auto:day_of_week:opt:3")
        self.assertEqual(sk.auto_type, AutoSourceType.DAY_OF_WEEK)
        self.assertEqual(sk.auto_option_id, 3)
        self.assertIsNone(sk.auto_parent_metric_id)

    def test_parse_auto_month_with_option_id(self) -> None:
        sk = SourceKey.parse("auto:month:opt:12")
        self.assertEqual(sk.auto_type, AutoSourceType.MONTH)
        self.assertEqual(sk.auto_option_id, 12)

    def test_parse_auto_is_workday_with_option_id(self) -> None:
        sk = SourceKey.parse("auto:is_workday:opt:1")
        self.assertEqual(sk.auto_type, AutoSourceType.IS_WORKDAY)
        self.assertEqual(sk.auto_option_id, 1)

    def test_parse_auto_slot_max(self) -> None:
        sk = SourceKey.parse("auto:slot_max:metric:42")
        self.assertEqual(sk.auto_type, AutoSourceType.SLOT_MAX)
        self.assertEqual(sk.auto_parent_metric_id, 42)
        self.assertIsNone(sk.auto_option_id)

    def test_parse_auto_slot_min(self) -> None:
        sk = SourceKey.parse("auto:slot_min:metric:42")
        self.assertEqual(sk.auto_type, AutoSourceType.SLOT_MIN)
        self.assertEqual(sk.auto_parent_metric_id, 42)
        self.assertIsNone(sk.auto_option_id)

    def test_parse_auto_rolling_avg(self) -> None:
        sk = SourceKey.parse("auto:rolling_avg:metric:5:opt:7")
        self.assertEqual(sk.auto_type, AutoSourceType.ROLLING_AVG)
        self.assertEqual(sk.auto_parent_metric_id, 5)
        self.assertEqual(sk.auto_option_id, 7)

    def test_parse_auto_rolling_avg_window_3(self) -> None:
        sk = SourceKey.parse("auto:rolling_avg:metric:10:opt:3")
        self.assertEqual(sk.auto_type, AutoSourceType.ROLLING_AVG)
        self.assertEqual(sk.auto_parent_metric_id, 10)
        self.assertEqual(sk.auto_option_id, 3)

    def test_parse_auto_rolling_avg_window_14(self) -> None:
        sk = SourceKey.parse("auto:rolling_avg:metric:1:opt:14")
        self.assertEqual(sk.auto_type, AutoSourceType.ROLLING_AVG)
        self.assertEqual(sk.auto_parent_metric_id, 1)
        self.assertEqual(sk.auto_option_id, 14)

    def test_parse_old_week_number_backward_compat(self) -> None:
        sk = SourceKey.parse("auto:week_number")
        self.assertEqual(sk.auto_type, AutoSourceType.WEEK_NUMBER)
        self.assertIsNone(sk.auto_option_id)


class TestSourceKeyRoundTrip(unittest.TestCase):
    """Tests for to_str() -> parse() round-trip consistency."""

    def _assert_round_trip(self, sk: SourceKey) -> None:
        serialized = sk.to_str()
        restored = SourceKey.parse(serialized)
        self.assertEqual(restored, sk)

    def test_round_trip_plain_metric(self) -> None:
        self._assert_round_trip(SourceKey(metric_id=1))

    def test_round_trip_metric_with_slot(self) -> None:
        self._assert_round_trip(SourceKey(metric_id=2, slot_id=3))

    def test_round_trip_metric_with_enum_opt(self) -> None:
        self._assert_round_trip(SourceKey(metric_id=4, enum_option_id=5))

    def test_round_trip_metric_with_enum_opt_and_slot(self) -> None:
        self._assert_round_trip(SourceKey(metric_id=6, slot_id=7, enum_option_id=8))

    def test_round_trip_auto_without_parent(self) -> None:
        self._assert_round_trip(SourceKey(auto_type=AutoSourceType.WEEK_NUMBER))

    def test_round_trip_auto_with_parent(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=99)
        )

    def test_round_trip_auto_with_option_id(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=5)
        )

    def test_round_trip_auto_month_with_option_id(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.MONTH, auto_option_id=7)
        )

    def test_round_trip_auto_is_workday_with_option_id(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.IS_WORKDAY, auto_option_id=2)
        )

    def test_round_trip_auto_slot_max(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.SLOT_MAX, auto_parent_metric_id=10)
        )

    def test_round_trip_auto_slot_min(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.SLOT_MIN, auto_parent_metric_id=10)
        )

    def test_round_trip_auto_rolling_avg_window_3(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=3)
        )

    def test_round_trip_auto_rolling_avg_window_7(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        )

    def test_round_trip_auto_rolling_avg_window_14(self) -> None:
        self._assert_round_trip(
            SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=14)
        )


class TestRollingAvgWindows(unittest.TestCase):
    """Tests for ROLLING_AVG_WINDOWS constant."""

    def test_is_list_of_ints(self) -> None:
        self.assertIsInstance(ROLLING_AVG_WINDOWS, list)
        for w in ROLLING_AVG_WINDOWS:
            self.assertIsInstance(w, int)

    def test_default_values(self) -> None:
        self.assertEqual(ROLLING_AVG_WINDOWS, [3, 7, 14])

    def test_all_positive(self) -> None:
        for w in ROLLING_AVG_WINDOWS:
            self.assertGreater(w, 0)


class TestSourceKeyIsAuto(unittest.TestCase):
    """Tests for SourceKey.is_auto property."""

    def test_auto_type_set_returns_true(self) -> None:
        sk = SourceKey(auto_type=AutoSourceType.AW_ACTIVE)
        self.assertTrue(sk.is_auto)

    def test_metric_returns_false(self) -> None:
        sk = SourceKey(metric_id=1)
        self.assertFalse(sk.is_auto)

    def test_default_returns_false(self) -> None:
        sk = SourceKey()
        self.assertFalse(sk.is_auto)


class TestSourceKeyFrozen(unittest.TestCase):
    """Tests for SourceKey immutability (frozen dataclass)."""

    def test_cannot_set_metric_id(self) -> None:
        sk = SourceKey(metric_id=1)
        with self.assertRaises(AttributeError):
            sk.metric_id = 2  # type: ignore[misc]

    def test_hashable(self) -> None:
        sk = SourceKey(metric_id=1)
        # Should not raise — frozen dataclass is hashable
        self.assertIsInstance(hash(sk), int)

    def test_equal_instances_same_hash(self) -> None:
        a = SourceKey(metric_id=5, slot_id=3)
        b = SourceKey(metric_id=5, slot_id=3)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_usable_in_set(self) -> None:
        a = SourceKey(metric_id=1)
        b = SourceKey(metric_id=1)
        c = SourceKey(metric_id=2)
        s = {a, b, c}
        self.assertEqual(len(s), 2)

    def test_auto_option_id_in_hash(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=2)
        self.assertNotEqual(a, b)
        self.assertNotEqual(hash(a), hash(b))


if __name__ == "__main__":
    unittest.main()
