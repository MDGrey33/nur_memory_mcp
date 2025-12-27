-- migrations/007_source_metadata.sql
-- Add source metadata columns for authority/credibility reasoning

-- Add new columns to artifact_revision table
ALTER TABLE artifact_revision
ADD COLUMN IF NOT EXISTS document_date DATE NULL,
ADD COLUMN IF NOT EXISTS source_type TEXT NULL CHECK (source_type IS NULL OR source_type IN ('email', 'slack', 'meeting_notes', 'document', 'policy', 'contract', 'chat', 'transcript', 'wiki', 'ticket')),
ADD COLUMN IF NOT EXISTS document_status TEXT NULL CHECK (document_status IS NULL OR document_status IN ('draft', 'final', 'approved', 'superseded', 'archived')),
ADD COLUMN IF NOT EXISTS author_title TEXT NULL,
ADD COLUMN IF NOT EXISTS distribution_scope TEXT NULL CHECK (distribution_scope IS NULL OR distribution_scope IN ('private', 'team', 'department', 'company', 'public')),
ADD COLUMN IF NOT EXISTS title TEXT NULL;

-- Create index on document_date for time-based queries
CREATE INDEX IF NOT EXISTS idx_artifact_revision_document_date
    ON artifact_revision (document_date DESC NULLS LAST);

-- Create index on source_type for filtering
CREATE INDEX IF NOT EXISTS idx_artifact_revision_source_type
    ON artifact_revision (source_type);

-- Confirm migration
SELECT 'source_metadata columns added successfully' AS status;
