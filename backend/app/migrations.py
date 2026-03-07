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
    (3, "categories_as_entities", """
        -- 1. Create categories table + indexes
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_top
            ON categories(user_id, name) WHERE parent_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_sub
            ON categories(user_id, name, parent_id) WHERE parent_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user_id);
        CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);

        -- 2. Add category_id column to metric_definitions
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL;

        -- 3. Rename AW columns
        DO $aw$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'integration_category_config' AND column_name = 'category_id'
            ) THEN
                ALTER TABLE integration_category_config RENAME COLUMN category_id TO activitywatch_category_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'activitywatch_app_category_map' AND column_name = 'category_id'
            ) THEN
                ALTER TABLE activitywatch_app_category_map RENAME COLUMN category_id TO activitywatch_category_id;
            END IF;
        END $aw$;

        -- 4. Migrate fill_time/category data into categories table, then drop old columns
        DO $migrate$
        DECLARE
            _uid INTEGER;
            _ft TEXT;
            _cat TEXT;
            _top_id INTEGER;
            _sub_id INTEGER;
            _sort INTEGER;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'metric_definitions' AND column_name = 'fill_time'
            ) THEN
                -- Create top-level categories from unique fill_time values
                _sort := 0;
                FOR _uid, _ft IN
                    SELECT DISTINCT user_id, fill_time FROM metric_definitions
                    WHERE fill_time IS NOT NULL AND fill_time != ''
                    ORDER BY fill_time
                LOOP
                    INSERT INTO categories (user_id, name, parent_id, sort_order)
                    VALUES (_uid, _ft, NULL, _sort)
                    ON CONFLICT DO NOTHING;
                    _sort := _sort + 1;
                END LOOP;

                -- Create subcategories from category within each fill_time
                FOR _uid, _ft, _cat IN
                    SELECT DISTINCT user_id, fill_time, category FROM metric_definitions
                    WHERE fill_time IS NOT NULL AND fill_time != ''
                      AND category IS NOT NULL AND category != ''
                    ORDER BY fill_time, category
                LOOP
                    SELECT id INTO _top_id FROM categories
                    WHERE user_id = _uid AND name = _ft AND parent_id IS NULL;
                    IF _top_id IS NOT NULL THEN
                        INSERT INTO categories (user_id, name, parent_id, sort_order)
                        VALUES (_uid, _cat, _top_id, 0)
                        ON CONFLICT DO NOTHING;
                    END IF;
                END LOOP;

                -- Create top-level categories from category (where fill_time is empty)
                FOR _uid, _cat IN
                    SELECT DISTINCT user_id, category FROM metric_definitions
                    WHERE (fill_time IS NULL OR fill_time = '')
                      AND category IS NOT NULL AND category != ''
                    ORDER BY category
                LOOP
                    INSERT INTO categories (user_id, name, parent_id, sort_order)
                    VALUES (_uid, _cat, NULL, _sort)
                    ON CONFLICT DO NOTHING;
                    _sort := _sort + 1;
                END LOOP;

                -- Set category_id on metrics with fill_time + category (subcategory)
                UPDATE metric_definitions md SET category_id = c.id
                FROM categories c
                JOIN categories p ON c.parent_id = p.id
                WHERE md.user_id = c.user_id
                  AND md.fill_time = p.name
                  AND md.category = c.name
                  AND md.fill_time IS NOT NULL AND md.fill_time != ''
                  AND md.category IS NOT NULL AND md.category != '';

                -- Set category_id on metrics with fill_time only (no category)
                UPDATE metric_definitions md SET category_id = c.id
                FROM categories c
                WHERE md.user_id = c.user_id
                  AND md.fill_time = c.name
                  AND c.parent_id IS NULL
                  AND (md.category IS NULL OR md.category = '')
                  AND md.fill_time IS NOT NULL AND md.fill_time != ''
                  AND md.category_id IS NULL;

                -- Set category_id on metrics with category only (no fill_time)
                UPDATE metric_definitions md SET category_id = c.id
                FROM categories c
                WHERE md.user_id = c.user_id
                  AND md.category = c.name
                  AND c.parent_id IS NULL
                  AND (md.fill_time IS NULL OR md.fill_time = '')
                  AND md.category_id IS NULL;

                -- Drop old columns
                ALTER TABLE metric_definitions DROP COLUMN IF EXISTS category;
                ALTER TABLE metric_definitions DROP COLUMN IF EXISTS fill_time;
            END IF;
        END $migrate$;
    """),
    (4, "add_notes_table", """
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_notes_metric_user_date ON notes(metric_id, user_id, date);
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
