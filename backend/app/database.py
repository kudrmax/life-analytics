import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://la_user:la_password@localhost:5432/life_analytics",
)

pool: asyncpg.Pool | None = None


async def create_pool():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)


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
        # Advisory lock to prevent race condition when multiple workers start simultaneously
        await conn.execute("SELECT pg_advisory_lock(1)")
        try:
            await _init_db_schema(conn)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(1)")


async def _init_db_schema(conn):
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
    await conn.execute("""
        ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'computed'
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

    # Categories (two-level hierarchy for metric grouping)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_top
            ON categories(user_id, name) WHERE parent_id IS NULL
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_sub
            ON categories(user_id, name, parent_id) WHERE parent_id IS NOT NULL
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user_id)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id)
    """)

    # Metric definitions
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS metric_definitions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            slug VARCHAR(100) NOT NULL,
            name VARCHAR(200) NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
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
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS icon VARCHAR(600) NOT NULL DEFAULT ''
    """)
    await conn.execute("""
        ALTER TABLE metric_definitions ALTER COLUMN icon TYPE VARCHAR(600)
    """)

    # Add category_id column to metric_definitions (for existing DBs that had category/fill_time columns)
    await conn.execute("""
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
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
            metric_a_id INTEGER,
            metric_b_id INTEGER,
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

    # Add columns for existing DBs
    await conn.execute("""
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS type_a VARCHAR(20) NOT NULL DEFAULT ''
    """)
    await conn.execute("""
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS type_b VARCHAR(20) NOT NULL DEFAULT ''
    """)
    await conn.execute("""
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS lag_days INTEGER NOT NULL DEFAULT 0
    """)
    await conn.execute("""
        ALTER TABLE correlation_pairs ALTER COLUMN metric_a_id DROP NOT NULL
    """)
    await conn.execute("""
        ALTER TABLE correlation_pairs ALTER COLUMN metric_b_id DROP NOT NULL
    """)

    await conn.execute("""
        ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'integration'
    """)
    await conn.execute("""
        ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'enum'
    """)
    await conn.execute("""
        ALTER TYPE metric_type ADD VALUE IF NOT EXISTS 'duration'
    """)

    # User integrations (OAuth tokens for external services)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_integrations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(50) NOT NULL,
            encrypted_token TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, provider)
        )
    """)

    # Integration config (links metric to external provider)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            provider VARCHAR(50) NOT NULL,
            metric_key VARCHAR(100) NOT NULL DEFAULT 'completed_tasks_count'
        )
    """)

    await conn.execute("""
        ALTER TABLE integration_config ADD COLUMN IF NOT EXISTS value_type VARCHAR(20) NOT NULL DEFAULT 'number'
    """)

    # Integration filter config (filter_tasks_count — filter by name)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_filter_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            filter_name VARCHAR(200) NOT NULL
        )
    """)

    # Integration query config (query_tasks_count — arbitrary filter query)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_query_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            filter_query VARCHAR(1024) NOT NULL
        )
    """)

    # Computed metric config (formula stored as JSONB token list)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS computed_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            formula JSONB NOT NULL DEFAULT '[]',
            result_type VARCHAR(10) NOT NULL DEFAULT 'float'
        )
    """)

    # ActivityWatch settings
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS activitywatch_settings (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            aw_url VARCHAR(500) NOT NULL DEFAULT 'http://localhost:5600',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ActivityWatch daily summary
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS activitywatch_daily_summary (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            total_seconds INTEGER NOT NULL DEFAULT 0,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, date)
        )
    """)

    # ActivityWatch per-app/domain usage (aggregated per day)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS activitywatch_app_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            app_name VARCHAR(500) NOT NULL,
            source VARCHAR(20) NOT NULL DEFAULT 'window',
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, date, app_name, source)
        )
    """)

    # Extend daily summary with computed fields
    for col, typedef in [
        ("first_activity_time", "TIMESTAMPTZ"),
        ("last_activity_time", "TIMESTAMPTZ"),
        ("afk_seconds", "INTEGER DEFAULT 0"),
        ("longest_session_seconds", "INTEGER DEFAULT 0"),
        ("context_switches", "INTEGER DEFAULT 0"),
        ("break_count", "INTEGER DEFAULT 0"),
    ]:
        await conn.execute(f"""
            ALTER TABLE activitywatch_daily_summary
            ADD COLUMN IF NOT EXISTS {col} {typedef}
        """)

    # ActivityWatch app categories
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS activitywatch_categories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            color VARCHAR(7) DEFAULT '#6c5ce7',
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, name)
        )
    """)

    # App-to-category mapping
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS activitywatch_app_category_map (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            app_name VARCHAR(500) NOT NULL,
            activitywatch_category_id INTEGER NOT NULL REFERENCES activitywatch_categories(id) ON DELETE CASCADE,
            UNIQUE(user_id, app_name)
        )
    """)

    # Integration config: category_time metric -> category
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_category_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            activitywatch_category_id INTEGER NOT NULL REFERENCES activitywatch_categories(id) ON DELETE CASCADE
        )
    """)

    # Integration config: app_time metric -> app_name
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_app_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            app_name VARCHAR(500) NOT NULL
        )
    """)

    # Enum config (multi_select flag for enum metrics)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS enum_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            multi_select BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # Enum options (choices for enum metrics, soft-delete via enabled)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS enum_options (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            label VARCHAR(200) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE
        )
    """)

    # Value table for duration metrics (minutes as INTEGER)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS values_duration (
            entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
            value INTEGER NOT NULL
        )
    """)

    # Value table for enum metrics (selected option IDs as integer array)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS values_enum (
            entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
            selected_option_ids INTEGER[] NOT NULL
        )
    """)

    # Indexes
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_enum_options_metric
        ON enum_options(metric_id)
    """)
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
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activitywatch_daily_summary_user_date
        ON activitywatch_daily_summary(user_id, date)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activitywatch_app_usage_user_date
        ON activitywatch_app_usage(user_id, date)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activitywatch_categories_user
        ON activitywatch_categories(user_id)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_activitywatch_app_category_map_user
        ON activitywatch_app_category_map(user_id)
    """)


