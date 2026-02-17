import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db, get_db, DB_PATH
from app.seed import DEFAULT_METRICS
from app.routers import metrics, entries, daily, analytics

app = FastAPI(title="Life Analytics API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(metrics.router)
app.include_router(entries.router)
app.include_router(daily.router)
app.include_router(analytics.router)


@app.on_event("startup")
async def startup():
    await init_db()
    await seed_defaults()


async def seed_defaults():
    async for db in get_db():
        for m in DEFAULT_METRICS:
            existing = await db.execute(
                "SELECT id FROM metric_configs WHERE id = ?", (m["id"],)
            )
            if not await existing.fetchone():
                await db.execute(
                    """INSERT INTO metric_configs (id, name, category, type, frequency, source, config_json, enabled, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)""",
                    (
                        m["id"],
                        m["name"],
                        m["category"],
                        m["type"],
                        m["frequency"],
                        m.get("source", "manual"),
                        json.dumps(m.get("config", {})),
                    ),
                )
        await db.commit()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
