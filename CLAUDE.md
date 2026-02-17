# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Life Analytics — a multi-user daily metrics tracker with JWT authentication, flexible metric configuration, multi-entry support, and ZIP export/import.

## Architecture

**Backend** (Python + FastAPI + SQLite) — standalone REST API with JWT authentication, fully decoupled from frontend.

**Frontend** (Web SPA) — vanilla JS application with login/register pages, communicates with backend exclusively via REST API.

### Authentication & Multi-User

- **JWT tokens** with 7-day expiration (HS256 algorithm)
- **Password hashing** using bcrypt (12 rounds)
- **User isolation**: Each user has their own metrics and entries
- **Default metrics**: 23 metrics automatically created on registration from `seed.py`
- **Session management**: Token stored in localStorage, auto-redirect on 401

Environment variables:
- `LA_SECRET_KEY` — JWT signing key (default: "dev-secret-key-change-in-production")
- `LA_DB_PATH` — database file path (default: "life_analytics.db")

### Database Schema

**Multi-tenant architecture** with complete data isolation:

```
users (1) ──→ (N) metric_configs  [ON DELETE CASCADE]
users (1) ──→ (N) entries          [ON DELETE CASCADE]
```

**Key tables:**
- `users` — id, username (unique), password_hash, created_at
- `metric_configs` — id, user_id, name, type, frequency, source, config_json, enabled, sort_order
  - PRIMARY KEY: (id, user_id) — allows same metric ID across different users
- `entries` — id, metric_id, user_id, date, timestamp, value_json

**JSON fields for flexibility:**
- `config_json` — metric settings (min/max, options, compound fields with conditions)
- `value_json` — entry values (varies by type: {"value": 5}, {"period": "morning", "value": 4}, etc.)

**Indexes:** user_id on all tables, (metric_id, date) on entries, date on entries

### Metric System

**Types:** scale (1-5), boolean, number, time, enum, compound

**Frequencies:**
- **daily** — one entry per day
- **multiple** — three entries per day (morning/day/evening) with automatic aggregation

**Sources:** manual (default), todoist, google_calendar (integrations not yet implemented)

**Compound metrics:** Support conditional fields using "condition" property (e.g., "planned == true" to show field only when another is true)

**Default metrics location:** `backend/app/seed.py` — edit `DEFAULT_METRICS` list to customize metrics for new users

### API Structure

**Authentication:**
- `POST /api/auth/register` — create user, seed default metrics, return JWT
- `POST /api/auth/login` — authenticate + return JWT
- `GET /api/auth/me` — get current user info

**Core:**
- `/api/metrics` — CRUD for metric definitions (protected)
- `/api/entries` — CRUD for metric values (protected)
- `/api/daily/{date}` — daily summary with aggregations (protected)

**Analytics:**
- `/api/analytics/trends` — time series for a metric
- `/api/analytics/correlations` — Pearson correlation between two metrics
- `/api/analytics/streaks` — consecutive days for boolean metrics

**Export/Import:**
- `GET /api/export/csv` — export ZIP archive with metrics.csv + entries.csv
- `POST /api/export/import` — import ZIP archive (creates/updates metrics, imports entries)

All endpoints except `/api/auth/*` require `Authorization: Bearer <token>` header.

### Frontend Architecture

**Single Page App** (vanilla JS) with:
- Client-side routing (login/register/today/history/dashboard/settings)
- Token-based authentication with auto-redirect
- Event delegation pattern for dynamic content

**Key files:**
- `js/api.js` — API client with token management and 401 handling
- `js/app.js` — routing, rendering, auth state, all page logic (1200+ lines)

**Auth flow:**
1. App loads → check token in localStorage
2. If valid token → fetch user info → navigate to 'today'
3. If no/invalid token → navigate to 'login'
4. On 401 from any API call → clear token → redirect to login

**UX patterns:**
- Visual feedback: filled daily metrics dimmed (50% opacity)
- Quick actions: +/- buttons for numbers, × clear button per metric
- Period-based tracking: morning/day/evening sections for multiple-frequency metrics
- Export: downloads ZIP file with metrics.csv + entries.csv
- Import: file picker (accepts .zip) → upload → shows detailed summary (metrics: imported/updated, entries: imported/skipped/errors)

## Commands

```bash
# Initial setup (one-time)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Run backend + frontend
./run.sh

# Backend only (with auto-reload)
cd backend
source venv/bin/activate
python -m uvicorn app.main:app --reload --port 8000

# Frontend only (static file server)
cd frontend
python -m http.server 3000

# View database schema
sqlite3 backend/life_analytics.db ".schema"

# Query database
sqlite3 backend/life_analytics.db "SELECT * FROM users"

# Count metrics per user
sqlite3 backend/life_analytics.db "SELECT username, COUNT(m.id) FROM users u LEFT JOIN metric_configs m ON u.id = m.user_id GROUP BY username"
```

**URLs:**
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs

**Database:**
- Location: `backend/life_analytics.db` (configurable via `LA_DB_PATH` env var)
- WAL mode enabled for concurrent reads
- Foreign keys enforced
- Auto-created on first run

**Important:** On schema changes, remove `life_analytics.db` to recreate with new schema (or write migration).

**Note:** No tests exist yet in this project.

## Project Structure

```
backend/
  app/
    main.py            — FastAPI app, CORS, startup (init_db)
    database.py        — SQLite connection, schema init with users table
    schemas.py         — Pydantic models (auth + metrics + entries)
    auth.py            — JWT utils (create_token, verify_token, hash_password with bcrypt)
    seed.py            — DEFAULT_METRICS definitions (23 metrics)
    routers/
      auth.py          — /api/auth/* (register with metric seeding, login, me)
      metrics.py       — /api/metrics CRUD (protected)
      entries.py       — /api/entries CRUD (protected)
      daily.py         — /api/daily/{date} summary (protected)
      analytics.py     — trends, correlations, streaks (protected)
      export_import.py — ZIP export/import (protected)
  requirements.txt     — dependencies (bcrypt, python-jose, etc.)

frontend/
  index.html           — main HTML with nav
  js/
    api.js             — API client + token management
    app.js             — SPA: routing, auth, all pages
  css/style.css        — dark theme styles + auth pages

life_analytics.db      — SQLite database (gitignored)
run.sh                 — convenience script to run backend + frontend
```

## Key Implementation Details

**Password security:**
- Bcrypt with 12 rounds
- Never store plain passwords
- Validate minimum 8 characters on registration

**Data isolation:**
- All queries filter by `current_user["id"]`
- Metrics with same ID allowed across users (composite PK: id + user_id)
- Return 404 (not 403) on unauthorized access to prevent info disclosure

**ZIP export format:**
```
archive.zip
├── metrics.csv     — id, name, category, type, frequency, source, config_json, enabled, sort_order
└── entries.csv     — date, metric_id, timestamp, value_json
```

**Import behavior:**
- Imports metrics first (creates new or updates existing by id+user_id)
- Then imports entries (skips duplicates: same metric_id, date, value_json, user_id)
- Returns detailed summary: {metrics: {imported, updated, errors}, entries: {imported, skipped, errors}}

**Metric config examples:**
```json
// Scale
{"min": 1, "max": 5}

// Number
{"min": 0, "max": 20, "label": "чашек"}

// Compound with conditional fields
{
  "fields": [
    {"name": "done", "type": "boolean", "label": "Была тренировка"},
    {"name": "type", "type": "enum", "label": "Тип",
     "options": ["кардио", "силовая"], "condition": "done == true"}
  ]
}
```

**Value JSON examples:**
```json
// Daily scale
{"value": 4}

// Multiple-frequency scale
{"period": "morning", "value": 5}

// Boolean
{"value": true}

// Compound
{"done": true, "type": "кардио"}
```

## Customizing Default Metrics

**File:** `backend/app/seed.py`

Edit `DEFAULT_METRICS` list to customize metrics created for new users on registration.

**Structure:**
```python
{
    "id": "unique_id",           # Unique identifier
    "name": "Display Name",      # User-facing name
    "category": "Category",      # For grouping in UI
    "type": "scale",             # scale/boolean/number/time/enum/compound
    "frequency": "daily",        # daily/multiple
    "source": "manual",          # manual/todoist/google_calendar (optional)
    "config": {                  # Type-specific config
        "min": 1,
        "max": 5
    },
    "enabled": True,             # Default True (optional)
    "sort_order": 0              # Display order (optional)
}
```

**Important:** Changes only affect NEW users. Existing users must add metrics via UI or import.

## Common Workflows

**Add new router:**
1. Create `backend/app/routers/new_router.py`
2. Define router with `router = APIRouter(prefix="/api/path", tags=["tag"])`
3. Add `current_user = Depends(get_current_user)` to protected endpoints
4. Import and include in `main.py`: `app.include_router(new_router.router)`

**Add new metric type:**
1. Update frontend rendering in `app.js` (renderMetricInput function)
2. Update config validation if needed
3. Add to DEFAULT_METRICS in `seed.py` if should be default

**Modify default metrics:**
1. Edit `backend/app/seed.py` DEFAULT_METRICS list
2. Restart backend
3. Changes apply only to new registrations
4. Existing users unaffected

**Database changes:**
1. Update schema in `database.py` init_db()
2. Delete `backend/life_analytics.db` file
3. Restart backend (will recreate DB)
4. Note: This loses all data — migrations not implemented yet

**Migrate user to new metrics:**
1. Register new account (gets updated DEFAULT_METRICS)
2. Export data from old account (Settings → Export ZIP)
3. Import into new account (Settings → Import ZIP)
4. Old metrics will be created/updated during import
