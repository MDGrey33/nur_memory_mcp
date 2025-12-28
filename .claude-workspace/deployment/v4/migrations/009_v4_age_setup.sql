-- Migration 009: Apache AGE Graph Setup
-- Enables Apache AGE extension and creates the 'nur' graph for V4 entity-event relationships.
--
-- IMPORTANT: Apache AGE must be installed in the Postgres instance.
-- For Docker: Use an AGE-enabled image (apache/age:PG16-latest or custom build)
-- For manual: See https://age.apache.org/age-manual/master/intro/setup.html
--
-- This migration is non-breaking - graph is a materialized index, not source of truth.
-- If AGE is unavailable, V4 will operate with V4_GRAPH_ENABLED=false
--
-- Prerequisites:
--   - Migration 008_v4_entity_tables.sql completed
--   - Apache AGE extension available in PostgreSQL
--
-- Usage: psql -U events -d events -f 009_v4_age_setup.sql

BEGIN;

\echo 'Starting V4 AGE Graph Setup...'

-- ============================================================================
-- 1. Check if AGE is Available
-- ============================================================================

DO $$
DECLARE
    age_available BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_available_extensions WHERE name = 'age'
    ) INTO age_available;

    IF NOT age_available THEN
        RAISE EXCEPTION 'Apache AGE extension is not available. Install AGE or use V4_GRAPH_ENABLED=false';
    END IF;

    RAISE NOTICE 'Apache AGE extension is available';
END $$;

-- ============================================================================
-- 2. Enable Apache AGE Extension
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS age;

-- Load the AGE library (required for Cypher functions)
-- This must be run in each session that uses AGE
LOAD 'age';

-- Set search path to include ag_catalog for AGE functions
SET search_path = ag_catalog, "$user", public;

\echo 'Apache AGE extension enabled'

-- ============================================================================
-- 3. Create the 'nur' Graph
-- ============================================================================

-- The graph will contain:
--   - Entity nodes (entity_id, canonical_name, type, role, organization)
--   - Event nodes (event_id, category, narrative, artifact_uid, revision_id, event_time, confidence)
--   - ACTED_IN edges (Entity -> Event) with role property
--   - ABOUT edges (Event -> Entity)
--   - POSSIBLY_SAME edges (Entity -> Entity) for uncertain merges

DO $$
BEGIN
    -- Check if graph already exists
    IF NOT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) THEN
        -- Create the graph
        PERFORM ag_catalog.create_graph('nur');
        RAISE NOTICE 'Created graph: nur';
    ELSE
        RAISE NOTICE 'Graph "nur" already exists, skipping creation';
    END IF;
END $$;

\echo 'Graph "nur" created/verified'

-- ============================================================================
-- 4. Helper Function: Safe Cypher Execution
-- ============================================================================

-- Create a helper function for executing Cypher queries
-- This handles the AGE-specific query wrapper and error handling

CREATE OR REPLACE FUNCTION execute_cypher_query(
    graph_name TEXT,
    cypher_query TEXT
)
RETURNS SETOF agtype AS $$
BEGIN
    RETURN QUERY EXECUTE format(
        'SELECT * FROM cypher(%L, $$ %s $$) AS (result agtype)',
        graph_name,
        cypher_query
    );
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Cypher query failed: % - Query: %', SQLERRM, cypher_query;
        RETURN;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION execute_cypher_query IS 'Helper for executing Cypher queries against an AGE graph with error handling';

-- ============================================================================
-- 5. Graph Statistics Function
-- ============================================================================

CREATE OR REPLACE FUNCTION get_graph_stats()
RETURNS TABLE (
    entity_count BIGINT,
    event_count BIGINT,
    acted_in_count BIGINT,
    about_count BIGINT,
    possibly_same_count BIGINT
) AS $$
DECLARE
    v_entity_count BIGINT := 0;
    v_event_count BIGINT := 0;
    v_acted_in_count BIGINT := 0;
    v_about_count BIGINT := 0;
    v_possibly_same_count BIGINT := 0;
BEGIN
    -- Load AGE for this session
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;

    -- Count Entity nodes
    BEGIN
        SELECT count INTO v_entity_count
        FROM (
            SELECT * FROM cypher('nur', $$ MATCH (e:Entity) RETURN count(e) AS count $$) AS (count agtype)
        ) sq;
    EXCEPTION WHEN OTHERS THEN
        v_entity_count := -1;
    END;

    -- Count Event nodes
    BEGIN
        SELECT count INTO v_event_count
        FROM (
            SELECT * FROM cypher('nur', $$ MATCH (ev:Event) RETURN count(ev) AS count $$) AS (count agtype)
        ) sq;
    EXCEPTION WHEN OTHERS THEN
        v_event_count := -1;
    END;

    -- Count ACTED_IN edges
    BEGIN
        SELECT count INTO v_acted_in_count
        FROM (
            SELECT * FROM cypher('nur', $$ MATCH ()-[r:ACTED_IN]->() RETURN count(r) AS count $$) AS (count agtype)
        ) sq;
    EXCEPTION WHEN OTHERS THEN
        v_acted_in_count := -1;
    END;

    -- Count ABOUT edges
    BEGIN
        SELECT count INTO v_about_count
        FROM (
            SELECT * FROM cypher('nur', $$ MATCH ()-[r:ABOUT]->() RETURN count(r) AS count $$) AS (count agtype)
        ) sq;
    EXCEPTION WHEN OTHERS THEN
        v_about_count := -1;
    END;

    -- Count POSSIBLY_SAME edges
    BEGIN
        SELECT count INTO v_possibly_same_count
        FROM (
            SELECT * FROM cypher('nur', $$ MATCH ()-[r:POSSIBLY_SAME]->() RETURN count(r) AS count $$) AS (count agtype)
        ) sq;
    EXCEPTION WHEN OTHERS THEN
        v_possibly_same_count := -1;
    END;

    RETURN QUERY SELECT v_entity_count, v_event_count, v_acted_in_count, v_about_count, v_possibly_same_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_graph_stats IS 'Return node and edge counts for the nur graph';

\echo 'Graph statistics function created'

-- ============================================================================
-- 6. Graph Health Check Function
-- ============================================================================

CREATE OR REPLACE FUNCTION check_graph_health()
RETURNS TABLE (
    status TEXT,
    age_enabled BOOLEAN,
    graph_exists BOOLEAN,
    message TEXT
) AS $$
DECLARE
    v_age_enabled BOOLEAN;
    v_graph_exists BOOLEAN;
    v_status TEXT;
    v_message TEXT;
BEGIN
    -- Check AGE extension
    SELECT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'age'
    ) INTO v_age_enabled;

    IF NOT v_age_enabled THEN
        RETURN QUERY SELECT 'unhealthy'::TEXT, false, false, 'AGE extension not installed';
        RETURN;
    END IF;

    -- Check graph exists
    SELECT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) INTO v_graph_exists;

    IF NOT v_graph_exists THEN
        RETURN QUERY SELECT 'unhealthy'::TEXT, true, false, 'Graph "nur" does not exist';
        RETURN;
    END IF;

    -- All checks passed
    RETURN QUERY SELECT 'healthy'::TEXT, true, true, 'Graph is operational';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_graph_health IS 'Health check for AGE graph availability';

\echo 'Graph health check function created'

-- ============================================================================
-- 7. Grant Permissions
-- ============================================================================

-- Grant access to the nur graph schema (created with the graph)
DO $$
BEGIN
    -- Grant usage on the nur schema
    EXECUTE 'GRANT USAGE ON SCHEMA nur TO PUBLIC';
    RAISE NOTICE 'Granted usage on schema nur to PUBLIC';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not grant permissions on nur schema: % (may be normal)', SQLERRM;
END $$;

-- Grant execute on helper functions
GRANT EXECUTE ON FUNCTION execute_cypher_query(TEXT, TEXT) TO PUBLIC;
GRANT EXECUTE ON FUNCTION get_graph_stats() TO PUBLIC;
GRANT EXECUTE ON FUNCTION check_graph_health() TO PUBLIC;

\echo 'Permissions granted'

-- ============================================================================
-- 8. Verify AGE Setup
-- ============================================================================

DO $$
DECLARE
    v_age_version TEXT;
    v_graph_exists BOOLEAN;
    v_health_status TEXT;
BEGIN
    -- Check AGE version
    SELECT extversion INTO v_age_version
    FROM pg_extension
    WHERE extname = 'age';

    IF v_age_version IS NULL THEN
        RAISE EXCEPTION 'Apache AGE extension is not installed after CREATE EXTENSION';
    END IF;

    RAISE NOTICE 'Apache AGE version: %', v_age_version;

    -- Check graph exists
    SELECT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) INTO v_graph_exists;

    IF NOT v_graph_exists THEN
        RAISE EXCEPTION 'Graph "nur" was not created successfully';
    END IF;

    -- Run health check
    SELECT status INTO v_health_status FROM check_graph_health();

    IF v_health_status != 'healthy' THEN
        RAISE WARNING 'Graph health check returned: %', v_health_status;
    END IF;

    RAISE NOTICE 'Graph "nur" verified successfully';
    RAISE NOTICE 'V4 AGE setup completed';
END $$;

\echo ''
\echo '=============================================='
\echo 'V4 AGE Graph Setup Complete'
\echo '=============================================='
\echo ''
\echo 'Graph created: nur'
\echo ''
\echo 'Node types:'
\echo '  - :Entity (entity_id, canonical_name, type, role, organization)'
\echo '  - :Event (event_id, category, narrative, artifact_uid, revision_id)'
\echo ''
\echo 'Edge types:'
\echo '  - [:ACTED_IN {role}] (Entity -> Event)'
\echo '  - [:ABOUT] (Event -> Entity)'
\echo '  - [:POSSIBLY_SAME {confidence, reason}] (Entity -> Entity)'
\echo ''
\echo 'Helper functions:'
\echo '  - execute_cypher_query(graph_name, cypher_query)'
\echo '  - get_graph_stats()'
\echo '  - check_graph_health()'
\echo ''
\echo 'To use AGE in a new session:'
\echo '  LOAD ''age'';'
\echo '  SET search_path = ag_catalog, "$user", public;'
\echo ''

COMMIT;

-- ============================================================================
-- Post-Migration: Configuration Recommendations
-- ============================================================================
-- Add to postgresql.conf for persistent AGE loading:
--   shared_preload_libraries = 'age'
--   search_path = '"$user", public, ag_catalog'
--
-- Example Cypher queries:
--
-- MERGE Entity node:
--   SELECT * FROM cypher('nur', $$
--       MERGE (e:Entity {entity_id: 'uuid-here'})
--       ON CREATE SET e.canonical_name = 'Alice Chen', e.type = 'person'
--       RETURN e
--   $$) AS (e agtype);
--
-- 1-hop expansion:
--   SELECT * FROM cypher('nur', $$
--       MATCH (seed:Event) WHERE seed.event_id IN ['uuid1', 'uuid2']
--       OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
--       OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)
--       WITH seed, collect(DISTINCT actor) + collect(DISTINCT subject) AS entities
--       UNWIND entities AS entity
--       MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)
--       WHERE NOT related.event_id IN ['uuid1', 'uuid2']
--       RETURN DISTINCT related, entity
--       LIMIT 10
--   $$) AS (related agtype, entity agtype);
