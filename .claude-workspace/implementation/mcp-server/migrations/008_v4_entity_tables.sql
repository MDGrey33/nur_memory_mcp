-- Migration 008: V4 Entity Tables
-- Creates entity resolution and graph support tables for V4 features.
-- Non-breaking migration - adds new tables without modifying V3 schema.

BEGIN;

-- Ensure vector extension is available (should already exist from V3)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. entity - Canonical entity registry with embedding support
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

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for type + name lookups
CREATE INDEX IF NOT EXISTS entity_type_name_idx ON entity(entity_type, normalized_name);

-- Vector similarity index using IVFFlat for cosine similarity searches
-- lists=100 is appropriate for up to ~100K entities
CREATE INDEX IF NOT EXISTS entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);

-- Partial index for review queue
CREATE INDEX IF NOT EXISTS entity_needs_review_idx ON entity(needs_review)
    WHERE needs_review = true;

COMMENT ON TABLE entity IS 'V4 canonical entity registry with embedding-based deduplication';
COMMENT ON COLUMN entity.normalized_name IS 'Lowercase, whitespace-normalized name for exact match lookups';
COMMENT ON COLUMN entity.context_embedding IS 'Vector embedding from "{name}, {type}, {role}, {org}" for similarity search';
COMMENT ON COLUMN entity.needs_review IS 'True when entity requires manual disambiguation (uncertain merge)';


-- ============================================================================
-- 2. entity_alias - Known aliases for each entity
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

COMMENT ON TABLE entity_alias IS 'V4 known aliases per entity (e.g., "Alice Chen" -> "Alice", "A. Chen")';


-- ============================================================================
-- 3. entity_mention - Every surface form occurrence (preserves evidence trail)
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
CREATE INDEX IF NOT EXISTS entity_mention_revision_idx ON entity_mention(artifact_uid, revision_id);

COMMENT ON TABLE entity_mention IS 'V4 preserves every entity mention occurrence with character offsets';


-- ============================================================================
-- 4. event_actor - Structured actor relationships
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

COMMENT ON TABLE event_actor IS 'V4 normalized actor relationships (supplements actors_json for graph queries)';


-- ============================================================================
-- 5. event_subject - Structured subject relationships
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

COMMENT ON TABLE event_subject IS 'V4 normalized subject relationships (supplements subject_json for graph queries)';


-- ============================================================================
-- Verification
-- ============================================================================
DO $$
BEGIN
    -- Verify all tables exist
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'entity') THEN
        RAISE EXCEPTION 'entity table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'entity_alias') THEN
        RAISE EXCEPTION 'entity_alias table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'entity_mention') THEN
        RAISE EXCEPTION 'entity_mention table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'event_actor') THEN
        RAISE EXCEPTION 'event_actor table was not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'event_subject') THEN
        RAISE EXCEPTION 'event_subject table was not created';
    END IF;

    RAISE NOTICE 'V4 entity tables created successfully';
END $$;

COMMIT;
