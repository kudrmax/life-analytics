# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Life Analytics — multi-user daily metrics tracker. FastAPI + PostgreSQL backend, vanilla JS SPA frontend, Docker Compose deployment.

## Commands

```bash
# Run everything (Docker Compose — preferred)
./run.sh                    # or: docker compose up --build
make up                     # detached mode with rebuild

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
```

**URLs:** Frontend :3000, Backend :8000, API docs :8000/docs, Health check: GET /api/health

**No tests exist in this project.**

Frontend is served by `python -m http.server` (local) or nginx (Docker). Both serve files from disk on each request — no restart needed for JS/CSS/HTML changes, just refresh the browser.

## Architecture

### Backend (FastAPI + asyncpg + PostgreSQL)

- `main.py` — FastAPI app with lifespan (creates/closes asyncpg pool, runs `init_db`)
- `database.py` — asyncpg pool management, full DDL schema in `init_db()` (tables, enums, indexes)
- `auth.py` — JWT (HS256, 7-day expiry), bcrypt hashing, `get_current_user` dependency
- `schemas.py` — Pydantic models for all request/response types
- `metric_helpers.py` — shared value read/write logic across routers; `build_metric_out` converts DB rows to response models with slots

**Routers** (all under `/api/`): `auth`, `metrics`, `entries`, `daily`, `analytics`, `export_import`

### Database Schema (PostgreSQL)

**Enum:** `metric_type` = 'bool' | 'time' | 'number' | 'scale'

**Tables:**
- `users` — id, username (unique), password_hash, created_at
- `metric_definitions` — id, user_id (FK), slug, name, category, icon, type (enum), enabled, sort_order; UNIQUE(user_id, slug)
- `measurement_slots` — id, metric_id (FK), sort_order, label, enabled (for multi-slot metrics like Утро/День/Вечер)
- `entries` — id, metric_id (FK), user_id (FK), date, recorded_at, slot_id (FK, nullable)
- `values_bool` — entry_id (PK/FK), value BOOLEAN
- `values_time` — entry_id (PK/FK), value TIMESTAMPTZ
- `values_number` — entry_id (PK/FK), value INTEGER
- `values_scale` — entry_id (PK/FK), value INTEGER, scale_min, scale_max, scale_step (stores context at time of entry)
- `scale_config` — metric_id (PK/FK), scale_min, scale_max, scale_step (current config for rendering)

**Entry uniqueness (partial indexes):** Metrics without slots: `UNIQUE(metric_id, user_id, date) WHERE slot_id IS NULL`. Metrics with slots: `UNIQUE(metric_id, user_id, date, slot_id) WHERE slot_id IS NOT NULL`.

**Value storage pattern:** Separate typed table per metric type (not JSON). Entry creation: INSERT into `entries` → INSERT into `values_{type}`, all within a transaction.

**Scale context pattern:** `scale_config` stores the current min/max/step for rendering buttons. `values_scale` stores the min/max/step that were active when each entry was created. When displaying a filled entry, use context from `values_scale` (not current config) so old entries render correctly even after config changes. Analytics normalizes scale values to percentages using the per-entry context.

**Multi-slot pattern:** A metric can have 2+ measurement slots (e.g. Утро, День, Вечер). `measurement_slots` stores slot definitions per metric. `entries.slot_id` links an entry to a specific slot. Daily endpoint aggregates multi-slot data, showing each slot's value separately.

### Frontend (Vanilla JS SPA)

- `index.html` — single entry point with nav, Lucide icons (CDN), emoji-picker-element (CDN)
- `config.js` — `window.API_BASE` (set by run.sh for local dev, empty for Docker/nginx proxy)
- `js/api.js` — API client, token in localStorage (`la_auth_token`), auto-redirect on 401
- `js/app.js` — all page logic: routing, rendering, event handling
- `css/style.css` — dark/light theme via CSS custom properties

**Event delegation pattern:** `#metrics-form` element persists across re-renders (innerHTML replaced). Event listeners (click, change) are attached once via `data-handlersAttached` guard in `attachInputHandlers()` to prevent duplicate async handlers.

**Icons:** Lucide icons via CDN (`<i data-lucide="...">` → `lucide.createIcons()`). Emoji icons on metrics via emoji-picker-element. Metric icons rendered in `<span class="metric-icon">` wrapper.

### Deployment (Docker Compose)

Three services: `db` (postgres:16-alpine), `backend` (Python 3.12-slim + uvicorn), `frontend` (nginx:alpine proxies `/api/` to backend).

## Environment Variables

```
DATABASE_URL=postgresql://la_user:la_password@db:5432/life_analytics
LA_SECRET_KEY=change-me-in-production
POSTGRES_USER=la_user
POSTGRES_PASSWORD=la_password
POSTGRES_DB=life_analytics
```

See `.env.example`. Defaults work for local Docker Compose dev.

## Key Implementation Details

**Adding a new metric type** requires changes in 8 places:
1. `database.py` — `ALTER TYPE metric_type ADD VALUE`, create `values_{type}` table (+ config table if type has settings)
2. `schemas.py` — add to `MetricType` enum, add config fields to Create/Update/Out if needed (keep `bool` before `int` in value unions — bool is subclass of int in Python)
3. `metric_helpers.py` — add branch in `get_entry_value`, `insert_value`, `update_value`; pass `metric_id` for types that need config lookup
4. `routers/metrics.py` — LEFT JOIN config table in list/get queries, handle config creation/update in create/update endpoints
5. `routers/daily.py` — LEFT JOIN config table, include config fields in response; for filled entries, override with stored context from value table
6. `routers/analytics.py` — `_extract_numeric` + value_table selection in `trends` and `values_by_date`; include extra columns (e.g. scale context) in SELECT
7. `routers/export_import.py` — type validation on import + value parsing + config export/import
8. `frontend/js/app.js` — render function, input handlers, history display, settings type label, modal (preview + radio + type hint + config fields)

**Data isolation:** All queries filter by `current_user["id"]`. Return 404 (not 403) on unauthorized access.

**Schema changes:** Update DDL in `database.py` `init_db()`. For new enum values, use `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (safe for existing DBs). For new tables, use `CREATE TABLE IF NOT EXISTS`. Destructive changes require dropping and recreating the database.

**Metric queries with config:** Routers that list/return metrics use LEFT JOIN to include type-specific config (e.g. `LEFT JOIN scale_config sc ON sc.metric_id = md.id`). The `build_metric_out` helper uses `.get()` for config fields since they may be NULL for non-matching types.

## Common Workflows

**Add new router:**
1. Create `backend/app/routers/new_router.py` with `router = APIRouter(prefix="/api/path", tags=["tag"])`
2. Add `current_user = Depends(get_current_user)` to protected endpoints
3. Include in `main.py`: `app.include_router(new_router.router)`

**Export/Import format:**
- ZIP with `metrics.csv` (id, slug, name, category, type, enabled, sort_order, scale_min, scale_max, scale_step, icon, slot_labels as JSON) + `entries.csv` (date, metric_slug, value as JSON, slot_sort_order, slot_label)
- Import: creates/updates metrics by slug, recreates slots, skips duplicate entries
