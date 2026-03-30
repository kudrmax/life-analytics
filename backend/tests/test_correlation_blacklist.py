"""Unit tests for correlation_blacklist.should_skip_pair."""

import unittest

from app.correlation_blacklist import should_skip_pair
from app.source_key import AutoSourceType, SourceKey


class TestShouldSkipPair(unittest.TestCase):
    """Tests for should_skip_pair blacklist rules."""

    # ---- Same metric, different checkpoints -> skip ----

    def test_same_metric_different_checkpoints_skipped(self) -> None:
        a = SourceKey(metric_id=1, checkpoint_id=10)
        b = SourceKey(metric_id=1, checkpoint_id=20)
        self.assertTrue(should_skip_pair(a, b))

    def test_same_metric_no_checkpoints_skipped(self) -> None:
        a = SourceKey(metric_id=1)
        b = SourceKey(metric_id=1)
        self.assertTrue(should_skip_pair(a, b))

    # ---- Same metric, different enum options (multi-select) -> don't skip ----

    def test_multi_select_enum_different_options_not_skipped(self) -> None:
        a = SourceKey(metric_id=5, enum_option_id=100)
        b = SourceKey(metric_id=5, enum_option_id=200)
        self.assertFalse(should_skip_pair(a, b))

    def test_multi_select_enum_different_options_explicit_set_not_skipped(self) -> None:
        a = SourceKey(metric_id=5, enum_option_id=100)
        b = SourceKey(metric_id=5, enum_option_id=200)
        self.assertFalse(should_skip_pair(a, b, single_select_metric_ids=set()))

    # ---- Same metric, different enum options (single-select) -> skip ----

    def test_single_select_enum_different_options_skipped(self) -> None:
        a = SourceKey(metric_id=5, enum_option_id=100)
        b = SourceKey(metric_id=5, enum_option_id=200)
        self.assertTrue(should_skip_pair(a, b, single_select_metric_ids={5}))

    def test_single_select_enum_different_options_default_not_skipped(self) -> None:
        """Without single_select_metric_ids param (None) — backward compat, don't skip."""
        a = SourceKey(metric_id=5, enum_option_id=100)
        b = SourceKey(metric_id=5, enum_option_id=200)
        self.assertFalse(should_skip_pair(a, b, single_select_metric_ids=None))

    # ---- Same metric, same enum option -> skip ----

    def test_same_metric_same_enum_option_skipped(self) -> None:
        a = SourceKey(metric_id=5, enum_option_id=100)
        b = SourceKey(metric_id=5, enum_option_id=100)
        self.assertTrue(should_skip_pair(a, b))

    # ---- Auto + its parent metric -> skip ----

    def test_auto_nonzero_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_auto_nonzero_with_parent_metric_reversed_skipped(self) -> None:
        regular = SourceKey(metric_id=3)
        auto = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=3)
        self.assertTrue(should_skip_pair(regular, auto))

    # ---- Two autos from same parent -> skip ----

    def test_two_autos_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=7)
        b = SourceKey(auto_type=AutoSourceType.NOTE_COUNT, auto_parent_metric_id=7)
        self.assertTrue(should_skip_pair(a, b))

    # ---- Two calendar autos -> skip ----

    def test_two_calendar_autos_different_types_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        b = SourceKey(auto_type=AutoSourceType.MONTH, auto_option_id=3)
        self.assertTrue(should_skip_pair(a, b))

    def test_two_calendar_autos_same_type_different_options_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_is_workday_and_day_of_week_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.IS_WORKDAY, auto_option_id=1)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=3)
        self.assertTrue(should_skip_pair(a, b))

    # ---- aw_active + calendar -> don't skip ----

    def test_aw_active_and_calendar_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.AW_ACTIVE)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        self.assertFalse(should_skip_pair(a, b))

    # ---- Two different regular metrics -> don't skip ----

    def test_two_different_regular_metrics_not_skipped(self) -> None:
        a = SourceKey(metric_id=1)
        b = SourceKey(metric_id=2)
        self.assertFalse(should_skip_pair(a, b))

    # ---- One auto, one regular, not parent -> don't skip ----

    def test_auto_with_unrelated_metric_not_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=99)
        self.assertFalse(should_skip_pair(auto, regular))

    def test_calendar_auto_with_regular_metric_not_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        regular = SourceKey(metric_id=5)
        self.assertFalse(should_skip_pair(auto, regular))

    # ---- Two autos, different parents -> don't skip ----

    def test_two_autos_different_parents_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=1)
        b = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=2)
        self.assertFalse(should_skip_pair(a, b))

    # ---- CHECKPOINT_MAX / CHECKPOINT_MIN blacklist coverage ----

    def test_checkpoint_max_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_checkpoint_min_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_checkpoint_max_and_checkpoint_min_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=5)
        b = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_checkpoint_max_with_unrelated_metric_not_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=99)
        self.assertFalse(should_skip_pair(auto, regular))

    def test_checkpoint_max_and_checkpoint_min_different_parents_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=1)
        b = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MIN, auto_parent_metric_id=2)
        self.assertFalse(should_skip_pair(a, b))

    # ---- ROLLING_AVG blacklist coverage ----

    def test_rolling_avg_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=3, auto_option_id=7)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_rolling_avg_with_parent_metric_reversed_skipped(self) -> None:
        regular = SourceKey(metric_id=3)
        auto = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=3, auto_option_id=7)
        self.assertTrue(should_skip_pair(regular, auto))

    def test_two_rolling_avg_same_parent_different_windows_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=3)
        b = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        self.assertTrue(should_skip_pair(a, b))

    def test_rolling_avg_and_nonzero_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_rolling_avg_and_checkpoint_max_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=5, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.CHECKPOINT_MAX, auto_parent_metric_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_rolling_avg_different_parents_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=1, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=2, auto_option_id=7)
        self.assertFalse(should_skip_pair(a, b))

    def test_rolling_avg_with_unrelated_metric_not_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=3, auto_option_id=7)
        regular = SourceKey(metric_id=99)
        self.assertFalse(should_skip_pair(auto, regular))

    def test_rolling_avg_and_calendar_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=3, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        self.assertFalse(should_skip_pair(a, b))

    # ---- STREAK blacklist coverage ----

    def test_streak_true_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_streak_false_with_parent_metric_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=3)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_streak_true_and_streak_false_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5)
        b = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_streak_and_nonzero_same_parent_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5)
        b = SourceKey(auto_type=AutoSourceType.NONZERO, auto_parent_metric_id=5)
        self.assertTrue(should_skip_pair(a, b))

    def test_streak_with_unrelated_metric_not_skipped(self) -> None:
        auto = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=3)
        regular = SourceKey(metric_id=99)
        self.assertFalse(should_skip_pair(auto, regular))

    def test_streak_true_and_streak_false_different_parents_skipped(self) -> None:
        """streak × streak — always skip, even different parents."""
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=1)
        b = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=2)
        self.assertTrue(should_skip_pair(a, b))

    def test_streak_true_x_streak_true_different_parents_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=1)
        b = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=2)
        self.assertTrue(should_skip_pair(a, b))

    def test_streak_x_rolling_avg_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=1)
        b = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=2, auto_option_id=7)
        self.assertTrue(should_skip_pair(a, b))

    def test_streak_x_rolling_avg_reversed_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=2, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.STREAK_FALSE, auto_parent_metric_id=1)
        self.assertTrue(should_skip_pair(a, b))

    def test_rolling_avg_x_rolling_avg_different_parents_not_skipped(self) -> None:
        """rolling_avg × rolling_avg (different parents) — no rule, don't skip."""
        a = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=1, auto_option_id=7)
        b = SourceKey(auto_type=AutoSourceType.ROLLING_AVG, auto_parent_metric_id=2, auto_option_id=7)
        self.assertFalse(should_skip_pair(a, b))

    def test_streak_enum_option_same_option_skipped(self) -> None:
        """streak(metric=5, opt=100) vs enum_option(metric=5, opt=100) → skip."""
        auto = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5, auto_option_id=100)
        regular = SourceKey(metric_id=5, enum_option_id=100)
        self.assertTrue(should_skip_pair(auto, regular))

    def test_streak_enum_option_different_option_not_skipped(self) -> None:
        """streak(metric=5, opt=100) vs enum_option(metric=5, opt=200) → not skip."""
        auto = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=5, auto_option_id=100)
        regular = SourceKey(metric_id=5, enum_option_id=200)
        self.assertFalse(should_skip_pair(auto, regular))

    def test_streak_and_calendar_not_skipped(self) -> None:
        a = SourceKey(auto_type=AutoSourceType.STREAK_TRUE, auto_parent_metric_id=3)
        b = SourceKey(auto_type=AutoSourceType.DAY_OF_WEEK, auto_option_id=1)
        self.assertFalse(should_skip_pair(a, b))


if __name__ == "__main__":
    unittest.main()
