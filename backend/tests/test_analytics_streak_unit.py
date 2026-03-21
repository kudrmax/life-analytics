"""Unit tests for _compute_streak function."""

import unittest

from app.routers.analytics import _compute_streak


class TestComputeStreak(unittest.TestCase):
    """Tests for streak computation logic."""

    def _make_dates(self, start: str, count: int) -> list[str]:
        """Generate consecutive date strings starting from start."""
        from datetime import date, timedelta
        d = date.fromisoformat(start)
        return [str(d + timedelta(days=i)) for i in range(count)]

    def test_streak_true_basic(self) -> None:
        """streak_true: [T, T, F, F, F, T] → [1, 2, 0, 0, 0, 1]."""
        dates = self._make_dates("2026-01-01", 6)
        parent = {
            dates[0]: 1.0,
            dates[1]: 1.0,
            dates[2]: 0.0,
            dates[3]: 0.0,
            dates[4]: 0.0,
            dates[5]: 1.0,
        }
        result = _compute_streak(parent, dates, target_value=True)
        self.assertEqual(result[dates[0]], 1.0)
        self.assertEqual(result[dates[1]], 2.0)
        self.assertEqual(result[dates[2]], 0.0)
        self.assertEqual(result[dates[3]], 0.0)
        self.assertEqual(result[dates[4]], 0.0)
        self.assertEqual(result[dates[5]], 1.0)

    def test_streak_false_basic(self) -> None:
        """streak_false: [T, T, F, F, F, T] → [0, 0, 1, 2, 3, 0]."""
        dates = self._make_dates("2026-01-01", 6)
        parent = {
            dates[0]: 1.0,
            dates[1]: 1.0,
            dates[2]: 0.0,
            dates[3]: 0.0,
            dates[4]: 0.0,
            dates[5]: 1.0,
        }
        result = _compute_streak(parent, dates, target_value=False)
        self.assertEqual(result[dates[0]], 0.0)
        self.assertEqual(result[dates[1]], 0.0)
        self.assertEqual(result[dates[2]], 1.0)
        self.assertEqual(result[dates[3]], 2.0)
        self.assertEqual(result[dates[4]], 3.0)
        self.assertEqual(result[dates[5]], 0.0)

    def test_missing_day_resets_streak(self) -> None:
        """A missing day (no entry) resets streak to 0."""
        dates = self._make_dates("2026-01-01", 5)
        # Day 3 (index 2) is missing
        parent = {
            dates[0]: 1.0,
            dates[1]: 1.0,
            # dates[2] missing
            dates[3]: 1.0,
            dates[4]: 1.0,
        }
        result = _compute_streak(parent, dates, target_value=True)
        self.assertEqual(result[dates[0]], 1.0)
        self.assertEqual(result[dates[1]], 2.0)
        self.assertNotIn(dates[2], result)
        self.assertEqual(result[dates[3]], 1.0)  # reset after gap
        self.assertEqual(result[dates[4]], 2.0)

    def test_empty_parent_data(self) -> None:
        """Empty parent data produces empty result."""
        dates = self._make_dates("2026-01-01", 5)
        result = _compute_streak({}, dates, target_value=True)
        self.assertEqual(result, {})

    def test_all_true(self) -> None:
        """All True gives incrementing streak_true."""
        dates = self._make_dates("2026-01-01", 4)
        parent = {d: 1.0 for d in dates}
        result = _compute_streak(parent, dates, target_value=True)
        self.assertEqual([result[d] for d in dates], [1.0, 2.0, 3.0, 4.0])

    def test_all_false(self) -> None:
        """All False gives incrementing streak_false."""
        dates = self._make_dates("2026-01-01", 4)
        parent = {d: 0.0 for d in dates}
        result = _compute_streak(parent, dates, target_value=False)
        self.assertEqual([result[d] for d in dates], [1.0, 2.0, 3.0, 4.0])

    def test_single_day(self) -> None:
        """Single day with matching value gives streak of 1."""
        dates = ["2026-01-01"]
        parent = {"2026-01-01": 1.0}
        result = _compute_streak(parent, dates, target_value=True)
        self.assertEqual(result["2026-01-01"], 1.0)

    def test_result_only_contains_parent_dates(self) -> None:
        """Result only has dates present in parent_data."""
        dates = self._make_dates("2026-01-01", 5)
        parent = {dates[1]: 1.0, dates[3]: 0.0}
        result = _compute_streak(parent, dates, target_value=True)
        self.assertEqual(set(result.keys()), {dates[1], dates[3]})


if __name__ == "__main__":
    unittest.main()
