-- Rollback Migration 008: Remove V4 Entity Tables
-- WARNING: This will DELETE all entity resolution data!
-- Run rollback_009.sql FIRST if graph was set up
--
-- Use this if:
--   - Rolling back to V3 completely
--   - Entity resolution is causing issues
--   - Starting fresh with entity data
--
-- After rollback, V4 entity features will be disabled
--
-- Usage: psql -U events -d events -f rollback_008.sql

BEGIN;

\echo 'Starting V4 Entity Tables Rollback...'
\echo 'WARNING: This will DELETE all entity resolution data!'

-- ============================================================================
-- 1. Check for Existing Data
-- ============================================================================

DO $$
DECLARE
    entity_count INT := 0;
    mention_count INT := 0;
    actor_count INT := 0;
    subject_count INT := 0;
BEGIN
    -- Count records in each table (if they exist)
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'entity') THEN
        SELECT COUNT(*) INTO entity_count FROM entity;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'entity_mention') THEN
        SELECT COUNT(*) INTO mention_count FROM entity_mention;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'event_actor') THEN
        SELECT COUNT(*) INTO actor_count FROM event_actor;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'event_subject') THEN
        SELECT COUNT(*) INTO subject_count FROM event_subject;
    END IF;

    RAISE NOTICE 'Data to be deleted:';
    RAISE NOTICE '  - Entities: %', entity_count;
    RAISE NOTICE '  - Entity mentions: %', mention_count;
    RAISE NOTICE '  - Event actors: %', actor_count;
    RAISE NOTICE '  - Event subjects: %', subject_count;

    IF entity_count + mention_count + actor_count + subject_count > 0 THEN
        RAISE NOTICE 'Total records to be deleted: %',
            entity_count + mention_count + actor_count + subject_count;
    END IF;
END $$;

-- ============================================================================
-- 2. Drop Helper Functions
-- ============================================================================

DROP FUNCTION IF EXISTS normalize_entity_name(TEXT) CASCADE;
DROP FUNCTION IF EXISTS find_entity_by_name(TEXT, TEXT) CASCADE;

\echo 'Helper functions dropped'

-- ============================================================================
-- 3. Drop Tables in Reverse Dependency Order
-- ============================================================================

-- event_subject depends on semantic_event and entity
DROP TABLE IF EXISTS event_subject CASCADE;
\echo 'Dropped: event_subject'

-- event_actor depends on semantic_event and entity
DROP TABLE IF EXISTS event_actor CASCADE;
\echo 'Dropped: event_actor'

-- entity_mention depends on entity
DROP TABLE IF EXISTS entity_mention CASCADE;
\echo 'Dropped: entity_mention'

-- entity_alias depends on entity
DROP TABLE IF EXISTS entity_alias CASCADE;
\echo 'Dropped: entity_alias'

-- entity is the parent table
DROP TABLE IF EXISTS entity CASCADE;
\echo 'Dropped: entity'

-- ============================================================================
-- 4. Verify Rollback
-- ============================================================================

DO $$
DECLARE
    remaining_tables INT;
BEGIN
    SELECT COUNT(*) INTO remaining_tables
    FROM pg_tables
    WHERE tablename IN ('entity', 'entity_alias', 'entity_mention', 'event_actor', 'event_subject');

    IF remaining_tables > 0 THEN
        RAISE WARNING 'Some V4 tables still exist: %', remaining_tables;
    ELSE
        RAISE NOTICE 'All V4 entity tables successfully removed';
    END IF;
END $$;

-- ============================================================================
-- 5. Verify V3 Tables Still Exist
-- ============================================================================

DO $$
DECLARE
    v3_tables INT;
BEGIN
    SELECT COUNT(*) INTO v3_tables
    FROM pg_tables
    WHERE tablename IN ('artifact_revision', 'semantic_event', 'event_evidence', 'event_jobs');

    IF v3_tables < 4 THEN
        RAISE WARNING 'V3 tables may be missing: found %/4', v3_tables;
    ELSE
        RAISE NOTICE 'V3 tables intact: %/4', v3_tables;
    END IF;
END $$;

\echo ''
\echo '=============================================='
\echo 'V4 Entity Tables Rollback Complete'
\echo '=============================================='
\echo ''
\echo 'Tables removed:'
\echo '  - entity'
\echo '  - entity_alias'
\echo '  - entity_mention'
\echo '  - event_actor'
\echo '  - event_subject'
\echo ''
\echo 'Functions removed:'
\echo '  - normalize_entity_name(TEXT)'
\echo '  - find_entity_by_name(TEXT, TEXT)'
\echo ''
\echo 'Preserved:'
\echo '  - V3 tables (artifact_revision, semantic_event, event_evidence, event_jobs)'
\echo '  - pgvector extension'
\echo '  - V3 indexes and triggers'
\echo ''
\echo 'Next steps:'
\echo '  1. Restart services with V3 configuration'
\echo '  2. Verify V3 functionality with healthcheck'
\echo ''

COMMIT;
