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
                        "INSERT INTO schema_migrations (version, description) VALUES ($1, $2)",
                        version,
                        description,
                    )
                print(f"Migration {version} applied: {description}")
