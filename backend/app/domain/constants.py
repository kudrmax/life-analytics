"""Domain constants — именованные константы вместо magic numbers."""

# --- Корреляционные пороги ---
# pair_formatter.py, analytics.py — фильтрация пар по силе корреляции
CORRELATION_THRESHOLD_STRONG: float = 0.7
CORRELATION_THRESHOLD_MODERATE: float = 0.3

# --- Статистическая значимость ---
# quality.py, correlation_engine.py — p-value порог
P_VALUE_SIGNIFICANCE_THRESHOLD: float = 0.05

# --- Бинарные данные ---
# correlation_math.py — порог для contingency table (>=0.5 → True)
BINARY_THRESHOLD: float = 0.5

# --- Доверительный интервал ---
# correlation_engine.py — если CI шире этого порога → quality issue
CONFIDENCE_INTERVAL_WIDTH_THRESHOLD: float = 0.5
# correlation_math.py — z-score для 95% CI
Z_SCORE_95: float = 1.96

# --- Минимум данных ---
# quality.py — минимальное кол-во точек для валидной корреляции
MIN_DATA_POINTS: int = 10

# --- Конвертация времени ---
MINUTES_PER_HOUR: int = 60
MINUTES_PER_DAY: int = 1440  # 24 * 60
SECONDS_PER_HOUR: int = 3600

# --- Валидация пользователей ---
# auth.py — ограничения при регистрации
MIN_PASSWORD_LENGTH: int = 8
MIN_USERNAME_LENGTH: int = 3
MAX_USERNAME_LENGTH: int = 30

# --- Лимиты отображения ---
# integrations.py — кол-во элементов в summary
MAX_APPS_IN_SUMMARY: int = 7
MAX_DOMAINS_IN_SUMMARY: int = 5
