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

Frontend is served by `python -m http.server` (local) or nginx (Docker). Both serve files from disk on each request — no restart needed for JS/CSS/HTML changes, just refresh the browser.

## Testing

**Run tests:** `cd backend && python -m pytest tests/ -v`. Requires running PostgreSQL container (`make up`).

**Rule: always write tests.** Any backend change must include new or updated tests.

### Structure

- Tests live in `backend/tests/`
- `conftest.py`: session-scoped DB pool, autouse cleanup, helpers (`register_user`, `create_metric`, `create_checkpoint`, `create_entry`, `auth_headers`)
- Naming: `test_{module}_{type}.py` (e.g. `test_auth_api.py`, `test_auth_unit.py`)

### Test types

- **API tests** (integration): `AsyncClient` + httpx ASGI transport. Fixtures: `client`, `user_a`, `user_b`, `bool_metric`, `scale_metric`
- **Unit tests**: pure functions, no HTTP. `unittest.TestCase` or pytest classes

### Patterns

- One test class = one scenario (`class TestCreateBoolMetric`, `class TestDataIsolation`)
- Always test data isolation between users
- Test error cases (404, 409, 400) alongside happy path
- External APIs (Todoist) — mock via `unittest.mock.patch`

### When to add tests

- New endpoint → API test (CRUD + error cases + data isolation)
- New business function → unit test
- Bug fix → **must** write a test reproducing the bug BEFORE fixing
- Changed logic → update affected tests
- **Always run the full test suite** (`python -m pytest tests/ -v`), not just tests for changed files

### Test-first thinking

Define expected results from business logic understanding first, then write the test. If the test fails — decide what is wrong: the expectation or the code. Never adjust expected values to match actual program output.

## Architecture

### Backend — Clean Architecture

Four layers. Dependencies go strictly inward: **Router → Service → Repository → Domain**.

```
routers/          → HTTP controllers. Parse request → call service → return response.
services/         → Business logic orchestration. Receives repos via constructor.
repositories/     → SQL and DB row mapping. The ONLY layer that touches asyncpg.
domain/           → Pure models, enums, constants, exceptions. No external dependencies.
analytics/        → Computation engine (correlation_math, time_series, value_converter,
                    quality — pure modules without side effects).
```

**domain/** — clean models and business rules. No asyncpg, fastapi, httpx.
- `enums.py` — MetricType and other enums. Use EVERYWHERE instead of string literals.
- `constants.py` — named thresholds and numeric constants. Use EVERYWHERE instead of magic numbers.
- `exceptions.py` — EntityNotFoundError and other domain exceptions.
- `models.py` — dataclass models.
- `privacy.py` — mask_name, mask_icon, is_blocked.
- `formatters.py` — format_display_value, _parse_time.

**repositories/** — SQL and DB row mapping. The only layer with asyncpg.
- `base.py` — BaseRepository with _fetch_owned() pattern.
- One repository per aggregate: metric_repository, entry_repository, daily_repository, analytics_repository, correlation_repository, etc.
- `metric_repository.py` contains `_METRIC_WITH_CONFIG_SQL` constant — reused in daily_repository.

**services/** — business logic orchestration. Does NOT import asyncpg directly.
- Receives repositories via constructor.
- One service per domain: metrics_service, daily_service, correlation_service, etc.
- `daily_helpers.py` — pure helpers: `build_interval_label_map`, `split_by_checkpoints`, `evaluate_visibility`, `compute_formulas`, `build_auto_metrics`, `calculate_progress`.
- `metric_builder.py` — mapping DB row → MetricDefinitionOut.

**routers/** — thin HTTP controllers (all under `/api/`): auth, metrics, entries, daily, analytics, export_import, integrations, categories, checkpoints, notes, insights.
- Each endpoint: create repo → create service → call method → return. Max 10-15 lines.

**analytics/** — correlation engine and pure computation modules.
- Pure (no DB): correlation_math, time_series, value_converter, quality.
- pair_formatter — display label/icon resolution, uses checkpoint_labels for interval labels.
- value_fetcher — loads values for correlation sources.
- Engine: correlation_engine (orchestrates computation, receives dependencies from correlation_service).

### Architectural Rules (ENFORCE ON EVERY CHANGE)

1. **Dependency direction:** Router → Service → Repository → Domain. Never reverse.
2. **SQL lives in repositories/ only.** No SQL strings in services/, routers/, analytics/, domain/.
3. **Use MetricType enum** from `domain/enums.py` — never compare with string literals like `== "bool"`.
4. **Use named constants** from `domain/constants.py` — never hardcode thresholds (0.7, 0.05, 3600 etc.).
5. **Thin routers:** max 15 lines per endpoint. Create repo → create service → call → return.
6. **No god modules:** max 300 lines per file in domain/, repositories/, services/.
7. **Tests required:** every backend change must include tests. Run full suite, not just changed files.

### Patterns for new code

**New endpoint:**
```python
# routers/example.py
@router.get("/example/{id}")
async def get_example(id: int, db=Depends(get_db), user=Depends(get_current_user)):
    repo = ExampleRepository(db, user["id"])
    service = ExampleService(repo)
    return await service.get_by_id(id)
```

**New repository:**
```python
# repositories/example_repository.py
class ExampleRepository(BaseRepository):
    async def get_by_id(self, id: int):
        return await self._fetch_owned("example_table", id)
```

**New service:**
```python
# services/example_service.py
class ExampleService:
    def __init__(self, repo: ExampleRepository):
        self.repo = repo
    async def get_by_id(self, id: int):
        row = await self.repo.get_by_id(id)
        return dict(row)
```

### Database (PostgreSQL)

**No ORM** — raw asyncpg with hand-written SQL in repositories.

**Metric type enum:** `'bool' | 'enum' | 'time' | 'number' | 'duration' | 'scale' | 'computed' | 'integration' | 'text'`

**Key tables:** users, categories, metric_definitions, checkpoints, intervals, metric_checkpoints, metric_intervals, entries, values_{bool,time,number,scale,duration,enum}, scale_config, enum_config, enum_options, computed_config, notes, metric_condition, insights, insight_metrics, correlation_reports, correlation_pairs, user_integrations, integration_config, integration_filter_config, integration_query_config, activitywatch_settings, activitywatch_daily_summary, activitywatch_app_usage, activitywatch_categories, activitywatch_app_category_map, integration_app_config, integration_category_config.

Full DDL is in `database.py` `init_db()`. Read it for column details.

**Schema changes:** Update DDL in `database.py` `init_db()`. For new enum values: `ALTER TYPE ... ADD VALUE IF NOT EXISTS`. For altering existing tables: add migration to `migrations.py` AND update DDL. Always update `db_schema.puml`.

**Migrations:** `migrations.py` — version-based, runs on startup after `init_db()`. Use `IF NOT EXISTS` / `IF EXISTS` for idempotency.

### Key Data Patterns

**Value storage:** Separate typed table per metric type (not JSON). Entry creation: INSERT entries → INSERT values_{type}, within transaction. Handled by `entry_repository.py`.

**Entry uniqueness (partial indexes):** Without checkpoints/intervals: `UNIQUE(metric_id, user_id, date) WHERE checkpoint_id IS NULL AND interval_id IS NULL`. With checkpoint: `UNIQUE(metric_id, user_id, date, checkpoint_id) WHERE checkpoint_id IS NOT NULL`. With interval: `UNIQUE(metric_id, user_id, date, interval_id) WHERE interval_id IS NOT NULL`. Columns `checkpoint_id` and `interval_id` are mutually exclusive (CHECK constraint).

**Scale context:** `scale_config` = current rendering config. `values_scale` = config at time of entry. Display uses per-entry context so old entries render correctly after config changes. Analytics normalizes to percentages using per-entry context.

**Multi-checkpoint / Intervals:** `checkpoints` = глобальные per-user контрольные точки дня (renamed from measurement_slots), поле `description` — описание, soft-delete через `deleted` флаг. `intervals` = пары чекпоинтов (start_checkpoint_id + end_checkpoint_id), описывающие промежутки между контрольными точками. `metric_checkpoints` = junction table, связывает метрики с чекпоинтами. `metric_intervals` = junction table, связывает метрики с интервалами. `entries.checkpoint_id` — привязка записи к чекпоинту. `entries.interval_id` — привязка записи к интервалу. `checkpoint_id` и `interval_id` взаимоисключающие (CHECK constraint). `metric_definitions.all_checkpoints` — метрика привязана ко всем чекпоинтам. `metric_definitions.all_intervals` — метрика привязана ко всем интервалам. FK на `metric_checkpoints` и `metric_intervals` используют `ON DELETE CASCADE`.

**Checkpoints and Intervals:** `checkpoints` = чекпоинты (контрольные точки дня). `intervals` = промежутки между чекпоинтами (start_checkpoint_id → end_checkpoint_id). `metric_definitions.is_checkpoint` — true = оценка (замеряется В чекпоинтах), false = факт. `metric_definitions.interval_binding` — привязка факта к времени: `all_day` (весь день, без привязки), `by_interval` (выбранные интервалы между чекпоинтами), `moment` (одноразовый замер). Привязки к интервалам хранятся в `metric_intervals`, к чекпоинтам — в `metric_checkpoints`. Daily page: `split_by_checkpoints()` разбивает метрики по чекпоинтам (sandwich layout). `build_interval_label_map()` в `daily_helpers.py` строит лейблы "X → Y" для интервалов.

**Enum:** Options in `enum_options`, single/multi controlled by `enum_config.multi_select`. Values stored as `INTEGER[]` of option IDs. Options support soft-delete via `enabled`. In correlations: each option → separate boolean source.

**Text/Notes:** Text metrics use `notes` table (not entries/values_*). Multiple notes per metric per day. In correlations: `note_count` auto-source.

**Computed metrics:** Formula as JSONB token array in `computed_config`. Token types: metric, op (+−*/), number, lparen, rparen. Recursive descent evaluator. Result types: float, int, bool, time, duration. Restrictions: no refs to other computed metrics, no mixing time with non-time. Values computed on-the-fly, not stored.

**Metric conditions:** Conditional visibility on daily page. `metric_condition` table: depends_on_metric_id, condition_type (filled/equals/not_equals), condition_value (JSONB).

**Privacy mode:** `users.privacy_mode` + `metric_definitions.private`. When privacy ON: private metrics show masked name/icon, values hidden. Toggle: `PUT /api/auth/privacy-mode`.

**Metric conversion:** `GET /api/metrics/{id}/convert/preview` + `POST /api/metrics/{id}/convert`. Logic in `services/metric_conversion_service.py`.

**JSONB deserialization:** asyncpg does NOT auto-deserialize JSONB — returns raw strings. Every JSONB column must be `json.loads()` when read. When writing: `json.dumps(value)` + `::jsonb` cast.

**Data isolation:** All queries filter by `user_id`. Return 404 (not 403) on unauthorized access.

### Adding a new metric type

Requires changes in:
1. `database.py` — ALTER TYPE + CREATE TABLE values_{type} (+ config table if needed)
2. `migrations.py` — DDL migration (idempotent)
3. `domain/enums.py` — add value to MetricType
4. `schemas.py` — config fields in Create/Update/Out (keep `bool` before `int` in unions)
5. `repositories/entry_repository.py` — get/insert/update value for new type
6. `repositories/metric_repository.py` — LEFT JOIN for config table (if any)
7. `services/metrics_service.py` — create/update metric logic
8. `services/daily_service.py` + `services/daily_helpers.py` — daily form display
9. `services/export_service.py` + `services/import_service.py` — export/import
10. `analytics/value_converter.py` — numeric conversion for correlations
11. `frontend/js/app.js` — render, input handlers, history, settings

### Integration: Todoist

- OAuth: `GET .../todoist/auth-url` → redirect → `GET .../todoist/callback` → saves encrypted token
- User creates integration metrics via modal (type=integration, provider=todoist, metric_key from registry)
- Registry: `integrations/todoist/registry.py` — TODOIST_METRICS dict
- Keys: `completed_tasks_count`, `filter_tasks_count` (needs filter_name), `query_tasks_count` (needs filter_query)
- Fetch: `POST .../integrations/{provider}/fetch` → service dispatches by key
- Architecture: `todoist/client.py` (API) → `todoist/service.py` (orchestration) → `services/integration_service.py` → `routers/integrations.py`
- Token encryption: Fernet via `encryption.py`, key from LA_SECRET_KEY

### Integration: ActivityWatch

- No OAuth — AW runs locally (localhost:5600)
- Frontend fetches raw events from AW, sends to backend
- Architecture: `aw-client.js` → `routers/integrations.py` → `integrations/activitywatch/service.py` (processes events) → DB tables
- Dedicated tables: activitywatch_settings, activitywatch_daily_summary, activitywatch_app_usage, activitywatch_categories, activitywatch_app_category_map
- Registry: `integrations/activitywatch/registry.py` — 11 metric_keys
- Endpoints: sync, summary, trends, status, enable, disable

### Correlation Reports

- Launch: `services/correlation_service.py` → `asyncio.create_task` → `analytics/correlation_engine.py`
- Data: `repositories/analytics_repository.py` + `repositories/correlation_repository.py`
- Computation: analytics/ pure modules (correlation_math, quality, value_converter, time_series)
- Results: saved via correlation_repository
- Auto-sources: nonzero, note_count, checkpoint_max, checkpoint_min, rolling_avg, streak, day_of_week, month, is_workday, aw_active, delta, trend, range (delta/trend/range — only for checkpoint metrics with is_checkpoint=true)
- Source key format: `metric:{id}:checkpoint:{cpid}` for checkpoint-bound values, `metric:{id}:interval:{ivid}` for interval-bound values
- Lag: computes lag=0 + lag=1 (both directions) for each pair
- Blacklist: `correlation_blacklist.py` — filters trivial pairs
- Quality issues: see `docs/correlation-quality.md`
- Frontend: polling every 3s until done

### Frontend (Vanilla JS SPA)

- `index.html` — single entry point with nav, Lucide icons, emoji-picker, Chart.js (vendored)
- `js/api.js` — API client, token in localStorage, auto-redirect on 401
- `js/app.js` — all page logic: routing, rendering, event handling
- `css/style.css` — dark/light theme via CSS custom properties

**Navigation:** Сегодня, Статистика, Анализ, Выводы, История, Настройки.

**Routing:** `navigateTo(page, params = {})` — supports parameters.

**Event delegation:** `#metrics-form` persists across re-renders. Listeners attached once via `data-handlersAttached` guard.

**Backend-first logic:** All business logic on backend. Frontend = display and input only. No logic duplication.

### Frontend Visual Consistency

All new pages MUST reuse existing CSS classes:
- **Cards/rows:** `setting-row` (flex, surface bg, border, 8px radius, 12px 14px padding)
- **Headers:** `stats-header` + `stats-title`
- **Buttons:** `btn-primary`, `btn-small`, `btn-icon` (36x36), `btn-icon-tiny` (13x13), `btn-icon-danger`
- **Modals:** `modal-overlay` → `modal` → `h3` → `modal-form` → `form-section` + `label-text` → `modal-actions`
- **Inputs:** styled by `.modal input, .modal select`. Textareas: `note-textarea`
- **Empty state:** `empty-state` → `empty-state-icon` → `empty-state-text` → `btn-primary`
- **Tags/badges:** 4px radius, 12px font, 2px 8px padding, surface2 bg
- Always verify nav fits in `max-width: 600px`

## Deployment

Docker Compose on VDSina VPS. Three services: db (postgres:16-alpine), backend (Python 3.12-slim + uvicorn), frontend (nginx proxies /api/ to backend). Optional: backup service (profile `backup`).

Auto-deploy via GitHub Actions on push to master (SSH → git pull → docker compose up --build). Memory limits: 512M db, 512M backend, 64M frontend. PostgreSQL tuned for 2 GB RAM.

## Environment Variables

```
DATABASE_URL=postgresql://la_user:la_password@db:5432/life_analytics
LA_SECRET_KEY=change-me-in-production
POSTGRES_USER=la_user
POSTGRES_PASSWORD=la_password
POSTGRES_DB=life_analytics

# Backup (only with --profile backup)
YADISK_TOKEN=your-yandex-disk-oauth-token
YADISK_BACKUP_PATH=/life-analytics-backups/
BACKUP_INTERVAL_MINUTES=360
BACKUP_RETAIN_DAYS=30

# Todoist (optional)
TODOIST_CLIENT_ID=
TODOIST_CLIENT_SECRET=
```

See `.env.example`. Defaults work for local Docker Compose dev.

## Performance Instrumentation

Lightweight timing across all layers. No extra deps.

- `backend/app/timing.py` — `timed_fetch()` + `QueryTimer` (multi-checkpoint)
- `backend/app/main.py` — `TimingMiddleware` (SLOW threshold 500ms, env `SLOW_REQUEST_MS`)
- `frontend/js/api.js` — `performance.now()` around fetch
- `frontend/js/app.js` — render timing
- `frontend/nginx.conf` — `$request_time` + `$upstream_response_time`

**Bottleneck tree:**
```
1. frontend [api] vs nginx req=         → network
2. nginx req= vs upstr=                 → nginx overhead
3. backend [timing] vs [app.db] total=  → Python CPU
4. [app.db] breakdown                   → slow SQL
5. frontend [render] vs [api]           → JS rendering
```

## Common Workflows

**Add new router:**
1. Create `routers/new_router.py` with `router = APIRouter(prefix="/api/path")`
2. Create `repositories/new_repository.py` and `services/new_service.py`
3. Router uses service, service uses repository
4. Include in `main.py`: `app.include_router(new_router.router)`
5. Write tests

**Export/Import format:** ZIP with `metrics.csv` + `entries.csv`. Import creates/updates by slug, skips duplicates. Logic in `services/export_service.py` and `services/import_service.py`.

**Backup setup:** Get Yandex Disk OAuth token → add `YADISK_TOKEN` to `.env` → `make backup-up`. Uses Docker Compose profile `backup`, does NOT start with regular `make up`.

**Makefile:** When adding/removing targets, update the `help` target. `make help` is the default goal.
