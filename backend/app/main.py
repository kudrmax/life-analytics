import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.database import create_pool, close_pool, init_db, pool as app_pool
from app.migrations import run_migrations
from app.routers import metrics, entries, daily, analytics, auth, export_import, integrations, categories, notes, insights

SLOW_REQUEST_MS = int(os.environ.get("SLOW_REQUEST_MS", "500"))
_timing_logger = logging.getLogger("timing")


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/api/health":
            return await call_next(request)
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        msg = "%s %s -> %s  %.0fms"
        args = (request.method, request.url.path, response.status_code, ms)
        if ms > SLOW_REQUEST_MS:
            _timing_logger.warning("SLOW " + msg, *args)
        else:
            _timing_logger.info(msg, *args)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    await create_pool()
    await init_db()
    from app.database import pool as db_pool
    await run_migrations(db_pool)
    async with db_pool.acquire() as conn:
        await conn.execute("ANALYZE")
    yield
    await close_pool()


app = FastAPI(title="Life Analytics API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TimingMiddleware)

app.include_router(auth.router)
app.include_router(metrics.router)
app.include_router(entries.router)
app.include_router(daily.router)
app.include_router(analytics.router)
app.include_router(export_import.router)
app.include_router(integrations.router)
app.include_router(categories.router)
app.include_router(notes.router)
app.include_router(insights.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "env": os.environ.get("LA_ENV", "local")}
