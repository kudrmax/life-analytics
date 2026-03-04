from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_pool, close_pool, init_db
from app.routers import metrics, entries, daily, analytics, auth, export_import, integrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_pool()
    await init_db()
    yield
    await close_pool()


app = FastAPI(title="Life Analytics API", version="2.0.0", lifespan=lifespan)

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
app.include_router(export_import.router)
app.include_router(integrations.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
