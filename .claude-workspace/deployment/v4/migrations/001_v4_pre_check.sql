-- Migration V4-001: Pre-Migration Verification
-- This script checks prerequisites before running V4 migrations.
-- Run this BEFORE 008_v4_entity_tables.sql and 009_v4_age_setup.sql
--
-- Usage: psql -U events -d events -f 001_v4_pre_check.sql
-- Exit code 0 = all checks passed
-- Exit code 1 = one or more checks failed

\echo '=============================================='
\echo 'V4 Pre-Migration Verification'
\echo '=============================================='
\echo ''

-- Create temporary function for assertions
CREATE OR REPLACE FUNCTION pg_temp.assert_check(
    check_name TEXT,
    passed BOOLEAN,
    message TEXT DEFAULT ''
) RETURNS VOID AS $$
BEGIN
    IF passed THEN
        RAISE NOTICE '[PASS] %', check_name;
    ELSE
        RAISE EXCEPTION '[FAIL] % - %', check_name, message;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Check 1: PostgreSQL Version
-- ============================================================================
DO $$
DECLARE
    pg_version INT;
BEGIN
    SELECT current_setting('server_version_num')::INT INTO pg_version;

    PERFORM pg_temp.assert_check(
        'PostgreSQL version >= 14',
        pg_version >= 140000,
        format('Found version %s, need 14+', current_setting('server_version'))
    );
END $$;

-- ============================================================================
-- Check 2: pgvector Extension Available
-- ============================================================================
DO $$
DECLARE
    vector_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'vector'
    ) INTO vector_exists;

    PERFORM pg_temp.assert_check(
        'pgvector extension installed',
        vector_exists,
        'Run: CREATE EXTENSION IF NOT EXISTS vector;'
    );
END $$;

-- ============================================================================
-- Check 3: V3 Tables Exist
-- ============================================================================
DO $$
DECLARE
    tables_exist BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = 'semantic_event'
    ) AND EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = 'artifact_revision'
    ) INTO tables_exist;

    PERFORM pg_temp.assert_check(
        'V3 tables exist (semantic_event, artifact_revision)',
        tables_exist,
        'Run V3 migrations first: init.sql'
    );
END $$;

-- ============================================================================
-- Check 4: V4 Entity Tables Do Not Exist (or are empty for re-run)
-- ============================================================================
DO $$
DECLARE
    entity_table_exists BOOLEAN;
    entity_count INT;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = 'entity'
    ) INTO entity_table_exists;

    IF entity_table_exists THEN
        SELECT COUNT(*) INTO entity_count FROM entity;

        IF entity_count > 0 THEN
            RAISE NOTICE '[WARN] entity table exists with % rows - migration will be idempotent', entity_count;
        ELSE
            RAISE NOTICE '[INFO] entity table exists but is empty - safe to proceed';
        END IF;
    ELSE
        RAISE NOTICE '[PASS] entity table does not exist - ready for migration';
    END IF;
END $$;

-- ============================================================================
-- Check 5: Apache AGE Available (for 009 migration)
-- ============================================================================
DO $$
DECLARE
    age_available BOOLEAN;
    age_installed BOOLEAN;
BEGIN
    -- Check if AGE is available in pg_available_extensions
    SELECT EXISTS (
        SELECT 1 FROM pg_available_extensions WHERE name = 'age'
    ) INTO age_available;

    -- Check if AGE is already installed
    SELECT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'age'
    ) INTO age_installed;

    IF age_installed THEN
        RAISE NOTICE '[PASS] Apache AGE extension already installed';
    ELSIF age_available THEN
        RAISE NOTICE '[PASS] Apache AGE extension available for installation';
    ELSE
        RAISE NOTICE '[WARN] Apache AGE extension NOT available - graph features will be disabled';
        RAISE NOTICE '       Install AGE or use V4_GRAPH_ENABLED=false';
    END IF;
END $$;

-- ============================================================================
-- Check 6: Sufficient Disk Space (estimate)
-- ============================================================================
DO $$
DECLARE
    db_size_mb NUMERIC;
BEGIN
    SELECT pg_database_size(current_database()) / (1024 * 1024) INTO db_size_mb;

    -- V4 typically adds 20-30% to database size
    IF db_size_mb > 5000 THEN
        RAISE NOTICE '[WARN] Database size: % MB - ensure sufficient disk space for V4 tables', ROUND(db_size_mb);
    ELSE
        RAISE NOTICE '[PASS] Database size: % MB - sufficient for V4', ROUND(db_size_mb);
    END IF;
END $$;

-- ============================================================================
-- Check 7: Connection Count
-- ============================================================================
DO $$
DECLARE
    conn_count INT;
    max_conn INT;
BEGIN
    SELECT COUNT(*) INTO conn_count FROM pg_stat_activity WHERE datname = current_database();
    SELECT setting::INT INTO max_conn FROM pg_settings WHERE name = 'max_connections';

    IF conn_count > max_conn * 0.8 THEN
        RAISE NOTICE '[WARN] High connection count: %/% - consider increasing max_connections', conn_count, max_conn;
    ELSE
        RAISE NOTICE '[PASS] Connection count: %/%', conn_count, max_conn;
    END IF;
END $$;

-- ============================================================================
-- Summary
-- ============================================================================
\echo ''
\echo '=============================================='
\echo 'Pre-Migration Verification Complete'
\echo '=============================================='
\echo ''
\echo 'If all checks passed, proceed with:'
\echo '  1. psql -f 008_v4_entity_tables.sql'
\echo '  2. psql -f 009_v4_age_setup.sql'
\echo ''
\echo 'If AGE is unavailable, you can still run migration 008'
\echo 'and set V4_GRAPH_ENABLED=false in your environment.'
\echo ''
