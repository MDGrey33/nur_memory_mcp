-- Migration 009: Apache AGE Graph Setup
-- Enables Apache AGE extension and creates the 'nur' graph for V4 entity-event relationships.
--
-- IMPORTANT: Apache AGE must be installed in the Postgres instance.
-- For Docker: Use an AGE-enabled image or install the extension.
-- Example Docker image: apache/age:PG15-1.5.0
--
-- This migration is non-breaking - graph is a materialized index, not source of truth.

BEGIN;

-- ============================================================================
-- 1. Enable Apache AGE Extension
-- ============================================================================

-- Create the extension if not exists
-- Note: This requires AGE to be installed in the Postgres instance
CREATE EXTENSION IF NOT EXISTS age;

-- Load the AGE library (required for Cypher functions)
-- This must be run in each session that uses AGE
LOAD 'age';

-- Set search path to include ag_catalog for AGE functions
-- Note: This should also be set in postgresql.conf for persistence:
--   search_path = 'ag_catalog, "$user", public'
SET search_path = ag_catalog, "$user", public;


-- ============================================================================
-- 2. Create the 'nur' Graph
-- ============================================================================

-- Create graph if it doesn't exist
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


-- ============================================================================
-- 3. Helper Function: Safe Cypher Execution
-- ============================================================================

-- Create a helper function for executing Cypher queries from Python/SQL
-- This handles the AGE-specific query wrapper

CREATE OR REPLACE FUNCTION execute_cypher(
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
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION execute_cypher IS 'Helper for executing Cypher queries against an AGE graph';


-- ============================================================================
-- 4. Verify AGE Setup
-- ============================================================================

DO $$
DECLARE
    age_version TEXT;
    graph_exists BOOLEAN;
BEGIN
    -- Check AGE extension
    SELECT extversion INTO age_version
    FROM pg_extension
    WHERE extname = 'age';

    IF age_version IS NULL THEN
        RAISE EXCEPTION 'Apache AGE extension is not installed. Please install AGE before running this migration.';
    END IF;

    RAISE NOTICE 'Apache AGE version: %', age_version;

    -- Check graph exists
    SELECT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'nur'
    ) INTO graph_exists;

    IF NOT graph_exists THEN
        RAISE EXCEPTION 'Graph "nur" was not created successfully';
    END IF;

    RAISE NOTICE 'Graph "nur" verified successfully';
    RAISE NOTICE 'V4 AGE setup completed';
END $$;


-- ============================================================================
-- 5. Grant Permissions (for connection user)
-- ============================================================================

-- Note: Adjust the role name if using a different database user
-- GRANT USAGE ON SCHEMA ag_catalog TO events;

-- Grant access to the nur graph schema
-- When a graph is created, AGE creates a schema with the same name
DO $$
BEGIN
    -- Grant usage on the nur schema (created with the graph)
    EXECUTE 'GRANT USAGE ON SCHEMA nur TO PUBLIC';
    RAISE NOTICE 'Granted usage on schema nur to PUBLIC';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not grant permissions on nur schema: %', SQLERRM;
END $$;

COMMIT;


-- ============================================================================
-- Post-Migration Notes
-- ============================================================================
--
-- To use AGE in each session, you must:
--   1. LOAD 'age';
--   2. SET search_path = ag_catalog, "$user", public;
--
-- For persistent configuration, add to postgresql.conf:
--   shared_preload_libraries = 'age'
--   search_path = '"$user", public, ag_catalog'
--
-- Example Cypher queries after setup:
--
-- Create Entity node:
--   SELECT * FROM cypher('nur', $$
--       MERGE (e:Entity {entity_id: 'uuid-here'})
--       ON CREATE SET e.canonical_name = 'Alice Chen', e.type = 'person'
--       RETURN e
--   $$) AS (e agtype);
--
-- Create Event node:
--   SELECT * FROM cypher('nur', $$
--       MERGE (ev:Event {event_id: 'uuid-here'})
--       ON CREATE SET ev.category = 'Decision', ev.narrative = 'Team decided...'
--       RETURN ev
--   $$) AS (ev agtype);
--
-- Create ACTED_IN edge:
--   SELECT * FROM cypher('nur', $$
--       MATCH (e:Entity {entity_id: 'entity-uuid'})
--       MATCH (ev:Event {event_id: 'event-uuid'})
--       MERGE (e)-[r:ACTED_IN]->(ev)
--       ON CREATE SET r.role = 'owner'
--       RETURN r
--   $$) AS (r agtype);
--
-- 1-hop expansion query:
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
--
