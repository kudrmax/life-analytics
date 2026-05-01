# Cross-Metric Correlation: Free Checkpoints x Free Intervals

## Контекст

В проекте есть метрики со свободными замерами (free_checkpoints, `recorded_at`) и метрики со свободными интервалами (free_intervals, `time_start`–`time_end`). Сейчас корреляции для них считаются только на уровне дня (среднее за день). Нужно сопоставлять записи ВНУТРИ дня по времени.

## Scope

Две фичи для пар free_checkpoints x free_intervals. Любые типы метрик.

### Фича 1: Value During — "значение во время интервала"

Сопоставляет замеры free_cp метрики с интервалами free_iv метрики по времени: `recorded_at` попадает в `[time_start, time_end]`.

**Три типа источников:**

1. **Per-option (enum free_iv):** для каждого варианта enum — отдельный источник. "Настроение во время Работы", "Настроение во время Прогулки".
2. **Aggregate (не-enum free_iv):** один источник на всю метрику. "Настроение во время Тренировки".
3. **Outside:** замеры, не попавшие ни в один интервал метрики-контекста. "Настроение вне интервалов Активности".

**Агрегация за день:** если несколько замеров попали в один тип интервала — среднее.

**Пропуск:** если за день ни один замер не попал в интервал — у "value during" источников нет значения за этот день. У "outside" источника нет значения, если ВСЕ замеры попали в интервалы.

### Фича 2: Delta Between — "изменение после интервала"

Берёт пары последовательных замеров free_cp метрики (по `recorded_at`), вычисляет delta, и привязывает её к интервалу free_iv метрики, который был МЕЖДУ этими замерами.

**Источники:**

1. **Per-option (enum free_iv):** "Delta настроения после Работы", "Delta настроения после Прогулки".
2. **Aggregate (не-enum free_iv):** "Delta настроения после Тренировки".

Без источника "delta вне интервалов" (out of scope).

**Матчинг:** интервал считается "между замерами", если `time_start >= recorded_at[i]` и `time_end <= recorded_at[i+1]` (интервал целиком умещается между двумя замерами). Если между двумя замерами несколько интервалов одного типа — delta привязывается к последнему (ближайшему к замеру "после").

**Агрегация за день:** если за день несколько delta для одного типа интервала — среднее.

**Пропуск:** если между парой замеров нет интервала — эта пара не даёт delta. Если за весь день нет ни одной пары с интервалом — пропуск.

## Edge Cases

### Граница интервала
Замер с `recorded_at` ровно равным `time_start` считается попавшим в интервал (>=). Замер с `recorded_at` равным `time_end` — НЕ попал (строго <). Т.е. интервал `[time_start, time_end)`.

### Несколько интервалов между замерами (фича 2)
Между двумя замерами может быть несколько интервалов разных типов. Каждый даёт свою delta (одинаковую по значению, но привязанную к разным типам). Пример: замер 9:00(5) → Работа 9:30–12:00 → Прогулка 12:30–14:00 → замер 15:00(8). Delta=+3 привязывается и к Работе, и к Прогулке.

### Нет free_iv метрик или нет free_cp метрик
Кросс-источники не создаются. Engine работает как раньше.

### Метрика является и free_cp, и free_iv одновременно
Невозможно — `interval_binding` принимает одно значение.

## Архитектура

### Новые AutoSourceType

```python
# source_key.py
CROSS_VALUE_DURING = "cross_value_during"    # значение free_cp во время free_iv
CROSS_VALUE_OUTSIDE = "cross_value_outside"  # значение free_cp вне интервалов free_iv
CROSS_DELTA_BETWEEN = "cross_delta_between"  # delta free_cp после free_iv
```

### Расширение SourceKey

Новое поле `target_metric_id` — ссылка на метрику-контекст (free_iv).

```python
# source_key.py — SourceKey dataclass
target_metric_id: int | None = None  # для кросс-источников: id free_iv метрики
```

### Source Key формат

```
auto:cross_value_during:metric:{cp_id}:target:{iv_id}                 — не-enum free_iv
auto:cross_value_during:metric:{cp_id}:target:{iv_id}:opt:{option_id} — enum free_iv, per option
auto:cross_value_outside:metric:{cp_id}:target:{iv_id}                — вне интервалов
auto:cross_delta_between:metric:{cp_id}:target:{iv_id}                — не-enum free_iv
auto:cross_delta_between:metric:{cp_id}:target:{iv_id}:opt:{option_id} — enum free_iv, per option
```

### Поток данных в CorrelationEngine

Кросс-источники вычисляются в фазе 4 (auto-sources):

1. Engine находит все пары (free_cp метрика, free_iv метрика) среди enabled метрик
2. Для каждой пары загружает:
   - free_cp записи с `recorded_at` и значением, сгруппированные по дате
   - free_iv записи с `time_start`, `time_end` и значением (enum option или другое), сгруппированные по дате
3. Передаёт данные в `compute_auto_source()` (registry.py)
4. Registry вычисляет матчинг по времени, возвращает `{дата: float}`
5. Результат попадает в `_source_data` и дальше в стандартный pipeline

### Новые методы в ValueFetcher

```python
async def free_cp_entries_by_date(self, metric_id: int, start: date, end: date) -> dict[str, list[tuple[time, float]]]:
    """Загружает free_cp записи: {дата: [(recorded_at_time, value), ...]}"""

async def free_iv_entries_by_date(self, metric_id: int, start: date, end: date) -> dict[str, list[tuple[time, time, Any]]]:
    """Загружает free_iv записи: {дата: [(time_start, time_end, value), ...]}"""
```

### Новые SQL в AnalyticsRepository

Два новых метода для загрузки записей с временными метками:
- `fetch_free_cp_with_time()` — entries JOIN values_{type}, WHERE is_free_checkpoint, возвращает (date, recorded_at, value)
- `fetch_free_iv_with_time()` — entries JOIN values_{type}, WHERE is_free_interval, возвращает (date, time_start, time_end, value)

### Вычисление в auto_sources/registry.py

Новый входной датакласс:

```python
@dataclass
class CrossSourceInput:
    cp_entries: dict[str, list[tuple[time, float]]]  # {date: [(recorded_at, value), ...]}
    iv_entries: dict[str, list[tuple[time, time, Any]]]  # {date: [(start, end, value/option_id), ...]}
    option_id: int | None  # для enum: фильтр по option; None = все интервалы
```

Три функции вычисления:

```python
def compute_cross_value_during(inp: CrossSourceInput) -> dict[str, float]:
    """Для каждого дня: среднее значений cp, чей recorded_at in [iv.start, iv.end)"""

def compute_cross_value_outside(inp: CrossSourceInput) -> dict[str, float]:
    """Для каждого дня: среднее значений cp, не попавших ни в один интервал"""

def compute_cross_delta_between(inp: CrossSourceInput) -> dict[str, float]:
    """Для каждого дня: среднее delta между последовательными cp, если интервал целиком между ними"""
```

### SourceReconstructor

Обновить для поддержки кросс-источников — нужен для отображения графика пары на фронтенде.

### CorrelationPairResult

Новое поле `target_metric_a_id` и `target_metric_b_id` (nullable) в результате и в таблице `correlation_pairs` — чтобы сохранить связь с метрикой-контекстом.

## Количество источников

Для N free_cp метрик и M free_iv метрик:
- Фича 1 (value during): N * M * (avg_options + 1) источников (+1 за outside)
- Фича 2 (delta between): N * M * avg_options источников

При типичных 2-3 free_cp и 1-2 free_iv метриках: 10-30 новых источников. Не взрывает комбинаторику.

## Тесты

- Unit-тесты для `compute_cross_value_during`, `compute_cross_value_outside`, `compute_cross_delta_between` — чистые функции, легко тестировать
- Unit-тесты для `SourceKey.to_str()` / `SourceKey.parse()` с новым форматом
- API-тест: создать free_cp и free_iv метрики, внести данные, запустить корреляцию, проверить что кросс-источники появились в результатах
- Edge case тесты: пустые дни, замер на границе интервала, несколько интервалов между замерами

## Не в scope

- free_cp x free_cp (сопоставление двух метрик со свободными замерами)
- free_iv x free_iv (сопоставление двух метрик со свободными интервалами)
- Кросс-источники для обычных (не-free) чекпоинтов и интервалов
- Delta "вне интервалов" для фичи 2
- Фронтенд: отображение кросс-источников (они автоматически появятся в существующем UI корреляций)
