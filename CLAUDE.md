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
- Two entry modes: **daily** (one entry per metric per day) and **multiple** (several timestamped entries per day, e.g. mood).
- Aggregations for multi-entry metrics: average, min/max, intra-day dynamics.

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

## Commands

```bash
# Run everything (backend + frontend)
./run.sh

# Backend only
cd backend && source venv/bin/activate && python -m uvicorn app.main:app --reload --port 8000

# Frontend only (static file server)
cd frontend && python -m http.server 3000
```

- Backend: http://localhost:8000 (API docs at /docs)
- Frontend: http://localhost:3000
- DB file: `backend/life_analytics.db` (created on first run)

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
