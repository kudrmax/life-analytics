# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Life Analytics — a multi-user daily metrics tracker with JWT authentication, flexible metric configuration, multi-entry support, and CSV export/import.

## Architecture

**Backend** (Python + FastAPI + SQLite) — standalone REST API with JWT authentication, fully decoupled from frontend.

**Frontend** (Web SPA) — vanilla JS application with login/register pages, communicates with backend exclusively via REST API.

### Authentication & Multi-User

- **JWT tokens** with 7-day expiration (HS256 algorithm)
- **Password hashing** using bcrypt (12 rounds)
- **User isolation**: Each user has their own metrics and entries
- **Default metrics**: 22 metrics automatically created on registration
- **Session management**: Token stored in localStorage, auto-redirect on 401

Environment variables:
- `LA_SECRET_KEY` — JWT signing key (default: "dev-secret-key-change-in-production")

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
- `config_json` — metric settings (min/max, options, compound fields)
- `value_json` — entry values (varies by type: {"value": 5}, {"period": "morning", "value": 4}, etc.)

**Indexes:** user_id on all tables, (metric_id, date) on entries, date on entries

### Metric System

**Types:** scale (1-5), boolean, number, time, enum, compound

**Frequencies:**
- **daily** — one entry per day
- **multiple** — three entries per day (morning/day/evening) with automatic aggregation

**Sources:** manual (default), todoist, google_calendar

**Compound metrics:** Support conditional fields (e.g., "workout done?" → if yes, show "type" dropdown)

### API Structure

**Authentication:**
- `POST /api/auth/register` — create user + return JWT
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
- `GET /api/export/csv` — export all user entries to CSV
- `POST /api/export/import` — import entries from CSV (with duplicate detection)

All endpoints except `/api/auth/*` require `Authorization: Bearer <token>` header.

### Frontend Architecture

**Single Page App** (vanilla JS) with:
- Client-side routing (login/register/today/history/dashboard/settings)
- Token-based authentication with auto-redirect
- Event delegation pattern for dynamic content

**Key files:**
- `js/api.js` — API client with token management and 401 handling
- `js/app.js` — routing, rendering, auth state, all page logic

**Auth flow:**
1. App loads → check token in localStorage
2. If valid token → fetch user info → navigate to 'today'
3. If no/invalid token → navigate to 'login'
4. On 401 from any API call → clear token → redirect to login

**UX patterns:**
- Visual feedback: filled daily metrics dimmed (50% opacity)
- Quick actions: +/- buttons for numbers, × clear button per metric
- Period-based tracking: morning/day/evening sections for multiple-frequency metrics
- Export: downloads CSV file with auto-generated filename
- Import: file picker → upload → shows import summary (imported/skipped/errors)

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
    auth.py            — JWT utils (create_token, verify_token, hash_password)
    seed.py            — DEFAULT_METRICS definitions
    routers/
      auth.py          — /api/auth/* (register, login, me)
      metrics.py       — /api/metrics CRUD (protected)
      entries.py       — /api/entries CRUD (protected)
      daily.py         — /api/daily/{date} summary (protected)
      analytics.py     — trends, correlations, streaks (protected)
      export_import.py — CSV export/import (protected)
  requirements.txt     — dependencies (includes bcrypt, python-jose)

frontend/
  index.html           — main HTML with nav
  js/
    api.js             — API client + token management
    app.js             — SPA: routing, auth, all pages (login/register/today/history/dashboard/settings)
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

**CSV format:**
```csv
date,metric_id,metric_name,timestamp,value_json
2026-02-17,mood,Настроение,2026-02-17T12:00:00,"{""period"": ""morning"", ""value"": 5}"
```

**Import behavior:**
- Skips duplicate entries (same metric_id, date, value_json, user_id)
- Only imports metrics that exist for the user
- Returns summary: {imported: N, skipped: N, errors: [...]}

**Metric config examples:**
```json
// Scale
{"min": 1, "max": 5}

// Number
{"min": 0, "max": 20, "label": "чашек"}

// Compound
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

## Common Workflows

**Add new router:**
1. Create `backend/app/routers/new_router.py`
2. Define router with `router = APIRouter(prefix="/api/path", tags=["tag"])`
3. Add `current_user = Depends(get_current_user)` to protected endpoints
4. Import and include in `main.py`: `app.include_router(new_router.router)`

**Add new metric type:**
1. Update frontend rendering in `app.js` (renderMetricInput function)
2. Update config validation if needed
3. Default metrics use `seed.py` DEFAULT_METRICS list

**Database changes:**
1. Update schema in `database.py` init_db()
2. Delete `life_analytics.db` file
3. Restart backend (will recreate DB)
4. Note: This loses all data — migrations not implemented yet
