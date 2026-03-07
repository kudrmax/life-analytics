"""
Миграции базы данных.

Каждая миграция — SQL + номер версии.
Выполненные миграции хранятся в таблице schema_migrations.

Использование:
    Добавь новую миграцию в MIGRATIONS:
        (1, "add_timezone_to_users", "ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC'"),
    Также обнови DDL в init_db() для чистых установок.
"""

MIGRATIONS = [
    # (version, description, sql)
    # NOTE: ALTER TYPE ... ADD VALUE is in init_db() (cannot run inside transaction)
    (1, "add_enum_tables", """
        CREATE TABLE IF NOT EXISTS enum_config (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            multi_select BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS enum_options (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            label VARCHAR(200) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS values_enum (
            entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
            selected_option_ids INTEGER[] NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_enum_options_metric ON enum_options(metric_id);
    """),
    (2, "add_fill_time_column", """
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS fill_time VARCHAR(100) NOT NULL DEFAULT '';
    """),
]


async def run_migrations(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        applied = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        for version, description, sql in MIGRATIONS:
            if version not in applied:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, description) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        version,
                        description,
                    )
                print(f"Migration {version} applied: {description}")
