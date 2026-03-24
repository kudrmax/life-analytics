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
    (5, "add_p_value_to_correlation_pairs", """
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS p_value FLOAT;
    """),
    (6, "add_private_column", """
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS private BOOLEAN NOT NULL DEFAULT FALSE;
    """),
    (7, "add_privacy_mode_to_users", """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_mode BOOLEAN NOT NULL DEFAULT FALSE;
    """),
    (8, "add_category_id_to_slots", """
        -- Add category_id column to measurement_slots
        ALTER TABLE measurement_slots ADD COLUMN IF NOT EXISTS
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL;

        -- Copy metric category_id to all its slots
        UPDATE measurement_slots ms
        SET category_id = md.category_id
        FROM metric_definitions md
        WHERE ms.metric_id = md.id
          AND ms.category_id IS NULL
          AND md.category_id IS NOT NULL;

        -- Clear category_id on multi-slot metrics (category now lives on slots)
        UPDATE metric_definitions md
        SET category_id = NULL
        WHERE EXISTS (
            SELECT 1 FROM measurement_slots ms
            WHERE ms.metric_id = md.id AND ms.enabled = TRUE
        );
    """),
    (9, "add_metric_condition", """
        CREATE TABLE IF NOT EXISTS metric_condition (
            metric_id INTEGER PRIMARY KEY REFERENCES metric_definitions(id) ON DELETE CASCADE,
            depends_on_metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            condition_type VARCHAR(20) NOT NULL,
            condition_value JSONB
        );
        CREATE INDEX IF NOT EXISTS idx_metric_condition_depends ON metric_condition(depends_on_metric_id);
    """),
    (10, "add_insights_tables", """
        CREATE TABLE IF NOT EXISTS insights (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS insight_metrics (
            id SERIAL PRIMARY KEY,
            insight_id INTEGER NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
            metric_id INTEGER REFERENCES metric_definitions(id) ON DELETE CASCADE,
            custom_label VARCHAR(200),
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_insights_user ON insights(user_id);
        CREATE INDEX IF NOT EXISTS idx_insight_metrics_insight ON insight_metrics(insight_id);
    """),
    (11, "replace_labels_with_source_keys", """
        -- Delete existing reports (max 1 per user, will be recomputed)
        DELETE FROM correlation_pairs;
        DELETE FROM correlation_reports;
        -- Add new columns
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS source_key_a VARCHAR(100) NOT NULL DEFAULT '';
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS source_key_b VARCHAR(100) NOT NULL DEFAULT '';
        -- Drop old columns
        ALTER TABLE correlation_pairs DROP COLUMN IF EXISTS label_a;
        ALTER TABLE correlation_pairs DROP COLUMN IF EXISTS label_b;
    """),
    (12, "add_quality_issue_to_correlation_pairs", """
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS quality_issue VARCHAR(30);
    """),
    (13, "global_measurement_slots", """
        -- 1. Add user_id column to measurement_slots (nullable initially)
        ALTER TABLE measurement_slots ADD COLUMN IF NOT EXISTS
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

        -- 2. Populate user_id from metric_definitions
        UPDATE measurement_slots ms
        SET user_id = md.user_id
        FROM metric_definitions md
        WHERE ms.metric_id = md.id AND ms.user_id IS NULL;

        -- 3. Create metric_slots junction table
        CREATE TABLE IF NOT EXISTS metric_slots (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            slot_id INTEGER NOT NULL REFERENCES measurement_slots(id) ON DELETE RESTRICT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            UNIQUE(metric_id, slot_id)
        );
        CREATE INDEX IF NOT EXISTS idx_metric_slots_metric ON metric_slots(metric_id);
        CREATE INDEX IF NOT EXISTS idx_metric_slots_slot ON metric_slots(slot_id);

        -- 4. Populate metric_slots from current measurement_slots (only if metric_id column exists)
        DO $populate$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'measurement_slots' AND column_name = 'metric_id'
            ) THEN
                INSERT INTO metric_slots (metric_id, slot_id, sort_order, enabled, category_id)
                SELECT ms.metric_id, ms.id, ms.sort_order,
                       COALESCE(ms.enabled, TRUE),
                       ms.category_id
                FROM measurement_slots ms
                WHERE ms.metric_id IS NOT NULL
                ON CONFLICT (metric_id, slot_id) DO NOTHING;
            END IF;
        END $populate$;

        -- 5. Merge duplicate slots per user (same label, case-insensitive)
        DO $merge$
        DECLARE
            _uid INTEGER;
            _label TEXT;
            _canonical_id INTEGER;
            _dup_id INTEGER;
            _dup_metric INTEGER;
            _dup_sort INTEGER;
            _dup_enabled BOOLEAN;
            _dup_cat INTEGER;
        BEGIN
            -- Only run if metric_id column still exists (first time migration)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'measurement_slots' AND column_name = 'metric_id'
            ) THEN
                RETURN;
            END IF;

            FOR _uid, _label IN
                SELECT ms.user_id, LOWER(TRIM(ms.label))
                FROM measurement_slots ms
                WHERE ms.user_id IS NOT NULL
                GROUP BY ms.user_id, LOWER(TRIM(ms.label))
                HAVING COUNT(*) > 1
            LOOP
                -- Pick canonical = lowest id
                SELECT id INTO _canonical_id
                FROM measurement_slots
                WHERE user_id = _uid AND LOWER(TRIM(label)) = _label
                ORDER BY id
                LIMIT 1;

                -- Process each duplicate (non-canonical)
                FOR _dup_id, _dup_metric, _dup_sort, _dup_enabled, _dup_cat IN
                    SELECT ms.id, msl.metric_id, msl.sort_order, msl.enabled, msl.category_id
                    FROM measurement_slots ms
                    JOIN metric_slots msl ON msl.slot_id = ms.id
                    WHERE ms.user_id = _uid
                      AND LOWER(TRIM(ms.label)) = _label
                      AND ms.id != _canonical_id
                LOOP
                    -- Check if (metric_id, canonical) already exists in metric_slots
                    IF EXISTS (
                        SELECT 1 FROM metric_slots
                        WHERE metric_id = _dup_metric AND slot_id = _canonical_id
                    ) THEN
                        -- Duplicate junction row — just delete the old one
                        DELETE FROM metric_slots WHERE metric_id = _dup_metric AND slot_id = _dup_id;
                    ELSE
                        -- Repoint metric_slots to canonical
                        UPDATE metric_slots
                        SET slot_id = _canonical_id
                        WHERE metric_id = _dup_metric AND slot_id = _dup_id;
                    END IF;

                    -- Handle entries: resolve unique conflicts before repointing
                    -- Delete duplicate entries that would conflict
                    DELETE FROM entries e1
                    USING entries e2
                    WHERE e1.slot_id = _dup_id
                      AND e2.slot_id = _canonical_id
                      AND e1.metric_id = e2.metric_id
                      AND e1.user_id = e2.user_id
                      AND e1.date = e2.date
                      AND e1.id != e2.id;

                    -- Repoint remaining entries
                    UPDATE entries SET slot_id = _canonical_id WHERE slot_id = _dup_id;
                END LOOP;

                -- Delete orphaned non-canonical slots (no metric_slots or entries referencing them)
                DELETE FROM measurement_slots ms
                WHERE ms.user_id = _uid
                  AND LOWER(TRIM(ms.label)) = _label
                  AND ms.id != _canonical_id
                  AND NOT EXISTS (SELECT 1 FROM metric_slots WHERE slot_id = ms.id)
                  AND NOT EXISTS (SELECT 1 FROM entries WHERE slot_id = ms.id);
            END LOOP;
        END $merge$;

        -- 6. Delete correlation data (will be recomputed)
        DELETE FROM correlation_pairs;
        DELETE FROM correlation_reports;

        -- 7. Drop old columns from measurement_slots
        ALTER TABLE measurement_slots DROP COLUMN IF EXISTS metric_id;
        ALTER TABLE measurement_slots DROP COLUMN IF EXISTS enabled;
        ALTER TABLE measurement_slots DROP COLUMN IF EXISTS category_id;

        -- 8. Make user_id NOT NULL
        DO $notnull$
        BEGIN
            -- Delete orphaned slots without user_id (shouldn't happen but safety)
            DELETE FROM measurement_slots WHERE user_id IS NULL;
            ALTER TABLE measurement_slots ALTER COLUMN user_id SET NOT NULL;
        EXCEPTION WHEN others THEN NULL;
        END $notnull$;

        -- 9. Create unique index on (user_id, LOWER(label))
        CREATE UNIQUE INDEX IF NOT EXISTS idx_measurement_slots_user_label
            ON measurement_slots(user_id, LOWER(label));
    """),
    (14, "add_labels_to_scale_config", """
        ALTER TABLE scale_config ADD COLUMN IF NOT EXISTS labels JSONB;
    """),
    (15, "add_description_to_metrics", """
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS description TEXT DEFAULT NULL;
    """),
    (16, "add_hide_in_cards_to_metrics", """
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS hide_in_cards BOOLEAN NOT NULL DEFAULT FALSE;
    """),
    (17, "add_checkpoints", """
        ALTER TABLE measurement_slots ADD COLUMN IF NOT EXISTS description TEXT;
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS is_checkpoint BOOLEAN NOT NULL DEFAULT FALSE;

        UPDATE metric_definitions SET is_checkpoint = TRUE
        WHERE id IN (SELECT DISTINCT metric_id FROM metric_slots WHERE enabled = TRUE);
    """),
    (18, "fix_metric_slots_cascade", """
        ALTER TABLE metric_slots DROP CONSTRAINT IF EXISTS metric_slots_slot_id_fkey;
        ALTER TABLE metric_slots ADD CONSTRAINT metric_slots_slot_id_fkey
            FOREIGN KEY (slot_id) REFERENCES measurement_slots(id) ON DELETE CASCADE;
    """),
    (19, "add_interval_binding", """
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS interval_binding VARCHAR(20) NOT NULL DEFAULT 'daily';
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS interval_start_slot_id INTEGER REFERENCES measurement_slots(id) ON DELETE SET NULL;
    """),
    (20, "add_deleted_to_measurement_slots", """
        ALTER TABLE measurement_slots ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE;
    """),
    (21, "unify_interval_binding", """
        UPDATE metric_definitions SET interval_binding = 'all_day' WHERE interval_binding = 'daily';
        UPDATE metric_definitions SET interval_binding = 'by_interval' WHERE interval_binding IN ('fixed', 'floating');
        ALTER TABLE metric_definitions ALTER COLUMN interval_binding SET DEFAULT 'all_day';
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
