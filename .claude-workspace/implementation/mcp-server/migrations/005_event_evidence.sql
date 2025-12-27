-- migrations/005_event_evidence.sql
-- Create event_evidence table for evidence spans

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

-- Confirm table created
SELECT 'event_evidence table created successfully' AS status;
