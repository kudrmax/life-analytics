import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://la_user:la_password@localhost:5432/life_analytics",
)

pool: asyncpg.Pool | None = None


async def create_pool():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None


async def get_db():
    async with pool.acquire() as conn:
        yield conn


async def init_db():
    async with pool.acquire() as conn:
        # Create ENUM types
        await conn.execute("""
            DO $$ BEGIN
                CREATE TYPE metric_type AS ENUM ('bool', 'time');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
        # Add 'time' to existing enum if missing (safe for existing DBs)
        await conn.execute("""
            ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'time'
        """)
        await conn.execute("""
            ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'number'
        """)

        # Users
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(30) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)

        # Metric definitions
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_definitions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                slug VARCHAR(100) NOT NULL,
                name VARCHAR(200) NOT NULL,
                category VARCHAR(100) NOT NULL DEFAULT '',
                type metric_type NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(user_id, slug)
            )
        """)

        # Entries (spine table — one row per metric per user per date)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date DATE NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(metric_id, user_id, date)
            )
        """)

        # Value table for bool metrics
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_bool (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value BOOLEAN NOT NULL
            )
        """)

        # Value table for time metrics
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_time (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value TIMESTAMPTZ NOT NULL
            )
        """)

        # Value table for number metrics
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_number (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value INTEGER NOT NULL
            )
        """)

        # Indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_metric_definitions_user
            ON metric_definitions(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_user
            ON entries(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_date
            ON entries(date)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_metric_date
            ON entries(metric_id, date)
        """)
