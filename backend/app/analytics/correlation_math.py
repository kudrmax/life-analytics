from __future__ import annotations

import math
from statistics import mean, stdev


BINARY_TYPES: frozenset[str] = frozenset({"bool", "enum_bool"})


class CorrelationCalculator:
    """Вычисление корреляции между двумя временными рядами.

    Инициализируется парой dict[str, float] (date→value).
    Кеширует Pearson r/n после первого вызова pearson().
    """

    def __init__(self, a: dict[str, float], b: dict[str, float]) -> None:
        self._a = a
        self._b = b
        self._r: float | None = None
        self._n: int = 0
        self._computed: bool = False

    def _ensure_pearson(self) -> None:
        if self._computed:
            return
        self._computed = True
        common = sorted(set(self._a) & set(self._b))
        self._n = len(common)
        if self._n < 3:
            self._r = None
            return

        xs = [self._a[d] for d in common]
        ys = [self._b[d] for d in common]

        mean_x, mean_y = mean(xs), mean(ys)
        try:
            std_x, std_y = stdev(xs), stdev(ys)
        except Exception:
            self._r = None
            return
        if std_x == 0 or std_y == 0:
            self._r = 0.0
            return

        n = self._n
        cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / (n - 1)
        self._r = round(cov / (std_x * std_y), 3)

    def pearson(self) -> tuple[float | None, int]:
        """Pearson r и количество общих точек."""
        self._ensure_pearson()
        return self._r, self._n

    def p_value(self) -> float:
        """Двусторонний p-value для Pearson r (t-test + beta)."""
        self._ensure_pearson()
        if self._r is None:
            return 1.0
        return p_value_from_r(self._r, self._n)

    def confidence_interval(self) -> tuple[float, float] | None:
        """95% CI через Fisher z-transform."""
        self._ensure_pearson()
        if self._r is None:
            return None
        return confidence_interval_from_r(self._r, self._n)

    def contingency_table(self) -> tuple[int, int, int, int, int]:
        """2×2 таблица сопряжённости для бинарных рядов.

        Returns (a, b, c, d, n) where:
          a = both True, b = A true & B false,
          c = A false & B true, d = both False,
          n = total common dates.
        """
        return build_contingency_table(self._a, self._b)

    def fisher_exact_p(self) -> float:
        """Двусторонний точный тест Фишера."""
        return fisher_exact_p(self._a, self._b)


# --- Standalone functions for cases where only r/n are available ---


def p_value_from_r(r: float, n: int) -> float:
    """Two-tailed p-value for Pearson correlation coefficient."""
    if n <= 2:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t_sq = r * r * df / (1.0 - r * r)
    return _betai(df / 2.0, 0.5, df / (df + t_sq))


def confidence_interval_from_r(r: float, n: int) -> tuple[float, float] | None:
    """95% confidence interval for Pearson r via Fisher z-transformation."""
    if n < 4:
        return None
    if abs(r) >= 1.0:
        return (r, r)
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    z_lower = z - 1.96 * se
    z_upper = z + 1.96 * se
    return (round(math.tanh(z_lower), 4), round(math.tanh(z_upper), 4))


def build_contingency_table(
    a_by_date: dict[str, float], b_by_date: dict[str, float],
) -> tuple[int, int, int, int, int]:
    """Build 2x2 contingency table from two binary data dicts."""
    a = b = c = d = 0
    for date in a_by_date:
        if date not in b_by_date:
            continue
        va = a_by_date[date] >= 0.5
        vb = b_by_date[date] >= 0.5
        if va and vb:
            a += 1
        elif va and not vb:
            b += 1
        elif not va and vb:
            c += 1
        else:
            d += 1
    return a, b, c, d, a + b + c + d


def fisher_exact_p(
    a_by_date: dict[str, float], b_by_date: dict[str, float],
) -> float:
    """Two-sided Fisher's exact test p-value for two binary data series."""
    a, b, c, d, n = build_contingency_table(a_by_date, b_by_date)
    if n == 0:
        return 1.0
    row1 = a + b
    col1 = a + c
    log_p_obs = _log_hypergeometric(a, b, c, d)
    a_min = max(0, row1 + col1 - n)
    a_max = min(row1, col1)
    p_total = 0.0
    for a_i in range(a_min, a_max + 1):
        b_i = row1 - a_i
        c_i = col1 - a_i
        d_i = n - row1 - col1 + a_i
        log_p_i = _log_hypergeometric(a_i, b_i, c_i, d_i)
        if log_p_i <= log_p_obs + 1e-10:
            p_total += math.exp(log_p_i)
    return min(p_total, 1.0)


# --- Private math helpers ---


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for regularized incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - ln_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _log_hypergeometric(a: int, b: int, c: int, d: int) -> float:
    """Log probability of a specific 2x2 table under the hypergeometric distribution."""
    n = a + b + c + d
    return (
        math.lgamma(a + b + 1) + math.lgamma(c + d + 1)
        + math.lgamma(a + c + 1) + math.lgamma(b + d + 1)
        - math.lgamma(n + 1)
        - math.lgamma(a + 1) - math.lgamma(b + 1)
        - math.lgamma(c + 1) - math.lgamma(d + 1)
    )
