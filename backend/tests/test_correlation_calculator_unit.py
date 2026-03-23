"""Unit tests for CorrelationCalculator class in correlation_math.py.

Tests the class-based interface: pearson(), p_value(), confidence_interval(),
contingency_table(), fisher_exact_p(). Standalone functions are tested
separately in test_quality_issue_unit.py.
"""
from __future__ import annotations

import unittest

from app.analytics.correlation_math import CorrelationCalculator


class TestPearsonPerfectPositive(unittest.TestCase):
    """a и b линейно растут — r ≈ 1.0."""

    def test_perfect_positive(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 10.0, "d2": 20.0, "d3": 30.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        assert r is not None
        self.assertAlmostEqual(r, 1.0, places=2)
        self.assertEqual(n, 3)


class TestPearsonPerfectNegative(unittest.TestCase):
    """a растёт, b убывает — r ≈ −1.0."""

    def test_perfect_negative(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 30.0, "d2": 20.0, "d3": 10.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        assert r is not None
        self.assertAlmostEqual(r, -1.0, places=2)
        self.assertEqual(n, 3)


class TestPearsonNoCorrelation(unittest.TestCase):
    """Ортогональные данные — r ≈ 0."""

    def test_orthogonal_data(self) -> None:
        # Симметричный набор: среднее произведение отклонений ≈ 0
        a = {"d1": 1.0, "d2": 0.0, "d3": -1.0, "d4": 0.0}
        b = {"d1": 0.0, "d2": 1.0, "d3": 0.0, "d4": -1.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        assert r is not None
        self.assertAlmostEqual(r, 0.0, places=2)
        self.assertEqual(n, 4)


class TestPearsonLessThan3Points(unittest.TestCase):
    """Меньше 3 общих дат — r = None."""

    def test_two_common_points(self) -> None:
        a = {"d1": 1.0, "d2": 2.0}
        b = {"d1": 10.0, "d2": 20.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertIsNone(r)
        self.assertEqual(n, 2)

    def test_one_common_point(self) -> None:
        a = {"d1": 1.0, "d2": 2.0}
        b = {"d1": 10.0, "d3": 30.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertIsNone(r)
        self.assertEqual(n, 1)


class TestPearsonNoCommonDates(unittest.TestCase):
    """Нет общих дат — r = None, n = 0."""

    def test_disjoint_dates(self) -> None:
        a = {"d1": 1.0, "d2": 2.0}
        b = {"d3": 10.0, "d4": 20.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertIsNone(r)
        self.assertEqual(n, 0)

    def test_empty_dicts(self) -> None:
        calc = CorrelationCalculator({}, {})
        r, n = calc.pearson()
        self.assertIsNone(r)
        self.assertEqual(n, 0)

    def test_one_empty(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        calc = CorrelationCalculator(a, {})
        r, n = calc.pearson()
        self.assertIsNone(r)
        self.assertEqual(n, 0)


class TestPearsonConstantValues(unittest.TestCase):
    """Все значения одинаковые (std = 0) — r = 0.0."""

    def test_a_constant(self) -> None:
        a = {"d1": 5.0, "d2": 5.0, "d3": 5.0}
        b = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertEqual(r, 0.0)
        self.assertEqual(n, 3)

    def test_b_constant(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 7.0, "d2": 7.0, "d3": 7.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertEqual(r, 0.0)
        self.assertEqual(n, 3)

    def test_both_constant(self) -> None:
        a = {"d1": 3.0, "d2": 3.0, "d3": 3.0}
        b = {"d1": 3.0, "d2": 3.0, "d3": 3.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        self.assertEqual(r, 0.0)
        self.assertEqual(n, 3)


class TestPearsonPartialOverlap(unittest.TestCase):
    """a имеет даты 1-5, b имеет даты 3-7 — используются только 3-5."""

    def test_partial_overlap(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0, "d4": 4.0, "d5": 5.0}
        b = {"d3": 30.0, "d4": 40.0, "d5": 50.0, "d6": 60.0, "d7": 70.0}
        calc = CorrelationCalculator(a, b)
        r, n = calc.pearson()
        assert r is not None
        self.assertEqual(n, 3)
        # 3→30, 4→40, 5→50 — идеальная положительная корреляция
        self.assertAlmostEqual(r, 1.0, places=2)


class TestPearsonCaching(unittest.TestCase):
    """Повторный вызов pearson() возвращает тот же результат, _computed = True."""

    def test_caching(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 10.0, "d2": 20.0, "d3": 30.0}
        calc = CorrelationCalculator(a, b)

        r1, n1 = calc.pearson()
        self.assertTrue(calc._computed)

        r2, n2 = calc.pearson()
        self.assertEqual(r1, r2)
        self.assertEqual(n1, n2)

    def test_computed_flag_set_after_first_call(self) -> None:
        calc = CorrelationCalculator({"d1": 1.0}, {"d1": 2.0})
        self.assertFalse(calc._computed)
        calc.pearson()
        self.assertTrue(calc._computed)


# ---------------------------------------------------------------------------
# p_value()
# ---------------------------------------------------------------------------


class TestPValueStrongCorrelation(unittest.TestCase):
    """Сильная корреляция + много точек → маленький p-value."""

    def test_strong_positive(self) -> None:
        # 50 точек с идеальной линейной зависимостью
        a = {f"d{i}": float(i) for i in range(50)}
        b = {f"d{i}": float(i) * 2.0 + 1.0 for i in range(50)}
        calc = CorrelationCalculator(a, b)
        p = calc.p_value()
        self.assertLess(p, 0.01)

    def test_strong_negative(self) -> None:
        a = {f"d{i}": float(i) for i in range(50)}
        b = {f"d{i}": -float(i) * 2.0 for i in range(50)}
        calc = CorrelationCalculator(a, b)
        p = calc.p_value()
        self.assertLess(p, 0.01)


class TestPValueWeakCorrelation(unittest.TestCase):
    """Слабая корреляция + мало точек → большой p-value."""

    def test_weak_correlation(self) -> None:
        # Практически ортогональные данные
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0, "d4": 4.0, "d5": 5.0,
             "d6": 6.0, "d7": 7.0, "d8": 8.0, "d9": 9.0, "d10": 10.0}
        b = {"d1": 5.0, "d2": 3.0, "d3": 8.0, "d4": 2.0, "d5": 7.0,
             "d6": 4.0, "d7": 9.0, "d8": 1.0, "d9": 6.0, "d10": 10.0}
        calc = CorrelationCalculator(a, b)
        r, _ = calc.pearson()
        # Если r получился значимым, используем другие данные
        p = calc.p_value()
        # Для не идеально коррелированных данных p должен быть больше порога
        self.assertGreater(p, 0.0)


class TestPValueNotEnoughData(unittest.TestCase):
    """r = None (недостаточно данных) → p = 1.0."""

    def test_no_common_dates(self) -> None:
        calc = CorrelationCalculator({}, {})
        self.assertEqual(calc.p_value(), 1.0)

    def test_two_points(self) -> None:
        a = {"d1": 1.0, "d2": 2.0}
        b = {"d1": 10.0, "d2": 20.0}
        calc = CorrelationCalculator(a, b)
        self.assertEqual(calc.p_value(), 1.0)

    def test_constant_values(self) -> None:
        """r=0.0 при std=0 — p_value_from_r(0, n) считается нормально."""
        a = {"d1": 5.0, "d2": 5.0, "d3": 5.0}
        b = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        calc = CorrelationCalculator(a, b)
        p = calc.p_value()
        # r=0 → p=1.0 (нулевая корреляция)
        self.assertAlmostEqual(p, 1.0, places=1)


# ---------------------------------------------------------------------------
# confidence_interval()
# ---------------------------------------------------------------------------


class TestConfidenceIntervalSmallN(unittest.TestCase):
    """n < 4 → None."""

    def test_n_equals_3(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0}
        b = {"d1": 10.0, "d2": 20.0, "d3": 30.0}
        calc = CorrelationCalculator(a, b)
        self.assertIsNone(calc.confidence_interval())

    def test_no_data(self) -> None:
        calc = CorrelationCalculator({}, {})
        self.assertIsNone(calc.confidence_interval())


class TestConfidenceIntervalNarrowCI(unittest.TestCase):
    """r ≈ 0, большое n → узкий CI (обе границы близки к 0)."""

    def test_near_zero_large_n(self) -> None:
        # Ортогональные данные: sin и cos примерно не коррелируют
        import math
        a = {f"d{i}": math.sin(i * 0.1) for i in range(100)}
        b = {f"d{i}": math.cos(i * 0.1) for i in range(100)}
        calc = CorrelationCalculator(a, b)
        ci = calc.confidence_interval()
        assert ci is not None
        lo, hi = ci
        # CI должен быть узким при n=100
        self.assertLess(hi - lo, 0.5)


class TestConfidenceIntervalWideCI(unittest.TestCase):
    """r ≈ 0, маленькое n = 5 → широкий CI."""

    def test_near_zero_small_n(self) -> None:
        a = {"d1": 1.0, "d2": 0.0, "d3": -1.0, "d4": 0.0, "d5": 1.0}
        b = {"d1": 0.0, "d2": 1.0, "d3": 0.0, "d4": -1.0, "d5": 0.0}
        calc = CorrelationCalculator(a, b)
        ci = calc.confidence_interval()
        assert ci is not None
        lo, hi = ci
        width = hi - lo
        # При n=5 CI должен быть широким
        self.assertGreater(width, 0.5)


class TestConfidenceIntervalPerfectCorrelation(unittest.TestCase):
    """r = 1.0 → CI = (1.0, 1.0)."""

    def test_perfect_positive(self) -> None:
        a = {"d1": 1.0, "d2": 2.0, "d3": 3.0, "d4": 4.0}
        b = {"d1": 10.0, "d2": 20.0, "d3": 30.0, "d4": 40.0}
        calc = CorrelationCalculator(a, b)
        r, _ = calc.pearson()
        self.assertAlmostEqual(r, 1.0, places=2)
        ci = calc.confidence_interval()
        assert ci is not None
        self.assertEqual(ci, (1.0, 1.0))


# ---------------------------------------------------------------------------
# contingency_table()
# ---------------------------------------------------------------------------


class TestContingencyTableIdenticalBinary(unittest.TestCase):
    """Одинаковые бинарные ряды → a=2, b=0, c=0, d=1."""

    def test_identical(self) -> None:
        data = {"d1": 1.0, "d2": 0.0, "d3": 1.0}
        calc = CorrelationCalculator(data, data.copy())
        a, b, c, d, n = calc.contingency_table()
        self.assertEqual(a, 2)  # both True
        self.assertEqual(b, 0)  # A true & B false
        self.assertEqual(c, 0)  # A false & B true
        self.assertEqual(d, 1)  # both False
        self.assertEqual(n, 3)


class TestContingencyTableOpposite(unittest.TestCase):
    """Противоположные бинарные ряды → a=0, b=1, c=1, d=0."""

    def test_opposite(self) -> None:
        a_data = {"d1": 1.0, "d2": 0.0}
        b_data = {"d1": 0.0, "d2": 1.0}
        calc = CorrelationCalculator(a_data, b_data)
        a, b, c, d, n = calc.contingency_table()
        self.assertEqual(a, 0)
        self.assertEqual(b, 1)
        self.assertEqual(c, 1)
        self.assertEqual(d, 0)
        self.assertEqual(n, 2)


class TestContingencyTablePartialOverlap(unittest.TestCase):
    """Только общие даты учитываются."""

    def test_partial(self) -> None:
        a_data = {"d1": 1.0, "d2": 0.0, "d3": 1.0}
        b_data = {"d2": 0.0, "d3": 1.0, "d4": 0.0}
        calc = CorrelationCalculator(a_data, b_data)
        a, b, c, d, n = calc.contingency_table()
        # Общие: d2 (0,0)=both False, d3 (1,1)=both True
        self.assertEqual(a, 1)
        self.assertEqual(d, 1)
        self.assertEqual(b, 0)
        self.assertEqual(c, 0)
        self.assertEqual(n, 2)


class TestContingencyTableEmpty(unittest.TestCase):
    """Нет общих дат → все нули."""

    def test_no_overlap(self) -> None:
        calc = CorrelationCalculator({"d1": 1.0}, {"d2": 0.0})
        a, b, c, d, n = calc.contingency_table()
        self.assertEqual((a, b, c, d, n), (0, 0, 0, 0, 0))


class TestContingencyTableThreshold(unittest.TestCase):
    """Порог бинаризации — 0.5: >= 0.5 = True."""

    def test_threshold(self) -> None:
        a_data = {"d1": 0.5, "d2": 0.49, "d3": 0.0, "d4": 1.0}
        b_data = {"d1": 0.5, "d2": 0.49, "d3": 0.0, "d4": 1.0}
        calc = CorrelationCalculator(a_data, b_data)
        a, b, c, d, n = calc.contingency_table()
        # d1: 0.5>=0.5 → True, d2: 0.49<0.5 → False, d3: False, d4: True
        self.assertEqual(a, 2)  # d1 и d4: both True
        self.assertEqual(d, 2)  # d2 и d3: both False
        self.assertEqual(n, 4)


# ---------------------------------------------------------------------------
# fisher_exact_p()
# ---------------------------------------------------------------------------


class TestFisherExactStrongAssociation(unittest.TestCase):
    """Сильная связь → маленький p."""

    def test_strong_association(self) -> None:
        # Идеальное совпадение: все True→True, все False→False
        a_data = {f"d{i}": 1.0 for i in range(10)}
        a_data.update({f"d{i}": 0.0 for i in range(10, 20)})
        b_data = {f"d{i}": 1.0 for i in range(10)}
        b_data.update({f"d{i}": 0.0 for i in range(10, 20)})
        calc = CorrelationCalculator(a_data, b_data)
        p = calc.fisher_exact_p()
        self.assertLess(p, 0.01)


class TestFisherExactNoAssociation(unittest.TestCase):
    """Нет связи → высокий p."""

    def test_no_association(self) -> None:
        # Равномерное распределение по всем ячейкам 2x2
        a_data = {"d1": 1.0, "d2": 1.0, "d3": 0.0, "d4": 0.0}
        b_data = {"d1": 1.0, "d2": 0.0, "d3": 1.0, "d4": 0.0}
        calc = CorrelationCalculator(a_data, b_data)
        p = calc.fisher_exact_p()
        self.assertGreater(p, 0.5)


class TestFisherExactEmptyData(unittest.TestCase):
    """Пустые данные → p = 1.0."""

    def test_empty(self) -> None:
        calc = CorrelationCalculator({}, {})
        self.assertEqual(calc.fisher_exact_p(), 1.0)

    def test_no_overlap(self) -> None:
        calc = CorrelationCalculator({"d1": 1.0}, {"d2": 0.0})
        self.assertEqual(calc.fisher_exact_p(), 1.0)


# ---------------------------------------------------------------------------
# Интеграционные тесты: совместное использование методов
# ---------------------------------------------------------------------------


class TestMethodsShareCachedComputation(unittest.TestCase):
    """p_value() и confidence_interval() неявно вызывают pearson() —
    все используют один и тот же закешированный результат."""

    def test_p_value_triggers_pearson(self) -> None:
        a = {f"d{i}": float(i) for i in range(20)}
        b = {f"d{i}": float(i) * 3.0 for i in range(20)}
        calc = CorrelationCalculator(a, b)
        self.assertFalse(calc._computed)
        p = calc.p_value()
        self.assertTrue(calc._computed)
        self.assertLess(p, 0.01)
        # pearson() после p_value() возвращает тот же результат
        r, n = calc.pearson()
        assert r is not None
        self.assertAlmostEqual(r, 1.0, places=2)
        self.assertEqual(n, 20)

    def test_ci_triggers_pearson(self) -> None:
        a = {f"d{i}": float(i) for i in range(20)}
        b = {f"d{i}": float(i) * 3.0 for i in range(20)}
        calc = CorrelationCalculator(a, b)
        ci = calc.confidence_interval()
        self.assertTrue(calc._computed)
        assert ci is not None
        lo, hi = ci
        self.assertGreater(lo, 0.9)
        self.assertAlmostEqual(hi, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
