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
    (22, "slots_to_checkpoints_and_intervals", """
        -- 1. Rename measurement_slots → checkpoints (skip if already done or fresh DB)
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'measurement_slots')
               AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'checkpoints') THEN
                ALTER TABLE measurement_slots RENAME TO checkpoints;
            END IF;
        END $$;
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_measurement_slots_user_label')
               AND NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_checkpoints_user_label') THEN
                ALTER INDEX idx_measurement_slots_user_label RENAME TO idx_checkpoints_user_label;
            END IF;
        END $$;

        -- 2. Create intervals table
        CREATE TABLE IF NOT EXISTS intervals (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            start_checkpoint_id INTEGER NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
            end_checkpoint_id INTEGER NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
            UNIQUE(user_id, start_checkpoint_id, end_checkpoint_id)
        );
        CREATE INDEX IF NOT EXISTS idx_intervals_user ON intervals(user_id);

        -- 3. Populate intervals from consecutive checkpoint pairs (ALL checkpoints, incl deleted)
        DO $intervals$
        DECLARE
            _uid INTEGER;
            _prev_id INTEGER;
            _curr_id INTEGER;
            _first BOOLEAN;
        BEGIN
            FOR _uid IN SELECT DISTINCT user_id FROM checkpoints
            LOOP
                _first := TRUE;
                _prev_id := NULL;
                FOR _curr_id IN
                    SELECT id FROM checkpoints
                    WHERE user_id = _uid
                    ORDER BY sort_order
                LOOP
                    IF _first THEN
                        _first := FALSE;
                    ELSE
                        INSERT INTO intervals (user_id, start_checkpoint_id, end_checkpoint_id)
                        VALUES (_uid, _prev_id, _curr_id)
                        ON CONFLICT DO NOTHING;
                    END IF;
                    _prev_id := _curr_id;
                END LOOP;
            END LOOP;
        END $intervals$;

        -- 4. Create metric_checkpoints table (for assessment metrics)
        CREATE TABLE IF NOT EXISTS metric_checkpoints (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            checkpoint_id INTEGER NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            UNIQUE(metric_id, checkpoint_id)
        );
        CREATE INDEX IF NOT EXISTS idx_metric_checkpoints_metric ON metric_checkpoints(metric_id);
        CREATE INDEX IF NOT EXISTS idx_metric_checkpoints_checkpoint ON metric_checkpoints(checkpoint_id);

        -- 5. Create metric_intervals table (for fact metrics with intervals)
        CREATE TABLE IF NOT EXISTS metric_intervals (
            id SERIAL PRIMARY KEY,
            metric_id INTEGER NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
            interval_id INTEGER NOT NULL REFERENCES intervals(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            UNIQUE(metric_id, interval_id)
        );
        CREATE INDEX IF NOT EXISTS idx_metric_intervals_metric ON metric_intervals(metric_id);
        CREATE INDEX IF NOT EXISTS idx_metric_intervals_interval ON metric_intervals(interval_id);

        -- 6. Migrate metric_slots → metric_checkpoints (assessment metrics) — skip if metric_slots gone
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'metric_slots') THEN
                INSERT INTO metric_checkpoints (metric_id, checkpoint_id, sort_order, enabled, category_id)
                SELECT ms.metric_id, ms.slot_id, ms.sort_order, ms.enabled, ms.category_id
                FROM metric_slots ms
                JOIN metric_definitions md ON md.id = ms.metric_id
                WHERE md.is_checkpoint = TRUE
                ON CONFLICT DO NOTHING;

                -- 7. Migrate metric_slots → metric_intervals (fact metrics)
                INSERT INTO metric_intervals (metric_id, interval_id, sort_order, enabled, category_id)
                SELECT ms.metric_id, i.id, ms.sort_order, ms.enabled, ms.category_id
                FROM metric_slots ms
                JOIN metric_definitions md ON md.id = ms.metric_id
                JOIN intervals i ON i.start_checkpoint_id = ms.slot_id AND i.user_id = md.user_id
                WHERE md.is_checkpoint = FALSE
                ON CONFLICT DO NOTHING;
            END IF;
        END $$;

        -- 8. Add checkpoint_id and interval_id to entries
        ALTER TABLE entries ADD COLUMN IF NOT EXISTS checkpoint_id INTEGER REFERENCES checkpoints(id);
        ALTER TABLE entries ADD COLUMN IF NOT EXISTS interval_id INTEGER REFERENCES intervals(id);

        -- 9-10. Migrate entries slot_id → checkpoint_id / interval_id (skip if slot_id gone)
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'entries' AND column_name = 'slot_id') THEN
                UPDATE entries e
                SET checkpoint_id = e.slot_id
                FROM metric_definitions md
                WHERE e.metric_id = md.id
                  AND md.is_checkpoint = TRUE
                  AND e.slot_id IS NOT NULL
                  AND e.checkpoint_id IS NULL;

                UPDATE entries e
                SET interval_id = i.id
                FROM metric_definitions md, intervals i
                WHERE e.metric_id = md.id
                  AND md.is_checkpoint = FALSE
                  AND e.slot_id IS NOT NULL
                  AND e.interval_id IS NULL
                  AND i.start_checkpoint_id = e.slot_id
                  AND i.user_id = e.user_id;

                -- Fallback: match by end_checkpoint_id for moment metrics
                -- (old system allowed selecting any slot, not just interval starts)
                -- Skip if interval_id already taken for this metric+user+date
                UPDATE entries e
                SET interval_id = i.id
                FROM metric_definitions md, intervals i
                WHERE e.metric_id = md.id
                  AND md.is_checkpoint = FALSE
                  AND e.slot_id IS NOT NULL
                  AND e.interval_id IS NULL
                  AND i.end_checkpoint_id = e.slot_id
                  AND i.user_id = e.user_id
                  AND NOT EXISTS (
                      SELECT 1 FROM entries e2
                      WHERE e2.metric_id = e.metric_id
                        AND e2.user_id = e.user_id
                        AND e2.date = e.date
                        AND e2.interval_id = i.id
                  );

                ALTER TABLE entries DROP COLUMN slot_id;
            END IF;
        END $$;

        -- 11. CHECK: checkpoint_id and interval_id mutually exclusive
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'entries_checkpoint_interval_exclusive') THEN
                ALTER TABLE entries ADD CONSTRAINT entries_checkpoint_interval_exclusive
                    CHECK (NOT (checkpoint_id IS NOT NULL AND interval_id IS NOT NULL));
            END IF;
        END $$;

        -- 12. Replace partial unique indexes
        DROP INDEX IF EXISTS entries_no_slot_key;
        DROP INDEX IF EXISTS entries_with_slot_key;
        CREATE UNIQUE INDEX IF NOT EXISTS entries_checkpoint_key
            ON entries(metric_id, user_id, date, checkpoint_id)
            WHERE checkpoint_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS entries_interval_key
            ON entries(metric_id, user_id, date, interval_id)
            WHERE interval_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS entries_no_binding_key
            ON entries(metric_id, user_id, date)
            WHERE checkpoint_id IS NULL AND interval_id IS NULL;

        -- 14. Add flags to metric_definitions
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS all_checkpoints BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE metric_definitions ADD COLUMN IF NOT EXISTS all_intervals BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE metric_definitions DROP COLUMN IF EXISTS interval_start_slot_id;

        -- 15. CHECK: all_checkpoints only for assessments, all_intervals only for facts
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'md_all_checkpoints_role') THEN
                ALTER TABLE metric_definitions ADD CONSTRAINT md_all_checkpoints_role
                    CHECK (NOT (all_checkpoints = TRUE AND is_checkpoint = FALSE));
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'md_all_intervals_role') THEN
                ALTER TABLE metric_definitions ADD CONSTRAINT md_all_intervals_role
                    CHECK (NOT (all_intervals = TRUE AND is_checkpoint = TRUE));
            END IF;
        END $$;

        -- 16. Clean correlation data (source_key format changes)
        DELETE FROM correlation_pairs;
        DELETE FROM correlation_reports;
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'correlation_pairs' AND column_name = 'slot_a_id') THEN
                ALTER TABLE correlation_pairs RENAME COLUMN slot_a_id TO checkpoint_a_id;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'correlation_pairs' AND column_name = 'slot_b_id') THEN
                ALTER TABLE correlation_pairs RENAME COLUMN slot_b_id TO checkpoint_b_id;
            END IF;
        END $$;
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS checkpoint_a_id INTEGER;
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS checkpoint_b_id INTEGER;
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS interval_a_id INTEGER;
        ALTER TABLE correlation_pairs ADD COLUMN IF NOT EXISTS interval_b_id INTEGER;

        -- 17. Drop old tables
        DROP TABLE IF EXISTS metric_slots;

        -- 18. Ensure intervals exist for all users with checkpoints (idempotent)
        DO $ensure_intervals$
        DECLARE
            _uid INTEGER;
            _prev_id INTEGER;
            _curr_id INTEGER;
            _first BOOLEAN;
        BEGIN
            FOR _uid IN SELECT DISTINCT user_id FROM checkpoints WHERE deleted = FALSE
            LOOP
                _first := TRUE;
                _prev_id := NULL;
                FOR _curr_id IN
                    SELECT id FROM checkpoints
                    WHERE user_id = _uid AND deleted = FALSE
                    ORDER BY sort_order, id
                LOOP
                    IF _first THEN
                        _first := FALSE;
                    ELSE
                        INSERT INTO intervals (user_id, start_checkpoint_id, end_checkpoint_id)
                        VALUES (_uid, _prev_id, _curr_id)
                        ON CONFLICT DO NOTHING;
                    END IF;
                    _prev_id := _curr_id;
                END LOOP;
            END LOOP;
        END $ensure_intervals$;
    """),
    (23, "drop_all_checkpoints_all_intervals", """
        ALTER TABLE metric_definitions DROP CONSTRAINT IF EXISTS md_all_checkpoints_role;
        ALTER TABLE metric_definitions DROP CONSTRAINT IF EXISTS md_all_intervals_role;
        ALTER TABLE metric_definitions DROP COLUMN IF EXISTS all_checkpoints;
        ALTER TABLE metric_definitions DROP COLUMN IF EXISTS all_intervals;
    """),
    (24, "remove_moment_binding", """
        -- Create metric_intervals for all active intervals of each moment metric
        DO $migrate_moment$
        DECLARE
            _metric RECORD;
            _interval RECORD;
            _sort INTEGER;
        BEGIN
            FOR _metric IN
                SELECT md.id AS metric_id, md.user_id
                FROM metric_definitions md
                WHERE md.interval_binding = 'moment'
            LOOP
                _sort := 0;
                FOR _interval IN
                    SELECT i.id
                    FROM intervals i
                    JOIN checkpoints cs ON cs.id = i.start_checkpoint_id AND cs.deleted = FALSE
                    JOIN checkpoints ce ON ce.id = i.end_checkpoint_id AND ce.deleted = FALSE
                    WHERE i.user_id = _metric.user_id
                      AND NOT EXISTS (
                          SELECT 1 FROM checkpoints cm
                          WHERE cm.user_id = _metric.user_id AND cm.deleted = FALSE
                            AND cm.sort_order > cs.sort_order AND cm.sort_order < ce.sort_order
                      )
                    ORDER BY cs.sort_order
                LOOP
                    INSERT INTO metric_intervals (metric_id, interval_id, sort_order, enabled)
                    VALUES (_metric.metric_id, _interval.id, _sort, TRUE)
                    ON CONFLICT (metric_id, interval_id) DO UPDATE SET enabled = TRUE;
                    _sort := _sort + 1;
                END LOOP;
            END LOOP;
        END $migrate_moment$;

        -- Update interval_binding
        UPDATE metric_definitions SET interval_binding = 'by_interval' WHERE interval_binding = 'moment';
    """),
    (25, "create_daily_layout", """
        CREATE TABLE IF NOT EXISTS daily_layout (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            block_type VARCHAR(20) NOT NULL,
            block_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, block_type, block_id)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_layout_user ON daily_layout(user_id);
    """),
    (26, "seed_daily_layout", """
        -- Seed daily_layout for all existing users
        DO $seed_layout$
        DECLARE
            _user RECORD;
            _cp RECORD;
            _iv RECORD;
            _cat_id INTEGER;
            _metric RECORD;
            _sort INTEGER;
            _bound_ids INTEGER[];
        BEGIN
            FOR _user IN SELECT id FROM users LOOP
                -- Skip if layout already exists
                IF EXISTS (SELECT 1 FROM daily_layout WHERE user_id = _user.id) THEN
                    CONTINUE;
                END IF;

                _sort := 0;

                -- Collect bound metric IDs
                SELECT ARRAY(
                    SELECT DISTINCT metric_id FROM metric_checkpoints mc
                    JOIN metric_definitions md ON md.id = mc.metric_id
                    WHERE md.user_id = _user.id AND mc.enabled = TRUE AND md.enabled = TRUE
                    UNION
                    SELECT DISTINCT metric_id FROM metric_intervals mi
                    JOIN metric_definitions md ON md.id = mi.metric_id
                    WHERE md.user_id = _user.id AND mi.enabled = TRUE AND md.enabled = TRUE
                ) INTO _bound_ids;

                -- Checkpoint blocks + interval blocks after each checkpoint
                FOR _cp IN
                    SELECT id, sort_order FROM checkpoints
                    WHERE user_id = _user.id AND deleted = FALSE
                    ORDER BY sort_order
                LOOP
                    INSERT INTO daily_layout (user_id, block_type, block_id, sort_order)
                    VALUES (_user.id, 'checkpoint', _cp.id, _sort)
                    ON CONFLICT DO NOTHING;
                    _sort := _sort + 10;

                    -- Intervals starting at this checkpoint
                    FOR _iv IN
                        SELECT i.id FROM intervals i
                        JOIN checkpoints cs ON cs.id = i.start_checkpoint_id
                        JOIN checkpoints ce ON ce.id = i.end_checkpoint_id
                        WHERE i.user_id = _user.id
                          AND i.start_checkpoint_id = _cp.id
                          AND cs.deleted = FALSE AND ce.deleted = FALSE
                          AND NOT EXISTS (
                              SELECT 1 FROM checkpoints cm
                              WHERE cm.user_id = _user.id AND cm.deleted = FALSE
                                AND cm.sort_order > cs.sort_order AND cm.sort_order < ce.sort_order
                          )
                        ORDER BY cs.sort_order
                    LOOP
                        INSERT INTO daily_layout (user_id, block_type, block_id, sort_order)
                        VALUES (_user.id, 'interval', _iv.id, _sort)
                        ON CONFLICT DO NOTHING;
                        _sort := _sort + 10;
                    END LOOP;
                END LOOP;

                -- Category blocks (standalone metrics with category)
                FOR _cat_id IN
                    SELECT DISTINCT md.category_id FROM metric_definitions md
                    WHERE md.user_id = _user.id AND md.enabled = TRUE
                      AND md.category_id IS NOT NULL
                      AND md.id != ALL(_bound_ids)
                    ORDER BY md.category_id
                LOOP
                    INSERT INTO daily_layout (user_id, block_type, block_id, sort_order)
                    VALUES (_user.id, 'category', _cat_id, _sort)
                    ON CONFLICT DO NOTHING;
                    _sort := _sort + 10;
                END LOOP;

                -- Metric blocks (standalone without category)
                FOR _metric IN
                    SELECT md.id FROM metric_definitions md
                    WHERE md.user_id = _user.id AND md.enabled = TRUE
                      AND md.category_id IS NULL
                      AND md.id != ALL(_bound_ids)
                    ORDER BY md.sort_order, md.id
                LOOP
                    INSERT INTO daily_layout (user_id, block_type, block_id, sort_order)
                    VALUES (_user.id, 'metric', _metric.id, _sort)
                    ON CONFLICT DO NOTHING;
                    _sort := _sort + 10;
                END LOOP;
            END LOOP;
        END $seed_layout$;
    """),
    (27, "remove_category_id_from_junction_tables", """
        -- Migrate category_id from junction tables to metric_definitions where missing
        UPDATE metric_definitions md
        SET category_id = sub.cat_id
        FROM (
            SELECT DISTINCT ON (mc.metric_id) mc.metric_id, mc.category_id AS cat_id
            FROM metric_checkpoints mc
            WHERE mc.category_id IS NOT NULL
        ) sub
        WHERE md.id = sub.metric_id AND md.category_id IS NULL;

        UPDATE metric_definitions md
        SET category_id = sub.cat_id
        FROM (
            SELECT DISTINCT ON (mi.metric_id) mi.metric_id, mi.category_id AS cat_id
            FROM metric_intervals mi
            WHERE mi.category_id IS NOT NULL
        ) sub
        WHERE md.id = sub.metric_id AND md.category_id IS NULL;

        ALTER TABLE metric_checkpoints DROP COLUMN IF EXISTS category_id;
        ALTER TABLE metric_intervals DROP COLUMN IF EXISTS category_id;
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
