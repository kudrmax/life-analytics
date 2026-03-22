"""Unit tests for distribution module (histogram, KDE, stats)."""

from __future__ import annotations

import math
import random

import pytest

from app.distribution import (
    DistributionResult,
    compute_distribution,
    compute_histogram,
    compute_kde,
    compute_stats,
    format_value,
)


class TestFormatValue:
    def test_time(self) -> None:
        assert format_value(510, "time") == "08:30"

    def test_time_midnight(self) -> None:
        assert format_value(0, "time") == "00:00"

    def test_duration(self) -> None:
        assert format_value(90, "duration") == "1ч 30м"

    def test_duration_zero(self) -> None:
        assert format_value(0, "duration") == "0ч 0м"

    def test_scale(self) -> None:
        assert format_value(75.3, "scale") == "75%"

    def test_number_integer(self) -> None:
        assert format_value(42.0, "number") == "42"

    def test_number_decimal(self) -> None:
        assert format_value(3.7, "number") == "3.7"


class TestComputeHistogram:
    def test_basic(self) -> None:
        values = list(range(20))
        bins = compute_histogram(values, "number")
        assert len(bins) >= 5
        assert sum(b.count for b in bins) == 20

    def test_single_value(self) -> None:
        values = [5.0] * 10
        bins = compute_histogram(values, "number")
        assert len(bins) == 1
        assert bins[0].count == 10
        assert bins[0].label == "5"

    def test_two_distinct_values(self) -> None:
        values = [1.0, 2.0, 1.0, 2.0]
        bins = compute_histogram(values, "number")
        assert sum(b.count for b in bins) == 4

    def test_min_bins(self) -> None:
        # Even with very few data points, at least 5 bins (unless all equal)
        values = [1.0, 2.0, 3.0]
        bins = compute_histogram(values, "number")
        assert len(bins) >= 5

    def test_max_bins(self) -> None:
        # Large dataset should not exceed 20 bins
        values = list(range(100000))
        bins = compute_histogram([float(v) for v in values], "number")
        assert len(bins) <= 20

    def test_empty(self) -> None:
        bins = compute_histogram([], "number")
        assert bins == []

    def test_bin_labels_time(self) -> None:
        values = [480.0, 510.0, 540.0, 570.0, 600.0]
        bins = compute_histogram(values, "time")
        for b in bins:
            assert ":" in b.label

    def test_bin_labels_duration(self) -> None:
        values = [60.0, 90.0, 120.0, 150.0, 180.0]
        bins = compute_histogram(values, "duration")
        for b in bins:
            assert "ч" in b.label and "м" in b.label

    def test_bin_labels_scale(self) -> None:
        values = [10.0, 30.0, 50.0, 70.0, 90.0]
        bins = compute_histogram(values, "scale")
        for b in bins:
            assert "%" in b.label

    def test_all_values_assigned(self) -> None:
        """Every value must end up in exactly one bin."""
        random.seed(42)
        values = [random.gauss(50, 15) for _ in range(100)]
        bins = compute_histogram(values, "number")
        assert sum(b.count for b in bins) == 100


class TestComputeKDE:
    def test_basic(self) -> None:
        values = [float(x) for x in range(20)]
        xs, ys = compute_kde(values)
        assert len(xs) == 50
        assert len(ys) == 50
        assert all(y >= 0 for y in ys)

    def test_integral_approximate(self) -> None:
        """Integral of KDE should be approximately 1.0."""
        random.seed(42)
        values = [random.gauss(0, 1) for _ in range(200)]
        xs, ys = compute_kde(values)
        # Trapezoidal approximation
        integral = 0.0
        for i in range(len(xs) - 1):
            dx = xs[i + 1] - xs[i]
            integral += (ys[i] + ys[i + 1]) / 2 * dx
        assert 0.8 < integral < 1.2, f"KDE integral = {integral}, expected ~1.0"

    def test_peak_near_mean(self) -> None:
        """For normally distributed data, KDE peak should be near the mean."""
        random.seed(42)
        values = [random.gauss(100, 5) for _ in range(500)]
        xs, ys = compute_kde(values)
        peak_idx = ys.index(max(ys))
        peak_x = xs[peak_idx]
        actual_mean = sum(values) / len(values)
        assert abs(peak_x - actual_mean) < 5, f"KDE peak at {peak_x}, mean at {actual_mean}"

    def test_zero_variance(self) -> None:
        """All equal values → empty KDE."""
        values = [5.0] * 20
        xs, ys = compute_kde(values)
        assert xs == []
        assert ys == []

    def test_too_few_values(self) -> None:
        xs, ys = compute_kde([1.0])
        assert xs == []
        assert ys == []


class TestComputeStats:
    def test_basic(self) -> None:
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        stats = compute_stats(values)
        assert stats.mean == 5.0
        assert stats.median == 4.5
        assert stats.variance > 0
        assert stats.std_dev > 0
        assert stats.skewness is not None
        assert stats.kurtosis is not None

    def test_symmetric_skewness(self) -> None:
        """Symmetric distribution has skewness near 0."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        stats = compute_stats(values)
        assert abs(stats.skewness) < 0.1

    def test_positive_skewness(self) -> None:
        """Right-skewed distribution has positive skewness."""
        values = [1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 10.0, 20.0, 50.0]
        stats = compute_stats(values)
        assert stats.skewness > 0

    def test_normal_kurtosis(self) -> None:
        """Approximately normal data has kurtosis near 0 (excess)."""
        random.seed(42)
        values = [random.gauss(0, 1) for _ in range(10000)]
        stats = compute_stats(values)
        assert abs(stats.kurtosis) < 0.5, f"kurtosis = {stats.kurtosis}"

    def test_zero_variance(self) -> None:
        values = [3.0] * 10
        stats = compute_stats(values)
        assert stats.mean == 3.0
        assert stats.variance == 0.0
        assert stats.std_dev == 0.0
        assert stats.skewness is None
        assert stats.kurtosis is None

    def test_single_value(self) -> None:
        stats = compute_stats([42.0])
        assert stats.mean == 42.0
        assert stats.variance == 0.0
        assert stats.skewness is None

    def test_two_values(self) -> None:
        stats = compute_stats([1.0, 3.0])
        assert stats.mean == 2.0
        assert stats.variance > 0
        assert stats.std_dev > 0


class TestComputeDistribution:
    def test_full_pipeline(self) -> None:
        random.seed(42)
        values = [random.gauss(50, 10) for _ in range(100)]
        result = compute_distribution(values, "number")
        assert isinstance(result, DistributionResult)
        assert result.n == 100
        assert len(result.bins) >= 5
        assert len(result.kde_x) == 50
        assert len(result.kde_y) == 50
        assert result.stats.mean is not None
        assert result.stats.variance > 0
