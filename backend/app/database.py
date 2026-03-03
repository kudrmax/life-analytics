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
        await conn.execute("""
            ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'scale'
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

        # Scale config (current settings for scale metrics)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scale_config (
                metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
                scale_min INTEGER NOT NULL DEFAULT 1,
                scale_max INTEGER NOT NULL DEFAULT 5,
                scale_step INTEGER NOT NULL DEFAULT 1
            )
        """)

        # Value table for scale metrics
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS values_scale (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                value INTEGER NOT NULL,
                scale_min INTEGER NOT NULL,
                scale_max INTEGER NOT NULL,
                scale_step INTEGER NOT NULL
            )
        """)

        # Measurement slots (multi-slot per metric per day)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS measurement_slots (
                id SERIAL PRIMARY KEY,
                metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                label VARCHAR(100) NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)

        # Add slot_id column to entries (nullable)
        await conn.execute("""
            ALTER TABLE entries ADD COLUMN IF NOT EXISTS
                slot_id INTEGER REFERENCES measurement_slots(id)
        """)

        # Migrate from old UNIQUE constraint to partial indexes
        await conn.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'entries_metric_id_user_id_date_key'
                    AND conrelid = 'entries'::regclass
                ) THEN
                    ALTER TABLE entries DROP CONSTRAINT entries_metric_id_user_id_date_key;
                END IF;
            END $$
        """)

        # Partial index for metrics without slots (max 1 entry per metric/user/date)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS entries_no_slot_key
            ON entries(metric_id, user_id, date) WHERE slot_id IS NULL
        """)

        # Partial index for metrics with slots (max 1 entry per metric/user/date/slot)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS entries_with_slot_key
            ON entries(metric_id, user_id, date, slot_id) WHERE slot_id IS NOT NULL
        """)

        # Add icon column to metric_definitions
        await conn.execute("""
            ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS icon VARCHAR(10) NOT NULL DEFAULT ''
        """)

        # Correlation reports
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS correlation_reports (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(20) NOT NULL DEFAULT 'running',
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS correlation_pairs (
                id SERIAL PRIMARY KEY,
                report_id INTEGER NOT NULL REFERENCES correlation_reports(id) ON DELETE CASCADE,
                metric_a_id INTEGER NOT NULL,
                metric_b_id INTEGER NOT NULL,
                slot_a_id INTEGER,
                slot_b_id INTEGER,
                label_a VARCHAR(200) NOT NULL,
                label_b VARCHAR(200) NOT NULL,
                type_a VARCHAR(20) NOT NULL DEFAULT '',
                type_b VARCHAR(20) NOT NULL DEFAULT '',
                correlation FLOAT,
                data_points INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Add type columns for existing DBs
        await conn.execute("""
            ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS type_a VARCHAR(20) NOT NULL DEFAULT ''
        """)
        await conn.execute("""
            ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS type_b VARCHAR(20) NOT NULL DEFAULT ''
        """)

        # Indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_correlation_reports_user
            ON correlation_reports(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_correlation_pairs_report
            ON correlation_pairs(report_id)
        """)
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
