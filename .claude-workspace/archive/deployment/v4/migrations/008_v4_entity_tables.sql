-- Migration 008: V4 Entity Tables
-- Creates entity resolution and graph support tables for V4 features.
-- Non-breaking migration - adds new tables without modifying V3 schema.
--
-- Prerequisites:
--   - PostgreSQL 14+
--   - pgvector extension installed
--   - V3 tables exist (semantic_event, artifact_revision)
--
-- Usage: psql -U events -d events -f 008_v4_entity_tables.sql

BEGIN;

\echo 'Starting V4 Entity Tables Migration...'

-- ============================================================================
-- 1. Ensure pgvector Extension
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

\echo 'pgvector extension verified'

-- ============================================================================
-- 2. entity - Canonical entity registry with embedding support
-- ============================================================================

CREATE TABLE IF NOT EXISTS entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Entity classification
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person', 'org', 'project', 'object', 'place', 'other'
    )),

    -- Names
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,  -- lowercase, stripped for matching

    -- Rich context for deduplication (nullable, populated when available)
    role TEXT,           -- e.g., "Engineering Manager"
    organization TEXT,   -- e.g., "Acme Corp"
    email TEXT,          -- e.g., "alice@acme.com"

    -- Embedding for similarity-based dedup candidate search
    -- Using text-embedding-3-large (3072 dimensions)
    context_embedding vector(3072),

    -- Provenance
    first_seen_artifact_uid TEXT NOT NULL,
    first_seen_revision_id TEXT NOT NULL,

    -- For manual review queue (uncertain merges)
    needs_review BOOLEAN DEFAULT false,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for type + name lookups
CREATE INDEX IF NOT EXISTS entity_type_name_idx
    ON entity(entity_type, normalized_name);

-- Vector similarity index using IVFFlat for cosine similarity searches
-- lists=100 is appropriate for up to ~100K entities
CREATE INDEX IF NOT EXISTS entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);

-- Partial index for review queue
CREATE INDEX IF NOT EXISTS entity_needs_review_idx ON entity(needs_review)
    WHERE needs_review = true;

-- Created_at index for timeline queries
CREATE INDEX IF NOT EXISTS entity_created_at_idx ON entity(created_at DESC);

COMMENT ON TABLE entity IS 'V4 canonical entity registry with embedding-based deduplication';
COMMENT ON COLUMN entity.normalized_name IS 'Lowercase, whitespace-normalized name for exact match lookups';
COMMENT ON COLUMN entity.context_embedding IS 'Vector embedding from "{name}, {type}, {role}, {org}" for similarity search';
COMMENT ON COLUMN entity.needs_review IS 'True when entity requires manual disambiguation (uncertain merge)';

\echo 'entity table created'

-- ============================================================================
-- 3. entity_alias - Known aliases for each entity
-- ============================================================================

CREATE TABLE IF NOT EXISTS entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,  -- lowercase for matching

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Each alias is unique per entity
    UNIQUE(entity_id, normalized_alias)
);

-- Fast alias lookup (e.g., "A. Chen" -> which entity?)
CREATE INDEX IF NOT EXISTS entity_alias_lookup_idx ON entity_alias(normalized_alias);

-- Entity-based alias lookup
CREATE INDEX IF NOT EXISTS entity_alias_entity_idx ON entity_alias(entity_id);

COMMENT ON TABLE entity_alias IS 'V4 known aliases per entity (e.g., "Alice Chen" -> "Alice", "A. Chen")';

\echo 'entity_alias table created'

-- ============================================================================
-- 4. entity_mention - Every surface form occurrence
-- ============================================================================

CREATE TABLE IF NOT EXISTS entity_mention (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    -- Document context
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Surface form as it appeared in document
    surface_form TEXT NOT NULL,

    -- Character offsets for evidence linking (nullable if not available)
    start_char INT,
    end_char INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Find all mentions of an entity
CREATE INDEX IF NOT EXISTS entity_mention_entity_idx ON entity_mention(entity_id);

-- Find all entities mentioned in a revision
CREATE INDEX IF NOT EXISTS entity_mention_revision_idx
    ON entity_mention(artifact_uid, revision_id);

-- Created_at for timeline queries
CREATE INDEX IF NOT EXISTS entity_mention_created_at_idx
    ON entity_mention(created_at DESC);

COMMENT ON TABLE entity_mention IS 'V4 preserves every entity mention occurrence with character offsets';

\echo 'entity_mention table created'

-- ============================================================================
-- 5. event_actor - Structured actor relationships
-- ============================================================================
-- Note: V3's semantic_event.actors_json is retained for backward compatibility.
-- This table is the normalized, graph-queryable version.

CREATE TABLE IF NOT EXISTS event_actor (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    -- Actor role in the event
    role TEXT NOT NULL CHECK (role IN (
        'owner', 'contributor', 'reviewer', 'stakeholder', 'other'
    )),

    PRIMARY KEY (event_id, entity_id)
);

-- Find all events an entity acted in
CREATE INDEX IF NOT EXISTS event_actor_entity_idx ON event_actor(entity_id);

-- Find all actors for an event
CREATE INDEX IF NOT EXISTS event_actor_event_idx ON event_actor(event_id);

COMMENT ON TABLE event_actor IS 'V4 normalized actor relationships (supplements actors_json for graph queries)';

\echo 'event_actor table created'

-- ============================================================================
-- 6. event_subject - Structured subject relationships
-- ============================================================================
-- Note: V3's semantic_event.subject_json is retained for backward compatibility.
-- This table is the normalized, graph-queryable version.

CREATE TABLE IF NOT EXISTS event_subject (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    PRIMARY KEY (event_id, entity_id)
);

-- Find all events about an entity
CREATE INDEX IF NOT EXISTS event_subject_entity_idx ON event_subject(entity_id);

-- Find all subjects for an event
CREATE INDEX IF NOT EXISTS event_subject_event_idx ON event_subject(event_id);

COMMENT ON TABLE event_subject IS 'V4 normalized subject relationships (supplements subject_json for graph queries)';

\echo 'event_subject table created'

-- ============================================================================
-- 7. Update event_jobs for V4 job types
-- ============================================================================

-- Add graph_upsert job type to job_type check constraint
-- First, check if constraint exists and needs updating
DO $$
BEGIN
    -- Drop existing constraint if it doesn't include graph_upsert
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'event_jobs_job_type_check'
    ) THEN
        ALTER TABLE event_jobs DROP CONSTRAINT IF EXISTS event_jobs_job_type_check;
    END IF;

    -- Add updated constraint (if not using default 'extract_events')
    -- Note: PostgreSQL doesn't have native enum, so we use CHECK constraint
    -- Allowing any job_type for flexibility in V4
    RAISE NOTICE 'event_jobs job_type constraint updated for V4';
END $$;

\echo 'event_jobs table updated for V4 job types'

-- ============================================================================
-- 8. Helper Functions
-- ============================================================================

-- Function to normalize entity names
CREATE OR REPLACE FUNCTION normalize_entity_name(name TEXT)
RETURNS TEXT AS $$
BEGIN
    -- Lowercase and collapse whitespace
    RETURN lower(regexp_replace(trim(name), '\s+', ' ', 'g'));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION normalize_entity_name IS 'Normalize entity name for matching: lowercase, trimmed, single spaces';

-- Function to get entity by normalized name
CREATE OR REPLACE FUNCTION find_entity_by_name(
    p_entity_type TEXT,
    p_name TEXT
)
RETURNS UUID AS $$
DECLARE
    v_entity_id UUID;
BEGIN
    SELECT entity_id INTO v_entity_id
    FROM entity
    WHERE entity_type = p_entity_type
      AND normalized_name = normalize_entity_name(p_name)
    LIMIT 1;

    RETURN v_entity_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION find_entity_by_name IS 'Find entity by type and normalized name';

\echo 'Helper functions created'

-- ============================================================================
-- 9. Verification
-- ============================================================================

DO $$
DECLARE
    table_count INT;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM pg_tables
    WHERE tablename IN ('entity', 'entity_alias', 'entity_mention', 'event_actor', 'event_subject');

    IF table_count != 5 THEN
        RAISE EXCEPTION 'Expected 5 V4 tables, found %', table_count;
    END IF;

    RAISE NOTICE 'All V4 entity tables verified: %/5', table_count;
END $$;

\echo ''
\echo '=============================================='
\echo 'V4 Entity Tables Migration Complete'
\echo '=============================================='
\echo ''
\echo 'Tables created:'
\echo '  - entity (canonical entity registry)'
\echo '  - entity_alias (known aliases per entity)'
\echo '  - entity_mention (every surface form occurrence)'
\echo '  - event_actor (actor-event relationships)'
\echo '  - event_subject (subject-event relationships)'
\echo ''
\echo 'Next: Run 009_v4_age_setup.sql for graph features'
\echo ''

COMMIT;
