-- Rollback Migration 009: Remove AGE Graph Setup
-- WARNING: This will DELETE all graph data (nodes and edges)
-- Entity data in PostgreSQL tables is NOT affected
--
-- Use this if:
--   - AGE is causing issues and you need to disable graph features
--   - Rolling back to V3 (run rollback_008.sql after this)
--   - Recreating graph from scratch
--
-- After rollback, set V4_GRAPH_ENABLED=false in environment
--
-- Usage: psql -U events -d events -f rollback_009.sql

BEGIN;

\echo 'Starting V4 AGE Graph Rollback...'
\echo 'WARNING: This will DELETE all graph data!'

-- ============================================================================
-- 1. Check if AGE/Graph exists
-- ============================================================================

DO $$
DECLARE
    age_exists BOOLEAN;
    graph_exists BOOLEAN;
BEGIN
    -- Check AGE extension
    SELECT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'age'
    ) INTO age_exists;

    IF NOT age_exists THEN
        RAISE NOTICE 'AGE extension not installed - nothing to rollback';
        RETURN;
    END IF;

    -- Check graph exists
    SELECT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) INTO graph_exists;

    IF NOT graph_exists THEN
        RAISE NOTICE 'Graph "nur" does not exist - nothing to drop';
    ELSE
        RAISE NOTICE 'Found graph "nur" - will be dropped';
    END IF;
END $$;

-- ============================================================================
-- 2. Drop Helper Functions
-- ============================================================================

DROP FUNCTION IF EXISTS execute_cypher_query(TEXT, TEXT) CASCADE;
DROP FUNCTION IF EXISTS get_graph_stats() CASCADE;
DROP FUNCTION IF EXISTS check_graph_health() CASCADE;

\echo 'Helper functions dropped'

-- ============================================================================
-- 3. Drop the Graph
-- ============================================================================

DO $$
BEGIN
    -- Load AGE for this operation
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;

    -- Check if graph exists
    IF EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) THEN
        -- Drop graph and all its data (cascade=true)
        PERFORM ag_catalog.drop_graph('nur', true);
        RAISE NOTICE 'Dropped graph: nur';
    ELSE
        RAISE NOTICE 'Graph "nur" does not exist';
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Failed to drop graph: % - may need manual intervention', SQLERRM;
END $$;

\echo 'Graph dropped (if existed)'

-- ============================================================================
-- 4. Optionally Drop AGE Extension
-- ============================================================================

-- Uncomment the following line ONLY if you want to completely remove AGE
-- This is NOT recommended if you plan to re-enable graph features later

-- DROP EXTENSION IF EXISTS age CASCADE;
-- \echo 'AGE extension dropped'

\echo ''
\echo '=============================================='
\echo 'V4 AGE Graph Rollback Complete'
\echo '=============================================='
\echo ''
\echo 'What was removed:'
\echo '  - Graph "nur" and all nodes/edges'
\echo '  - Helper functions (execute_cypher_query, get_graph_stats, check_graph_health)'
\echo ''
\echo 'What was preserved:'
\echo '  - AGE extension (still installed)'
\echo '  - Entity tables (entity, entity_alias, entity_mention)'
\echo '  - Event tables (event_actor, event_subject)'
\echo ''
\echo 'Next steps:'
\echo '  1. Set V4_GRAPH_ENABLED=false in your environment'
\echo '  2. Restart services'
\echo '  3. If rolling back to V3, also run: rollback_008.sql'
\echo ''
\echo 'To re-enable graph later:'
\echo '  1. Run 009_v4_age_setup.sql again'
\echo '  2. Set V4_GRAPH_ENABLED=true'
\echo '  3. Re-run graph_upsert worker to rebuild graph from entity tables'
\echo ''

COMMIT;
