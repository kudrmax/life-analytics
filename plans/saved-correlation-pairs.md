# Plan: Избранное и архив корреляционных пар

## Context

Корреляционные отчёты эфемерны — при пересчёте все старые пары удаляются (`DELETE FROM correlation_reports WHERE id != $2` → CASCADE). Пользователь не может отметить интересную пару как "избранное" — при следующем пересчёте она исчезнет.

**Цель:** дать возможность сохранять пары в избранное/архив. Сохранённые пары живут независимо от отчётов. При пересчёте их снапшот обновляется автоматически. Если пара исчезает из нового отчёта — она остаётся со старыми данными и помечается как stale.

**Ключевое решение:** закладка хранит `(source_key_a, source_key_b, lag_days)` — детерминистический ключ, а не FK на `correlation_pairs.id`. Это гарантирует выживание закладки при пересчёте.

---

## Шаг 1. Таблица `saved_correlation_pairs`

### `database.py` — DDL:

```sql
CREATE TABLE IF NOT EXISTS saved_correlation_pairs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_key_a VARCHAR(100) NOT NULL,
    source_key_b VARCHAR(100) NOT NULL,
    lag_days INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'favorite',
    last_correlation FLOAT,
    last_data_points INTEGER,
    last_p_value FLOAT,
    last_type_a VARCHAR(20) NOT NULL DEFAULT '',
    last_type_b VARCHAR(20) NOT NULL DEFAULT '',
    last_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, source_key_a, source_key_b, lag_days)
);
CREATE INDEX IF NOT EXISTS idx_saved_corr_pairs_user ON saved_correlation_pairs(user_id);
```

`status` = `'favorite'` | `'archived'`.

Нет FK на `correlation_pairs` или `correlation_reports` — намеренно.

### `migrations.py` — миграция 12:

```sql
CREATE TABLE IF NOT EXISTS saved_correlation_pairs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_key_a VARCHAR(100) NOT NULL,
    source_key_b VARCHAR(100) NOT NULL,
    lag_days INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'favorite',
    last_correlation FLOAT,
    last_data_points INTEGER,
    last_p_value FLOAT,
    last_type_a VARCHAR(20) NOT NULL DEFAULT '',
    last_type_b VARCHAR(20) NOT NULL DEFAULT '',
    last_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, source_key_a, source_key_b, lag_days)
);
CREATE INDEX IF NOT EXISTS idx_saved_corr_pairs_user ON saved_correlation_pairs(user_id);
```

---

## Шаг 2. Обновление снапшотов в `_compute_report()`

**Файл:** `backend/app/routers/analytics.py`, в конце `_compute_report()` — после INSERT пар и UPDATE status='done', **перед** DELETE старых отчётов.

```python
# Обновить снапшоты сохранённых пар
await conn.execute("""
    UPDATE saved_correlation_pairs sp
    SET last_correlation = cp.correlation,
        last_data_points = cp.data_points,
        last_p_value = cp.p_value,
        last_type_a = cp.type_a,
        last_type_b = cp.type_b,
        last_updated_at = now()
    FROM correlation_pairs cp
    WHERE cp.report_id = $1
      AND sp.user_id = $2
      AND sp.source_key_a = cp.source_key_a
      AND sp.source_key_b = cp.source_key_b
      AND sp.lag_days = cp.lag_days
""", report_id, user_id)
```

Один SQL, без цикла. Пары без совпадения — не обновляются (stale).

---

## Шаг 3. API эндпоинты

Добавить в `backend/app/routers/analytics.py`:

### `POST /api/analytics/saved-pairs`

Body: `{ source_key_a, source_key_b, lag_days, status? }` (status default = "favorite")

Логика:
1. INSERT ON CONFLICT (user_id, source_key_a, source_key_b, lag_days) DO UPDATE SET status = $status
2. Сразу копировать снапшот из текущего `correlation_pairs` (если отчёт существует):
```sql
SELECT correlation, data_points, p_value, type_a, type_b
FROM correlation_pairs cp
JOIN correlation_reports cr ON cr.id = cp.report_id
WHERE cr.user_id = $1 AND cr.status = 'done'
  AND cp.source_key_a = $2 AND cp.source_key_b = $3 AND cp.lag_days = $4
LIMIT 1
```
3. Вернуть `{ id, status }`

### `DELETE /api/analytics/saved-pairs/{id}`

Удалить закладку. Проверка `user_id`.

### `PATCH /api/analytics/saved-pairs/{id}`

Body: `{ status }` — `"favorite"` или `"archived"`. Проверка `user_id`.

### `GET /api/analytics/saved-pairs`

Query params: `status` (optional, default = all).

Логика:
1. SELECT из `saved_correlation_pairs` WHERE user_id = $1 [AND status = $2]
2. Batch-lookup: parse all source_keys → собрать metric_ids, enum_option_ids, auto_parent_metric_ids
3. Batch SELECT metric_definitions (name, icon, private), enum_options (label)
4. Вычислить stale: сравнить `last_updated_at` с `MAX(created_at) FROM correlation_reports WHERE user_id = $1 AND status = 'done'`
5. Обогатить каждую пару через `_build_display_label()` / `_resolve_icon()` — переиспользовать существующие хелперы
6. Вернуть формат аналогичный `_format_pair()` + `stale: bool` + `saved_status` + `saved_id`

---

## Шаг 4. Расширить `get_correlation_pairs()` response

В SQL запросе `get_correlation_pairs()` добавить LEFT JOIN:

```sql
LEFT JOIN saved_correlation_pairs sp
  ON sp.user_id = $user_id_param
  AND sp.source_key_a = cp.source_key_a
  AND sp.source_key_b = cp.source_key_b
  AND sp.lag_days = cp.lag_days
```

В `_format_pair()` добавить поля:
```python
"source_key_a": p["source_key_a"],
"source_key_b": p["source_key_b"],
"saved_status": p.get("saved_status"),   # "favorite" | "archived" | None
"saved_id": p.get("saved_id"),           # int | None
```

---

## Шаг 5. Frontend: API методы

**Файл:** `frontend/js/api.js`

```javascript
async saveCorrelationPair(sourceKeyA, sourceKeyB, lagDays, status = 'favorite') {
    return this.request('POST', '/api/analytics/saved-pairs', {
        source_key_a: sourceKeyA, source_key_b: sourceKeyB,
        lag_days: lagDays, status,
    });
},
async unsaveCorrelationPair(id) {
    return this.request('DELETE', `/api/analytics/saved-pairs/${id}`);
},
async updateSavedPairStatus(id, status) {
    return this.request('PATCH', `/api/analytics/saved-pairs/${id}`, { status });
},
async getSavedCorrelationPairs(status = null) {
    const params = status ? `?status=${status}` : '';
    return this.request('GET', `/api/analytics/saved-pairs${params}`);
},
```

---

## Шаг 6. Frontend: UI

**Файл:** `frontend/js/app.js`

### В `renderCorrPair()`:

Добавить source_key_a, source_key_b, lag_days в `corrPairData` Map.

### Кнопка ★ на каждой паре:

Рядом с кнопкой "i", добавить кнопку ★:

```html
<button class="corr-save-btn ${p.saved_status === 'favorite' ? 'active' : ''}"
        data-pair-id="${pairId}">★</button>
```

Стиль `corr-save-btn`: аналогичен `btn-icon-tiny` — без бордера, dim color, при `.active` — `color: var(--accent)`.

### Обработчик клика:

```javascript
const saveBtn = e.target.closest('.corr-save-btn');
if (saveBtn) {
    const d = corrPairData.get(saveBtn.dataset.pairId);
    if (!d) return;
    if (d.savedId) {
        await api.unsaveCorrelationPair(d.savedId);
        d.savedId = null;
        saveBtn.classList.remove('active');
    } else {
        const result = await api.saveCorrelationPair(d.sourceKeyA, d.sourceKeyB, d.lagDays);
        d.savedId = result.id;
        saveBtn.classList.add('active');
    }
}
```

### Вкладки на странице Анализ:

Под header: **Все** | **★ Избранное** | **Архив**

- **Все** — текущее поведение
- **★ Избранное** — `GET /api/analytics/saved-pairs?status=favorite`
- **Архив** — `GET /api/analytics/saved-pairs?status=archived`

Stale пары: `opacity: 0.6` + бейдж "устарело"

### Кнопка архивации:

В detail panel добавить кнопку "В архив" / "Из архива".

---

## Определение stale

Пара считается stale если `last_updated_at IS NULL` или `last_updated_at < (SELECT MAX(created_at) FROM correlation_reports WHERE user_id = $1 AND status = 'done')`.

Вычисляется на лету в `GET /api/analytics/saved-pairs`, не хранится как флаг.

---

## Файлы для изменения

| Файл | Тип изменения |
|---|---|
| `backend/app/database.py` | DDL новой таблицы + индекс |
| `backend/app/migrations.py` | Миграция 12 |
| `backend/app/routers/analytics.py` | 4 эндпоинта + update снапшотов в `_compute_report` + LEFT JOIN в `get_correlation_pairs` + расширение `_format_pair` |
| `frontend/js/api.js` | 4 API метода |
| `frontend/js/app.js` | Кнопка ★, обработчик, вкладки, stale-стиль |
| `frontend/css/style.css` | Стили: `.corr-save-btn`, `.stale-badge` |
| `db_schema.puml` | Новая entity + relationship |
| `CLAUDE.md` | Документация таблицы и паттерна |

## Порядок выполнения

1. `database.py` + `migrations.py` — таблица
2. `analytics.py` — backend: эндпоинты + update снапшотов + LEFT JOIN + _format_pair
3. `api.js` — frontend API методы
4. `app.js` + `style.css` — UI: кнопка, вкладки, stale
5. `db_schema.puml` + `CLAUDE.md` — документация

## Верификация

1. `make build-up` — пересобрать и запустить
2. `make logs-backend` — миграция 12 applied, нет ошибок
3. Анализ → запустить корреляционный отчёт → дождаться завершения
4. Кликнуть ★ на паре → проверить что пара сохранена (POST возвращает id)
5. Переключить на вкладку "★ Избранное" → пара отображается
6. Запустить пересчёт → убедиться что снапшот обновлён (GET saved-pairs → last_updated_at свежая)
7. Удалить метрику → saved pair показывает "Удалённая метрика" + stale бейдж
8. "В архив" → пара перемещается на вкладку "Архив"
9. Убрать из избранного (★ → DELETE) → пара исчезает
10. `docker exec ... psql ... -c "SELECT * FROM saved_correlation_pairs"` — проверить данные в БД
