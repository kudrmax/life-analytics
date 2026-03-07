# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Life Analytics — multi-user daily metrics tracker. FastAPI + PostgreSQL backend, vanilla JS SPA frontend, Docker Compose deployment.

## Commands

```bash
# Run everything (Docker Compose — preferred)
make up                     # запустить сервисы (быстро, офлайн)
make build-up               # пересобрать образы и запустить (после изменений кода)

# Run locally (without Docker — needs local PostgreSQL)
cd backend && source venv/bin/activate
python -m uvicorn app.main:app --reload --port 8000
cd frontend && python -m http.server 3000

# Logs
make logs                   # all services
make logs-backend           # backend only

# Database access
docker exec -it life-analytics-db-1 psql -U la_user -d life_analytics

# Restart / update
make restart                # restart backend only
make update                 # git pull + rebuild
make down                   # stop all

# Production (с локальной машины, нужен VPS_HOST)
VPS_HOST=<IP> make deploy       # ручной деплой на VPS через SSH
VPS_HOST=<IP> make ssh          # подключиться к VPS
VPS_HOST=<IP> make prod-logs    # логи production
VPS_HOST=<IP> make prod-status  # статус контейнеров
VPS_HOST=<IP> make prod-db      # подключиться к production БД

# Backup (requires YADISK_TOKEN in .env)
make backup-up              # start backup service
make backup-down            # stop backup service
make backup-logs            # view backup logs
make backup-now             # run one-off backup immediately
```

**URLs:** Frontend :3000, Backend :8000, API docs :8000/docs, Health check: GET /api/health

**No tests exist in this project.**

Frontend is served by `python -m http.server` (local) or nginx (Docker). Both serve files from disk on each request — no restart needed for JS/CSS/HTML changes, just refresh the browser.

## Architecture

### Backend (FastAPI + asyncpg + PostgreSQL)

- `main.py` — FastAPI app with lifespan (creates/closes asyncpg pool, runs `init_db`, runs `migrations`)
- `migrations.py` — lightweight DB migrations (schema_migrations table, version-based SQL)
- `database.py` — asyncpg pool management, full DDL schema in `init_db()` (tables, enums, indexes)
- `auth.py` — JWT (HS256, 7-day expiry), bcrypt hashing, `get_current_user` dependency
- `schemas.py` — Pydantic models for all request/response types
- `metric_helpers.py` — shared value read/write logic across routers; `build_metric_out` converts DB rows to response models with slots

**Routers** (all under `/api/`): `auth`, `metrics`, `entries`, `daily`, `analytics`, `export_import`, `integrations`

### Database Schema (PostgreSQL)

**Enum:** `metric_type` = 'bool' | 'time' | 'number' | 'duration' | 'scale' | 'computed' | 'integration'

**Tables:**
- `users` — id, username (unique), password_hash, created_at
- `metric_definitions` — id, user_id (FK), slug, name, category, icon, type (enum), enabled, sort_order; UNIQUE(user_id, slug)
- `measurement_slots` — id, metric_id (FK), sort_order, label, enabled (for multi-slot metrics like Утро/День/Вечер)
- `entries` — id, metric_id (FK), user_id (FK), date, recorded_at, slot_id (FK, nullable)
- `values_bool` — entry_id (PK/FK), value BOOLEAN
- `values_time` — entry_id (PK/FK), value TIMESTAMPTZ
- `values_number` — entry_id (PK/FK), value INTEGER
- `values_duration` — entry_id (PK/FK), value INTEGER (minutes)
- `values_scale` — entry_id (PK/FK), value INTEGER, scale_min, scale_max, scale_step (stores context at time of entry)
- `scale_config` — metric_id (PK/FK), scale_min, scale_max, scale_step (current config for rendering)
- `correlation_reports` — id, user_id (FK), status ('running'/'done'/'error'), period_start, period_end, created_at, finished_at
- `correlation_pairs` — id, report_id (FK), metric_a_id, metric_b_id, slot_a_id, slot_b_id, label_a, label_b, type_a, type_b, correlation (FLOAT), data_points (INTEGER)
- `user_integrations` — id, user_id (FK), provider (VARCHAR), encrypted_token (TEXT), enabled, created_at; UNIQUE(user_id, provider)
- `integration_config` — metric_id (PK/FK), provider (VARCHAR), metric_key (VARCHAR), value_type (VARCHAR)
- `integration_filter_config` — metric_id (PK/FK), filter_name VARCHAR(200) — config for filter_tasks_count metrics
- `integration_query_config` — metric_id (PK/FK), filter_query VARCHAR(1024) — config for query_tasks_count metrics
- `activitywatch_settings` — user_id (PK/FK), enabled, aw_url, created_at
- `activitywatch_daily_summary` — id, user_id (FK), date, total_seconds, active_seconds, synced_at; UNIQUE(user_id, date)
- `activitywatch_app_usage` — id, user_id (FK), date, app_name, source ('window'|'web'), duration_seconds; UNIQUE(user_id, date, app_name, source)

**Entry uniqueness (partial indexes):** Metrics without slots: `UNIQUE(metric_id, user_id, date) WHERE slot_id IS NULL`. Metrics with slots: `UNIQUE(metric_id, user_id, date, slot_id) WHERE slot_id IS NOT NULL`.

**Value storage pattern:** Separate typed table per metric type (not JSON). Entry creation: INSERT into `entries` → INSERT into `values_{type}`, all within a transaction.

**Scale context pattern:** `scale_config` stores the current min/max/step for rendering buttons. `values_scale` stores the min/max/step that were active when each entry was created. When displaying a filled entry, use context from `values_scale` (not current config) so old entries render correctly even after config changes. Analytics normalizes scale values to percentages using the per-entry context.

**Multi-slot pattern:** A metric can have 2+ measurement slots (e.g. Утро, День, Вечер). `measurement_slots` stores slot definitions per metric. `entries.slot_id` links an entry to a specific slot. Daily endpoint aggregates multi-slot data, showing each slot's value separately.

### Frontend (Vanilla JS SPA)

- `index.html` — single entry point with nav, Lucide icons, emoji-picker-element, Chart.js (all vendored in `vendor/`)
- `config.js` — `window.API_BASE` (empty for Docker/nginx proxy)
- `js/api.js` — API client, token in localStorage (`la_auth_token`), auto-redirect on 401
- `js/app.js` — all page logic: routing, rendering, event handling
- `css/style.css` — dark/light theme via CSS custom properties

**Navigation:** Сегодня, Статистика, Анализ, История, Настройки.

**Routing:** `navigateTo(page, params = {})` — поддерживает параметры (e.g. `{ metricId }`, `{ openAddModal: true }`).

**Pages:**
- Сегодня (today): ввод метрик за текущий день; `today-actions` кнопки «Добавить метрику» / «Редактировать метрики»
- Статистика (charts): `stats-header` с выбором периода, тренды с мини-чартами для всех метрик + ActivityWatch
- Анализ (analysis): `stats-header` с выбором периода, корреляционные отчёты с polling
- Детализация метрики (metric-detail): Chart.js графики (bar для bool, line для остальных); переход через `navigateTo('metric-detail', { metricId })`; кнопка «Назад» ведёт на `charts`; `detailChartInstance` глобальная переменная для cleanup
- Настройки (settings): принимает `{ openAddModal: true }` для автооткрытия модалки добавления метрики; раздел "Интеграции" внизу с кнопками подключения/отключения Todoist

**Event delegation pattern:** `#metrics-form` element persists across re-renders (innerHTML replaced). Event listeners (click, change) are attached once via `data-handlersAttached` guard in `attachInputHandlers()` to prevent duplicate async handlers.

**Icons:** Lucide icons via CDN (`<i data-lucide="...">` → `lucide.createIcons()`). Emoji icons on metrics via emoji-picker-element. Metric icons rendered in `<span class="metric-icon">` wrapper.

### Deployment (Docker Compose)

Three services: `db` (postgres:16-alpine), `backend` (Python 3.12-slim + uvicorn), `frontend` (nginx:alpine proxies `/api/` to backend).

Optional service (profile `backup`): `backup` (Python 3.12-alpine + pg_dump + yadisk) — periodic PostgreSQL dumps uploaded to Yandex Disk. Not started by default; activate with `docker compose --profile backup up` or `make backup-up`.

## Environment Variables

```
DATABASE_URL=postgresql://la_user:la_password@db:5432/life_analytics
LA_SECRET_KEY=change-me-in-production
POSTGRES_USER=la_user
POSTGRES_PASSWORD=la_password
POSTGRES_DB=life_analytics
```

```
# Backup (only used with --profile backup)
YADISK_TOKEN=your-yandex-disk-oauth-token
YADISK_BACKUP_PATH=/life-analytics-backups/
BACKUP_INTERVAL_MINUTES=360
BACKUP_RETAIN_DAYS=30
```

```
# Todoist integration (optional)
TODOIST_CLIENT_ID=           # from https://developer.todoist.com/appconsole.html
TODOIST_CLIENT_SECRET=       # from the same page
```

See `.env.example`. Defaults work for local Docker Compose dev.

## Key Implementation Details

**Backend-first logic:** All business logic lives on the backend. Frontend is a thin client — display and input only. Criterion: imagine a second, different frontend exists; avoid any logic duplication. Examples: available integration metrics registry — served via endpoint, not hardcoded on frontend; validation — backend only; value_type resolution — backend only.

**Adding a new metric type** requires changes in 8 places:
1. `database.py` — `ALTER TYPE metric_type ADD VALUE`, create `values_{type}` table (+ config table if type has settings)
2. `schemas.py` — add to `MetricType` enum, add config fields to Create/Update/Out if needed (keep `bool` before `int` in value unions — bool is subclass of int in Python)
3. `metric_helpers.py` — add branch in `get_entry_value`, `insert_value`, `update_value`; pass `metric_id` for types that need config lookup
4. `routers/metrics.py` — LEFT JOIN config table in list/get queries, handle config creation/update in create/update endpoints
5. `routers/daily.py` — LEFT JOIN config table, include config fields in response; for filled entries, override with stored context from value table
6. `routers/analytics.py` — `_extract_numeric` + value_table selection in `trends` and `values_by_date`; include extra columns (e.g. scale context) in SELECT
7. `routers/export_import.py` — type validation on import + value parsing + config export/import
8. `frontend/js/app.js` — render function, input handlers, history display, settings type label, modal (preview + radio + type hint + config fields)

**Integration pattern (Todoist):**
- OAuth flow: `GET /api/integrations/todoist/auth-url` (JWT-protected) → redirect to Todoist → `GET /api/integrations/todoist/callback` (no JWT, uses state JWT) → saves token to user_integrations
- User creates integration metrics manually via modal (type=integration, provider=todoist, metric_key from registry)
- Registry: `integrations/todoist/registry.py` — TODOIST_METRICS dict with metric_key → {name, value_type, config_fields}
- Available metric_keys: `completed_tasks_count` (no config), `filter_tasks_count` (requires filter_name in integration_filter_config), `query_tasks_count` (requires filter_query in integration_query_config)
- Data fetch: `POST /api/integrations/{provider}/fetch` → service layer dispatches by metric_key, returns {results, errors}
- Architecture: `integrations/todoist/client.py` (pure API client: completed tasks, Sync API filters, Filter API query) → `integrations/todoist/service.py` (DB + client orchestration) → `routers/integrations.py` (HTTP layer)
- Token encryption: Fernet symmetric encryption via `encryption.py`, key derived from LA_SECRET_KEY
- Integration metrics store values in values_* table per value_type, display as read-only with fetch button on frontend
- Env vars: `TODOIST_CLIENT_ID`, `TODOIST_CLIENT_SECRET`

**Integration pattern (ActivityWatch):**
- No OAuth — AW runs locally on user's machine (localhost:5600), no token needed
- Frontend acts as bridge: fetches raw events from AW on localhost, sends to backend
- Architecture: `frontend/js/aw-client.js` (local AW API client) → `routers/integrations.py` (receives raw events) → `integrations/activitywatch/service.py` (processes events, computes active time, stores aggregates)
- Dedicated tables (not metrics): `activitywatch_settings`, `activitywatch_daily_summary`, `activitywatch_app_usage`
- Processing: intersects window events with not-afk intervals to compute active time per app; extracts domains from web events
- Endpoints: `POST .../activitywatch/sync`, `GET .../activitywatch/summary`, `GET .../activitywatch/trends`, `GET .../activitywatch/status`, `POST .../activitywatch/enable`, `DELETE .../activitywatch/disable`
- Correlation: auto-source "Экранное время (активное)" in `_compute_report` reads from `activitywatch_daily_summary`
- Export/Import: `aw_daily.csv` + `aw_apps.csv` in ZIP (optional files)

**Analytics endpoints:**
- `GET /api/analytics/trends` — тренды метрик за период
- `GET /api/analytics/metric-stats` — статистика по метрике (streaks, avg, min/max)
- `POST /api/analytics/correlation-report` — запуск фонового расчёта всех попарных корреляций
- `GET /api/analytics/correlation-reports` — список отчётов
- `GET /api/analytics/correlation-report/{id}` — детали отчёта с парами

**Correlation reports pattern:**
- Background: `asyncio.create_task(_compute_report(...))` в том же процессе
- Data sources: каждая метрика со слотами → N+1 sources (среднее + каждый слот)
- P-value: вычисляется на лету при GET через `_p_value(r, n)` (t-test + beta distribution)
- Фронтенд: polling каждые 3 секунды до завершения

**Data isolation:** All queries filter by `current_user["id"]`. Return 404 (not 403) on unauthorized access.

**Schema changes:** Update DDL in `database.py` `init_db()`. For new enum values, use `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (safe for existing DBs). For new tables, use `CREATE TABLE IF NOT EXISTS`. For altering existing tables (add column, change type), add a migration to `migrations.py` AND update DDL in `init_db()`. **Always update `db_schema.puml`** (PlantUML ER-diagram in project root) to reflect any table/column/relationship changes.

**Migrations:** `migrations.py` — lightweight version-based system. `schema_migrations` table tracks applied versions. Migrations run automatically on backend startup after `init_db()`. Each migration: `(version_int, description, sql)`. Always use `IF NOT EXISTS` / `IF EXISTS` in migration SQL for idempotency.

**Deployment:** Docker Compose on VDSina VPS. Auto-deploy via GitHub Actions on push to master (SSH → git pull → docker compose up --build). Memory limits set in docker-compose.yml (512M db, 512M backend, 64M frontend). PostgreSQL tuned for 2 GB RAM. Swap 2 GB on VPS for safety.

**Metric queries with config:** Routers that list/return metrics use LEFT JOIN to include type-specific config (e.g. `LEFT JOIN scale_config sc ON sc.metric_id = md.id`). The `build_metric_out` helper uses `.get()` for config fields since they may be NULL for non-matching types.

## Performance Instrumentation

Lightweight timing is instrumented across all layers. No extra dependencies — stdlib `logging` + `time.perf_counter()` on backend, `performance.now()` + `console.debug` on frontend, `$upstream_response_time` in nginx.

**Key files:**
- `backend/app/timing.py` — `timed_fetch()` (single query wrapper) + `QueryTimer` (multi-query checkpoint timer)
- `backend/app/main.py` — `TimingMiddleware` logs every request (method, path, status, ms); SLOW threshold 500ms (env `SLOW_REQUEST_MS`)
- `backend/app/routers/daily.py` — `QueryTimer` checkpoints: metrics, entries, slots, disabled_slots, values, build
- `backend/app/routers/analytics.py` — `QueryTimer` in `_compute_report`, `trends`, `metric_stats`
- `frontend/js/api.js` — `performance.now()` around `fetch()` in `api.request()`, cache HIT/MISS in `cachedGet()`
- `frontend/js/app.js` — render timing in `renderTodayForm`, `updateHistoryView`, `loadDashboard`, `loadMetricDetail`, `renderSettings`
- `frontend/nginx.conf` — `log_format timing` with `$request_time` + `$upstream_response_time` for `/api/`

**How to collect data:**
1. VPS: `VPS_HOST=<IP> make prod-logs` — real-time logs
2. Browser: DevTools → Console → enable "Verbose" filter
3. Perform action in UI

**Log format per layer:**

| Layer | Format | Measures |
|---|---|---|
| nginx | `req=0.051 upstr=0.049` | Full request time / backend time |
| backend middleware | `[timing] GET /api/daily/... -> 200  49ms` | Total request processing |
| backend DB | `[app.db] [daily/...] total=34ms metrics=12ms ...` | Per-SQL-query breakdown |
| frontend API | `[api] GET /api/daily/... -> 200  280ms` | fetch() to response (network + backend) |
| frontend render | `[render] today  310ms` | Full page render time |

**Bottleneck diagnostic tree:**
```
1. Compare frontend [api] ms vs nginx req= → big gap = client DNS/TLS/network
2. Compare nginx req= vs upstr= → big gap = nginx overhead (gzip, buffering)
3. Compare backend [timing] ms vs [app.db] total= → big gap = Python CPU (serialization, formulas)
4. Look at [app.db] breakdown → which SQL query is slow
5. Compare frontend [render] ms vs [api] ms → big gap = JS rendering (DOM, Chart.js)
```

**Thresholds:** SLOW request WARNING: >500ms (`SLOW_REQUEST_MS` env). SLOW SQL WARNING: >200ms. For verbose DB logs: `LOG_LEVEL=DEBUG` in `.env`.

## Common Workflows

**Add new router:**
1. Create `backend/app/routers/new_router.py` with `router = APIRouter(prefix="/api/path", tags=["tag"])`
2. Add `current_user = Depends(get_current_user)` to protected endpoints
3. Include in `main.py`: `app.include_router(new_router.router)`

**Export/Import format:**
- ZIP with `metrics.csv` (id, slug, name, category, type, enabled, sort_order, scale_min, scale_max, scale_step, icon, slot_labels as JSON) + `entries.csv` (date, metric_slug, value as JSON, slot_sort_order, slot_label)
- Import: creates/updates metrics by slug, recreates slots, skips duplicate entries

**Backup setup (production):**
1. Get Yandex Disk OAuth token at https://yandex.ru/dev/disk/poligon/
2. Add `YADISK_TOKEN=<token>` to `.env`
3. `make backup-up` — starts backup service (first backup runs immediately, then every 6 hours)
4. `make backup-logs` — verify "Backup cycle complete" in logs
5. Old backups auto-deleted after 30 days (configurable via `BACKUP_RETAIN_DAYS`)

Backup service uses Docker Compose profile `backup` — it does NOT start with regular `docker compose up` / `make up`.

**Makefile `make help`:** When adding or removing Makefile targets, always update the `help` target to keep it in sync. `make help` is the default goal (runs on bare `make`).
