"""Distribution analysis: histogram, KDE, descriptive statistics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, median, stdev, variance


@dataclass
class HistogramBin:
    bin_start: float
    bin_end: float
    count: int
    label: str


@dataclass
class DistributionStats:
    mean: float
    median: float
    variance: float
    std_dev: float
    skewness: float | None
    kurtosis: float | None


@dataclass
class DistributionResult:
    bins: list[HistogramBin]
    kde_x: list[float]
    kde_y: list[float]
    stats: DistributionStats
    n: int


def format_value(value: float, metric_type: str) -> str:
    """Format a single numeric value according to metric type."""
    if metric_type == "time":
        minutes = int(round(value))
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"
    elif metric_type == "duration":
        minutes = int(round(value))
        h = minutes // 60
        m = minutes % 60
        return f"{h}ч {m}м"
    elif metric_type == "scale":
        return f"{value:.0f}%"
    else:
        if value == int(value):
            return str(int(value))
        return f"{value:.1f}"


def _bin_label(bin_start: float, bin_end: float, metric_type: str) -> str:
    """Format a bin range label."""
    return f"{format_value(bin_start, metric_type)}–{format_value(bin_end, metric_type)}"


def compute_histogram(
    values: list[float], metric_type: str, n_bins: int | None = None,
) -> list[HistogramBin]:
    """Build histogram bins using Sturges' rule."""
    n = len(values)
    if n == 0:
        return []

    v_min = min(values)
    v_max = max(values)

    if n_bins is None:
        n_bins = max(5, min(20, math.ceil(1 + math.log2(n))))

    if v_min == v_max:
        return [HistogramBin(
            bin_start=v_min,
            bin_end=v_max,
            count=n,
            label=format_value(v_min, metric_type),
        )]

    bin_width = (v_max - v_min) / n_bins
    bins: list[HistogramBin] = []
    for i in range(n_bins):
        b_start = v_min + i * bin_width
        b_end = v_min + (i + 1) * bin_width
        bins.append(HistogramBin(
            bin_start=b_start,
            bin_end=b_end,
            count=0,
            label=_bin_label(b_start, b_end, metric_type),
        ))

    for v in values:
        idx = int((v - v_min) / bin_width)
        if idx >= n_bins:
            idx = n_bins - 1
        bins[idx].count += 1

    return bins


def compute_kde(
    values: list[float], n_points: int = 50,
) -> tuple[list[float], list[float]]:
    """Gaussian KDE with Silverman bandwidth."""
    n = len(values)
    if n < 2:
        return [], []

    s = stdev(values)
    if s == 0:
        return [], []

    sorted_vals = sorted(values)
    q1 = sorted_vals[n // 4]
    q3 = sorted_vals[(3 * n) // 4]
    iqr = q3 - q1

    # Silverman's rule of thumb
    h = 0.9 * min(s, iqr / 1.34 if iqr > 0 else s) * (n ** -0.2)
    if h <= 0:
        h = s * (n ** -0.2)

    v_min = min(values)
    v_max = max(values)
    padding = 3 * h
    x_start = v_min - padding
    x_end = v_max + padding
    step = (x_end - x_start) / (n_points - 1) if n_points > 1 else 1.0

    xs: list[float] = []
    ys: list[float] = []
    coeff = 1.0 / (n * h * math.sqrt(2 * math.pi))

    for i in range(n_points):
        x = x_start + i * step
        density = 0.0
        for v in values:
            z = (x - v) / h
            density += math.exp(-0.5 * z * z)
        density *= coeff
        xs.append(round(x, 4))
        ys.append(round(density, 6))

    return xs, ys


def compute_stats(values: list[float]) -> DistributionStats:
    """Compute descriptive statistics including skewness and kurtosis."""
    n = len(values)
    m = mean(values)
    med = median(values)

    if n < 2:
        return DistributionStats(
            mean=round(m, 4),
            median=round(med, 4),
            variance=0.0,
            std_dev=0.0,
            skewness=None,
            kurtosis=None,
        )

    var = variance(values)
    sd = stdev(values)

    skew: float | None = None
    kurt: float | None = None

    if sd > 0:
        skew = sum((v - m) ** 3 for v in values) / n / (sd ** 3)
        kurt = sum((v - m) ** 4 for v in values) / n / (sd ** 4) - 3.0
        skew = round(skew, 4)
        kurt = round(kurt, 4)

    return DistributionStats(
        mean=round(m, 4),
        median=round(med, 4),
        variance=round(var, 4),
        std_dev=round(sd, 4),
        skewness=skew,
        kurtosis=kurt,
    )


def compute_distribution(
    values: list[float], metric_type: str,
) -> DistributionResult:
    """Compute full distribution analysis: histogram + KDE + stats."""
    bins = compute_histogram(values, metric_type)
    kde_x, kde_y = compute_kde(values)
    stats = compute_stats(values)
    return DistributionResult(
        bins=bins,
        kde_x=kde_x,
        kde_y=kde_y,
        stats=stats,
        n=len(values),
    )
