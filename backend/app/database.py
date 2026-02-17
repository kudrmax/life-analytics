import aiosqlite
import json
import os

DB_PATH = os.environ.get("LA_DB_PATH", "life_analytics.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS metric_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL,
                frequency TEXT NOT NULL DEFAULT 'daily',
                source TEXT NOT NULL DEFAULT 'manual',
                config_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_id TEXT NOT NULL,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                value_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (metric_id) REFERENCES metric_configs(id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(date)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_metric_date ON entries(metric_id, date)
        """)

        await db.commit()
