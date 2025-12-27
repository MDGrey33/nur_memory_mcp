-- migrations/004_semantic_event.sql
-- Create semantic_event table for structured events

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

-- Confirm table created
SELECT 'semantic_event table created successfully' AS status;
