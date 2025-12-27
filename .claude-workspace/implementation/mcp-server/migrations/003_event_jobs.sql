-- migrations/003_event_jobs.sql
-- Create event_jobs table for async job queue

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

-- Confirm table created
SELECT 'event_jobs table created successfully' AS status;
