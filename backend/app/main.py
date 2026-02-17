import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db, get_db, DB_PATH
from app.seed import DEFAULT_METRICS
from app.routers import metrics, entries, daily, analytics, auth

app = FastAPI(title="Life Analytics API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(metrics.router)
app.include_router(entries.router)
app.include_router(daily.router)
app.include_router(analytics.router)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
