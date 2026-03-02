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
                CREATE TYPE metric_type AS ENUM ('bool', 'number', 'scale', 'time');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)

        await conn.execute("""
            DO $$ BEGIN
                CREATE TYPE number_display_mode AS ENUM ('number_only', 'bool_number');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
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
                measurements_per_day SMALLINT NOT NULL DEFAULT 1
                    CHECK (measurements_per_day >= 1 AND measurements_per_day <= 10),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(user_id, slug)
            )
        """)

        # Measurement labels
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS measurement_labels (
                id SERIAL PRIMARY KEY,
                metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
                measurement_number SMALLINT NOT NULL,
                label VARCHAR(100) NOT NULL,
                UNIQUE(metric_id, measurement_number)
            )
        """)

        # Config tables (one per metric type)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config_bool (
                metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
                true_label VARCHAR(50) NOT NULL DEFAULT 'Да',
                false_label VARCHAR(50) NOT NULL DEFAULT 'Нет'
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config_number (
                metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
                min_value NUMERIC,
                max_value NUMERIC,
                step NUMERIC NOT NULL DEFAULT 1,
                unit_label VARCHAR(50) NOT NULL DEFAULT '',
                display_mode number_display_mode NOT NULL DEFAULT 'number_only',
                bool_label VARCHAR(200) NOT NULL DEFAULT '',
                number_label VARCHAR(200) NOT NULL DEFAULT ''
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config_scale (
                metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
                min_value INTEGER NOT NULL DEFAULT 1,
                max_value INTEGER NOT NULL DEFAULT 5,
                step INTEGER NOT NULL DEFAULT 1
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config_time (
                metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
                placeholder VARCHAR(50) NOT NULL DEFAULT ''
            )
        """)

        # Entries (spine table)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id SERIAL PRIMARY KEY,
                metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                date DATE NOT NULL,
                measurement_number SMALLINT NOT NULL DEFAULT 1,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(metric_id, user_id, date, measurement_number)
            )
        """)

        # Value tables (one per metric type)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_bool (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value BOOLEAN NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_number (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                bool_value BOOLEAN,
                number_value NUMERIC
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_scale (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value INTEGER NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_time (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value TIME NOT NULL
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
