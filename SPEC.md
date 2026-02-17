# Life Analytics — ТЗ v2

## Архитектура

**Backend** (Python + FastAPI + SQLite) — полноценный REST API, полностью независим от фронтенда.

**Frontend** (Web) — SPA, общается с backend только через API. Может быть заменён на что угодно.

---

## Типы метрик по частоте

### Разовые (раз в день)
Заполняются один раз, обычно вечером при подведении итогов.

| Метрика | Тип | Формат |
|---|---|---|
| Время подъёма | time | HH:MM |
| Время отбоя | time | HH:MM |
| Качество сна | scale | 1-5 |
| Тренировка | boolean + enum | да/нет + тип (кардио, силовая, растяжка...) |
| Алкоголь | boolean + number | да/нет + кол-во порций |
| Фастфуд | boolean | да/нет |
| Приёмов пищи | number | число |
| Кофе | number | чашек |
| Виделся с друзьями | boolean | да/нет |
| Новые знакомства | number | число |
| Медитация | boolean + number | да/нет + минуты |
| Чтение | boolean + number | да/нет + минуты |
| Часов продуктивной работы | number | часы |
| Экранное время | number | часы |
| Крупные траты | boolean + number | да/нет + сумма |
| Импульсивные покупки | boolean | да/нет |

### Многоразовые (несколько раз в день)
Можно отмечать в любой момент. Каждая запись — отдельная точка с timestamp.

| Метрика | Тип | Формат |
|---|---|---|
| Настроение | scale + timestamp | 1-5, в какое время |
| Уровень энергии | scale + timestamp | 1-5, в какое время |
| Уровень стресса | scale + timestamp | 1-5, в какое время |

Для многоразовых метрик в аналитике используется:
- **среднее за день**
- **мин/макс**
- **динамика внутри дня** (утро → день → вечер)

### Автоматические (из API)
| Метрика | Источник |
|---|---|
| Задач запланировано | Todoist API |
| Задач выполнено | Todoist API |
| Событий в календаре | Google Calendar API |

---

## Конфигурация метрик

Все метрики описываются в конфиге. Формат каждой:

```yaml
metrics:
  - id: mood
    name: "Настроение"
    category: "Ментальное"
    type: scale          # scale | boolean | number | time | enum | compound
    min: 1
    max: 5
    frequency: multiple  # daily | multiple
    source: manual       # manual | todoist | google_calendar
    enabled: true

  - id: alcohol
    name: "Алкоголь"
    category: "Здоровье"
    type: compound       # составной: boolean + number
    fields:
      - name: consumed
        type: boolean
      - name: amount
        type: number
        label: "Порций"
        condition: "consumed == true"  # показывать только если consumed = true
    frequency: daily
    source: manual
    enabled: true
```

Пользователь может: добавлять свои метрики, отключать ненужные, менять категории.

---

## API (ключевые эндпоинты)

```
# Метрики — конфигурация
GET    /api/metrics              — список всех метрик
POST   /api/metrics              — создать свою метрику
PATCH  /api/metrics/{id}         — изменить/отключить
DELETE /api/metrics/{id}         — удалить

# Записи
POST   /api/entries              — записать значение метрики
GET    /api/entries?date=...     — все записи за день
PUT    /api/entries/{id}         — изменить запись
DELETE /api/entries/{id}         — удалить запись

# Дневной отчёт
GET    /api/daily/{date}         — сводка за день (все метрики + агрегации)

# Аналитика
GET    /api/analytics/trends     — тренды за период
GET    /api/analytics/correlations — корреляции между метриками
GET    /api/analytics/streaks    — стрики

# Интеграции
POST   /api/integrations/sync    — подтянуть данные из Todoist/GCal
```

---

## Frontend — экраны

1. **Сегодня** — форма ввода разовых метрик + кнопки быстрого ввода многоразовых (нажал "настроение 4" — записалось с текущим временем)
2. **История** — календарь, клик по дню → сводка
3. **Дашборд** — графики трендов, стрики, корреляции
4. **Настройки** — управление метриками, интеграции

---

## Модель данных (SQLite)

```
metric_configs    — определения метрик (id, name, type, category, frequency, config_json)
entries           — записи (id, metric_id, date, timestamp, value_json)
integrations      — токены и настройки API (todoist, gcal)
```

`value_json` — гибкое хранение: `{"value": 4}`, `{"consumed": true, "amount": 3}`, `{"time": "07:30"}`.
