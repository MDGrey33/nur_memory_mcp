-- MCP Memory Server V3: Database Initialization Script
-- Combines all migrations into a single idempotent init script
-- This script can be run multiple times safely

-- ============================================================================
-- SECTION 1: Enable Extensions
-- ============================================================================

-- UUID generation (built-in for Postgres 13+)
-- gen_random_uuid() is available by default

-- Enable pgcrypto for additional crypto functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

\echo 'Extensions enabled successfully'

-- ============================================================================
-- SECTION 2: artifact_revision table
-- ============================================================================

-- Immutable revision tracking for artifacts
CREATE TABLE IF NOT EXISTS artifact_revision (
    -- Composite Primary Key
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- ChromaDB Reference
    artifact_id TEXT NOT NULL,  -- Chroma ID (e.g., art_9f2c)

    -- Artifact Metadata
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('email', 'doc', 'chat', 'transcript', 'note')),
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_ts TIMESTAMPTZ NULL,

    -- Content Tracking
    content_hash TEXT NOT NULL,
    token_count INT NOT NULL,
    is_chunked BOOLEAN NOT NULL,
    chunk_count INT NOT NULL,

    -- Privacy Fields (stored, not enforced in V3)
    sensitivity TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal', 'sensitive', 'highly_sensitive')),
    visibility_scope TEXT NOT NULL DEFAULT 'me' CHECK (visibility_scope IN ('me', 'team', 'org', 'custom')),
    retention_policy TEXT NOT NULL DEFAULT 'forever' CHECK (retention_policy IN ('forever', '1y', 'until_resolved', 'custom')),

    -- Version Tracking
    is_latest BOOLEAN NOT NULL DEFAULT true,

    -- Timestamps
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Primary Key
    PRIMARY KEY (artifact_uid, revision_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_artifact_revision_uid_latest
    ON artifact_revision (artifact_uid, is_latest);

CREATE INDEX IF NOT EXISTS idx_artifact_revision_ingested
    ON artifact_revision (ingested_at DESC);

CREATE INDEX IF NOT EXISTS idx_artifact_revision_source
    ON artifact_revision (source_system, source_id);

CREATE INDEX IF NOT EXISTS idx_artifact_revision_artifact_id
    ON artifact_revision (artifact_id);

\echo 'artifact_revision table created successfully'

-- ============================================================================
-- SECTION 3: event_jobs table
-- ============================================================================

-- Async job queue for event extraction
CREATE TABLE IF NOT EXISTS event_jobs (
    -- Primary Key
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Job Metadata
    job_type TEXT NOT NULL DEFAULT 'extract_events',
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Job State
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')),
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Lock Management
    locked_at TIMESTAMPTZ NULL,
    locked_by TEXT NULL,  -- WORKER_ID

    -- Error Tracking
    last_error_code TEXT NULL,
    last_error_message TEXT NULL,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Idempotency Constraint
    UNIQUE (artifact_uid, revision_id, job_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_event_jobs_claimable
    ON event_jobs (status, next_run_at)
    WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_event_jobs_revision
    ON event_jobs (artifact_uid, revision_id);

CREATE INDEX IF NOT EXISTS idx_event_jobs_status
    ON event_jobs (status);

\echo 'event_jobs table created successfully'

-- ============================================================================
-- SECTION 4: semantic_event table
-- ============================================================================

-- Structured semantic events extracted from artifacts
CREATE TABLE IF NOT EXISTS semantic_event (
    -- Primary Key
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Artifact Reference
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Event Data
    category TEXT NOT NULL CHECK (category IN (
        'Commitment', 'Execution', 'Decision', 'Collaboration',
        'QualityRisk', 'Feedback', 'Change', 'Stakeholder'
    )),
    event_time TIMESTAMPTZ NULL,  -- Extracted from text, may be null
    narrative TEXT NOT NULL,  -- 1-2 sentence summary

    -- Structured Data (JSONB for flexibility)
    subject_json JSONB NOT NULL,  -- {"type": "person|project|...", "ref": "..."}
    actors_json JSONB NOT NULL,   -- [{"ref": "...", "role": "owner|..."}]

    -- Quality Metadata
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_run_id UUID NOT NULL,  -- Job ID for traceability

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_semantic_event_revision
    ON semantic_event (artifact_uid, revision_id);

CREATE INDEX IF NOT EXISTS idx_semantic_event_category_time
    ON semantic_event (category, event_time DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_semantic_event_extraction
    ON semantic_event (extraction_run_id);

-- Full-Text Search (Postgres FTS)
CREATE INDEX IF NOT EXISTS idx_semantic_event_narrative_fts
    ON semantic_event USING GIN (to_tsvector('english', narrative));

-- JSONB Indexes (for fast filtering)
CREATE INDEX IF NOT EXISTS idx_semantic_event_subject_type
    ON semantic_event ((subject_json->>'type'));

CREATE INDEX IF NOT EXISTS idx_semantic_event_actors
    ON semantic_event USING GIN (actors_json);

\echo 'semantic_event table created successfully'

-- ============================================================================
-- SECTION 5: event_evidence table
-- ============================================================================

-- Evidence spans linking events to source text
CREATE TABLE IF NOT EXISTS event_evidence (
    -- Primary Key
    evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Event Reference
    event_id UUID NOT NULL,

    -- Artifact Reference
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    chunk_id TEXT NULL,  -- NULL if unchunked artifact

    -- Text Span
    start_char INT NOT NULL,
    end_char INT NOT NULL,
    quote TEXT NOT NULL,  -- Max 25 words

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Foreign Key (CASCADE delete when event is deleted)
    FOREIGN KEY (event_id)
        REFERENCES semantic_event(event_id)
        ON DELETE CASCADE,

    -- Constraints
    CHECK (end_char > start_char)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_event_evidence_event
    ON event_evidence (event_id);

CREATE INDEX IF NOT EXISTS idx_event_evidence_revision
    ON event_evidence (artifact_uid, revision_id);

CREATE INDEX IF NOT EXISTS idx_event_evidence_chunk
    ON event_evidence (chunk_id)
    WHERE chunk_id IS NOT NULL;

\echo 'event_evidence table created successfully'

-- ============================================================================
-- SECTION 6: Triggers
-- ============================================================================

-- Auto-update updated_at column on event_jobs
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_event_jobs_updated_at ON event_jobs;
CREATE TRIGGER update_event_jobs_updated_at
BEFORE UPDATE ON event_jobs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

\echo 'Triggers created successfully'

-- ============================================================================
-- SECTION 7: Verify Installation
-- ============================================================================

\echo ''
\echo '========================================='
\echo 'MCP Memory Server V3 Database Initialized'
\echo '========================================='
\echo ''

-- Display table counts
SELECT
    'artifact_revision' AS table_name,
    COUNT(*) AS row_count
FROM artifact_revision
UNION ALL
SELECT
    'event_jobs' AS table_name,
    COUNT(*) AS row_count
FROM event_jobs
UNION ALL
SELECT
    'semantic_event' AS table_name,
    COUNT(*) AS row_count
FROM semantic_event
UNION ALL
SELECT
    'event_evidence' AS table_name,
    COUNT(*) AS row_count
FROM event_evidence;

\echo ''
\echo 'Database ready for use!'
\echo ''
