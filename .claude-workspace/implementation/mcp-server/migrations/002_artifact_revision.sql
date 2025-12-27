-- migrations/002_artifact_revision.sql
-- Create artifact_revision table for immutable revision tracking

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

-- Confirm table created
SELECT 'artifact_revision table created successfully' AS status;
