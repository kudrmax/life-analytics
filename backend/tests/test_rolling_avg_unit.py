"""Unit tests for _compute_rolling_avg function."""

import unittest

from app.routers.analytics import _compute_rolling_avg


class TestComputeRollingAvgEmpty(unittest.TestCase):
    """Empty/insufficient data scenarios."""

    def test_empty_data_returns_empty(self) -> None:
        self.assertEqual(_compute_rolling_avg({}, 3), {})

    def test_data_less_than_window_returns_empty(self) -> None:
        data = {"2025-01-01": 5.0, "2025-01-02": 10.0}
        self.assertEqual(_compute_rolling_avg(data, 3), {})

    def test_window_1_returns_same_data(self) -> None:
        data = {"2025-01-01": 5.0, "2025-01-02": 10.0}
        result = _compute_rolling_avg(data, 1)
        self.assertEqual(result, {"2025-01-01": 5.0, "2025-01-02": 10.0})


class TestComputeRollingAvgFullWindow(unittest.TestCase):
    """Correct computation with full windows."""

    def test_exactly_n_days_returns_one_result(self) -> None:
        data = {
            "2025-01-01": 3.0,
            "2025-01-02": 6.0,
            "2025-01-03": 9.0,
        }
        result = _compute_rolling_avg(data, 3)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result["2025-01-03"], 6.0)

    def test_window_3_correct_values(self) -> None:
        data = {
            "2025-01-01": 1.0,
            "2025-01-02": 2.0,
            "2025-01-03": 3.0,
            "2025-01-04": 4.0,
            "2025-01-05": 5.0,
        }
        result = _compute_rolling_avg(data, 3)
        # 2025-01-03: (1+2+3)/3 = 2.0
        # 2025-01-04: (2+3+4)/3 = 3.0
        # 2025-01-05: (3+4+5)/3 = 4.0
        self.assertAlmostEqual(result["2025-01-03"], 2.0)
        self.assertAlmostEqual(result["2025-01-04"], 3.0)
        self.assertAlmostEqual(result["2025-01-05"], 4.0)
        self.assertNotIn("2025-01-01", result)
        self.assertNotIn("2025-01-02", result)

    def test_window_7_correct_value(self) -> None:
        data = {f"2025-01-{d:02d}": float(d) for d in range(1, 8)}
        result = _compute_rolling_avg(data, 7)
        self.assertEqual(len(result), 1)
        # (1+2+3+4+5+6+7)/7 = 4.0
        self.assertAlmostEqual(result["2025-01-07"], 4.0)


class TestComputeRollingAvgGaps(unittest.TestCase):
    """Gaps in data should cause incomplete windows to be skipped."""

    def test_gap_in_middle_skips_incomplete(self) -> None:
        data = {
            "2025-01-01": 1.0,
            "2025-01-02": 2.0,
            # gap on 2025-01-03
            "2025-01-04": 4.0,
            "2025-01-05": 5.0,
        }
        result = _compute_rolling_avg(data, 3)
        # 2025-01-02: needs 01,02,00 — 00 missing → skip (only 2 in window)
        # Actually: 2025-01-02 needs 01-02, 01-01, 12-31 — 12-31 missing
        # 2025-01-04: needs 04,03,02 — 03 missing → skip
        # 2025-01-05: needs 05,04,03 — 03 missing → skip
        # Only 2025-01-02 has window [02,01] but needs 3 days → skip
        self.assertEqual(result, {})

    def test_gap_then_full_window(self) -> None:
        data = {
            "2025-01-01": 1.0,
            # gap on 2025-01-02
            "2025-01-03": 3.0,
            "2025-01-04": 4.0,
            "2025-01-05": 5.0,
        }
        result = _compute_rolling_avg(data, 3)
        # 2025-01-05: needs 05,04,03 — all present → (3+4+5)/3 = 4.0
        self.assertAlmostEqual(result["2025-01-05"], 4.0)
        # 2025-01-04: needs 04,03,02 — 02 missing → skip
        self.assertNotIn("2025-01-04", result)
        # 2025-01-03: needs 03,02,01 — 02 missing → skip
        self.assertNotIn("2025-01-03", result)


class TestComputeRollingAvgEdgeCases(unittest.TestCase):
    """Edge cases for rolling average."""

    def test_all_same_values(self) -> None:
        data = {
            "2025-01-01": 5.0,
            "2025-01-02": 5.0,
            "2025-01-03": 5.0,
        }
        result = _compute_rolling_avg(data, 3)
        self.assertAlmostEqual(result["2025-01-03"], 5.0)

    def test_zero_values(self) -> None:
        data = {
            "2025-01-01": 0.0,
            "2025-01-02": 0.0,
            "2025-01-03": 0.0,
        }
        result = _compute_rolling_avg(data, 3)
        self.assertAlmostEqual(result["2025-01-03"], 0.0)

    def test_float_precision(self) -> None:
        data = {
            "2025-01-01": 1.0,
            "2025-01-02": 1.0,
            "2025-01-03": 2.0,
        }
        result = _compute_rolling_avg(data, 3)
        self.assertAlmostEqual(result["2025-01-03"], 4.0 / 3.0)


if __name__ == "__main__":
    unittest.main()
