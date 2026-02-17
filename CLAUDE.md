# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Life Analytics — a personal daily metrics tracker with flexible metric configuration, multi-entry support, and integrations with Todoist and Google Calendar.

## Architecture

**Backend** (Python + FastAPI + SQLite) — standalone REST API, fully decoupled from frontend.

**Frontend** (Web SPA) — communicates with backend exclusively via REST API. Designed to be replaceable.

### Backend Structure
- Metrics are configured dynamically (not hardcoded). Each metric has: id, name, type (scale/boolean/number/time/enum/compound), category, frequency (daily/multiple), source (manual/todoist/google_calendar).
- Values stored as JSON blobs in SQLite (`value_json` column) for flexibility.
- Two entry modes:
  - **daily**: one entry per metric per day (e.g., coffee cups, sleep quality)
  - **multiple**: three period-based entries per day (morning/day/evening) for scale 1-5 metrics (e.g., mood, energy, stress)
- Multiple-frequency entries store period in value JSON: `{"period": "morning", "value": 4}`
- Aggregations for multi-entry metrics: average, min/max across all periods
- Uses `aiosqlite` (async SQLite) with WAL mode and foreign keys enabled.

### Key API Groups
- `/api/metrics` — CRUD for metric definitions
- `/api/entries` — CRUD for metric values
- `/api/daily/{date}` — daily summary with aggregations
- `/api/analytics/*` — trends, correlations, streaks
- `/api/integrations/sync` — pull data from Todoist/Google Calendar

### Data Model (SQLite)
- `metric_configs` — metric definitions and config
- `entries` — recorded values (metric_id, date, timestamp, value_json)
- `integrations` — API tokens and settings

### Frontend Architecture

**Single Page App** (vanilla JS) with client-side routing and modular rendering functions.

**Key UX Patterns:**
- **Visual feedback**: Filled daily metrics are dimmed (50% opacity) to show completion status
- **Quick actions**: Number inputs have +/- buttons; each metric has a clear (×) button
- **Period-based tracking**: Multiple-frequency metrics show three sections (Утро/День/Вечер) instead of arbitrary timestamps
- **Interactive preview**: Metric creation modal has live preview that updates as you configure
- **Compound metrics**: Support conditional fields (e.g., "consumed alcohol?" → if yes, show "how many drinks?")

**Metric Creation Modal:**
- Two-column layout: form (left, scrollable) + preview (right, sticky)
- User-friendly labels: "Да/Нет" instead of "boolean", "Раз в день" instead of "daily"
- Type restrictions: "3 times a day" only available for scale 1-5 metrics
- Compound configuration: Can set question text, condition (show on Yes/No), and custom enum options

**Event Handling:**
- Uses event delegation from parent containers (metrics-form)
- All save operations call `saveDaily()` → API → `renderTodayForm()` to refresh UI
- Period buttons (morning/day/evening) create/update entries with period field in value JSON

## Commands

```bash
# Initial setup (one-time)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Run everything (backend + frontend)
./run.sh

# Backend only
cd backend && source venv/bin/activate && python -m uvicorn app.main:app --reload --port 8000

# Frontend only (static file server)
cd frontend && python -m http.server 3000
```

- Backend: http://localhost:8000 (API docs at /docs)
- Frontend: http://localhost:3000
- DB file: `backend/life_analytics.db` (created on first run, configurable via `LA_DB_PATH` env var)

**Note:** No tests exist yet in this project.

## Project Structure

```
backend/
  app/
    main.py          — FastAPI app, startup, seed
    database.py      — SQLite connection, schema init
    schemas.py       — Pydantic models
    seed.py          — default metric definitions
    routers/
      metrics.py     — /api/metrics CRUD
      entries.py     — /api/entries CRUD
      daily.py       — /api/daily/{date} summary
      analytics.py   — trends, correlations, streaks
frontend/
  index.html
  js/api.js          — API client (all fetch calls)
  js/app.js          — SPA logic, routing, rendering
  css/style.css
```
