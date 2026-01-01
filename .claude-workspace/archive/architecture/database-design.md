# Database Design: V3 Schema

**Version:** 3.0
**Date:** 2025-12-27
**Author:** Senior Architect
**Status:** Approved for Implementation

---

## Table of Contents

1. [Overview](#1-overview)
2. [Entity Relationship Diagram](#2-entity-relationship-diagram)
3. [Table Definitions](#3-table-definitions)
4. [Indexes](#4-indexes)
5. [Query Patterns](#5-query-patterns)
6. [Migration Strategy](#6-migration-strategy)

---

## 1. Overview

### 1.1 Database Technology

**PostgreSQL 16+**

**Rationale**:
- ACID guarantees for transactional writes
- Full-text search (tsvector + tsquery)
- JSONB for flexible schema (subject, actors)
- Window functions for complex queries
- Mature ecosystem with excellent tooling

### 1.2 Schema Summary

V3 introduces **4 new Postgres tables**:

| Table | Purpose | Rows (1 year) | Size (1 year) |
|-------|---------|---------------|---------------|
| `artifact_revision` | Immutable artifact versions | 365K | ~180 MB |
| `event_jobs` | Async job queue | 365K | ~180 MB |
| `semantic_event` | Structured events | 1.8M | ~1.8 GB |
| `event_evidence` | Evidence spans | 5.4M | ~1.6 GB |
| **Total** | | **7.9M** | **~3.8 GB** |

**Assumptions**: 1000 docs/day, 5 events/doc, 3 evidence spans/event

### 1.3 Key Design Principles

1. **Immutability**: Artifact revisions are never updated, only new ones inserted
2. **Composite Keys**: (artifact_uid, revision_id) allows efficient lookups and maintains history
3. **Referential Integrity**: Foreign keys with CASCADE deletes ensure consistency
4. **Denormalization**: JSONB for flexible subject/actors avoids complex joins
5. **Indexing Strategy**: Balance query performance vs. write overhead

---

## 2. Entity Relationship Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     ENTITY RELATIONSHIP DIAGRAM                     │
└────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│         artifact_revision               │
│─────────────────────────────────────────│
│ PK: (artifact_uid, revision_id)         │
│                                         │
│ • artifact_uid: TEXT                    │  Stable across revisions
│ • revision_id: TEXT                     │  Unique per content
│ • artifact_id: TEXT                     │  ChromaDB reference
│ • artifact_type: TEXT                   │
│ • source_system: TEXT                   │
│ • source_id: TEXT                       │
│ • source_ts: TIMESTAMPTZ                │
│ • content_hash: TEXT                    │
│ • token_count: INT                      │
│ • is_chunked: BOOLEAN                   │
│ • chunk_count: INT                      │
│ • sensitivity: TEXT                     │
│ • visibility_scope: TEXT                │
│ • retention_policy: TEXT                │
│ • is_latest: BOOLEAN                    │
│ • ingested_at: TIMESTAMPTZ              │
└────────────────┬────────────────────────┘
                 │
                 │ 1:N (one revision → many jobs)
                 │
                 ▼
┌─────────────────────────────────────────┐
│             event_jobs                  │
│─────────────────────────────────────────│
│ PK: job_id (UUID)                       │
│ UK: (artifact_uid, revision_id, type)   │
│                                         │
│ • job_id: UUID                          │
│ • job_type: TEXT                        │
│ • artifact_uid: TEXT ────────────┐      │
│ • revision_id: TEXT ──────────┐  │      │
│ • status: TEXT                │  │      │
│ • attempts: INT               │  │      │
│ • max_attempts: INT           │  │      │
│ • next_run_at: TIMESTAMPTZ    │  │      │
│ • locked_at: TIMESTAMPTZ      │  │      │
│ • locked_by: TEXT             │  │      │
│ • last_error_code: TEXT       │  │      │
│ • last_error_message: TEXT    │  │      │
│ • created_at: TIMESTAMPTZ     │  │      │
│ • updated_at: TIMESTAMPTZ     │  │      │
└───────────────────────────────┼──┼──────┘
                                │  │
                 ┌──────────────┘  │
                 │                 │
                 │ 1:N (one revision → many events)
                 │
                 ▼
┌─────────────────────────────────────────┐
│          semantic_event                 │
│─────────────────────────────────────────│
│ PK: event_id (UUID)                     │
│                                         │
│ • event_id: UUID                        │
│ • artifact_uid: TEXT ────────────────┼──┘
│ • revision_id: TEXT ──────────────┐  │
│ • category: TEXT                  │  │
│ • event_time: TIMESTAMPTZ         │  │
│ • narrative: TEXT (FTS indexed)   │  │
│ • subject_json: JSONB             │  │
│ • actors_json: JSONB              │  │
│ • confidence: FLOAT               │  │
│ • extraction_run_id: UUID (FK)    │  │
│ • created_at: TIMESTAMPTZ         │  │
└────────────────┬──────────────────┘  │
                 │                     │
                 │ 1:N (one event → many evidence)
                 │                     │
                 ▼                     │
┌─────────────────────────────────────────┐
│         event_evidence                  │
│─────────────────────────────────────────│
│ PK: evidence_id (UUID)                  │
│ FK: event_id → semantic_event (CASCADE) │
│                                         │
│ • evidence_id: UUID                     │
│ • event_id: UUID ───────────────┘       │
│ • artifact_uid: TEXT ────────────────┼──┘
│ • revision_id: TEXT ──────────────┐  │
│ • chunk_id: TEXT (nullable)       │  │
│ • start_char: INT                 │  │
│ • end_char: INT                   │  │
│ • quote: TEXT                     │  │
│ • created_at: TIMESTAMPTZ         │  │
└───────────────────────────────────┘  │
                                       │
                                       │
                ┌──────────────────────┘
                │
                │ References (artifact_uid, revision_id)
                │ back to artifact_revision
                │
                └─────> (Logical FK, not enforced)
```

### Relationship Summary

| Relationship | Type | Description |
|--------------|------|-------------|
| **artifact_revision → event_jobs** | 1:N | One revision can have one extraction job |
| **artifact_revision → semantic_event** | 1:N | One revision can have many events |
| **semantic_event → event_evidence** | 1:N | One event has 1+ evidence spans |
| **event_jobs → semantic_event** | 1:N | One job creates many events (via extraction_run_id) |

**Note**: Foreign keys between `event_jobs`/`semantic_event`/`event_evidence` and `artifact_revision` are **logical only** (not enforced). This allows:
- Faster writes (no FK checks)
- Flexibility for future sharding
- Manual cleanup if needed (rare)

---

## 3. Table Definitions

### 3.1 artifact_revision

**Purpose**: Track immutable versions of artifacts with content hashes for deduplication.

```sql
CREATE TABLE artifact_revision (
    -- Composite Primary Key
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- ChromaDB Reference
    artifact_id TEXT NOT NULL,  -- Chroma collection ID (e.g., art_9f2c)

    -- Artifact Metadata
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN ('email', 'doc', 'chat', 'transcript', 'note')),
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_ts TIMESTAMPTZ NULL,

    -- Content Tracking
    content_hash TEXT NOT NULL,     -- SHA256 of full content
    token_count INT NOT NULL,
    is_chunked BOOLEAN NOT NULL,
    chunk_count INT NOT NULL,

    -- Privacy Fields (stored, not enforced in V3)
    sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK (sensitivity IN ('normal', 'sensitive', 'highly_sensitive')),
    visibility_scope TEXT NOT NULL DEFAULT 'me'
        CHECK (visibility_scope IN ('me', 'team', 'org', 'custom')),
    retention_policy TEXT NOT NULL DEFAULT 'forever'
        CHECK (retention_policy IN ('forever', '1y', 'until_resolved', 'custom')),

    -- Version Tracking
    is_latest BOOLEAN NOT NULL DEFAULT true,

    -- Timestamps
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Primary Key
    PRIMARY KEY (artifact_uid, revision_id)
);
```

**ID Generation Logic**:

```python
# artifact_uid: stable across revisions
if source_id:
    artifact_uid = "uid_" + hashlib.sha256(
        f"{source_system}:{source_id}".encode()
    ).hexdigest()[:16]
else:
    # Manual ingestion without source_id
    artifact_uid = "uid_" + uuid4().hex[:16]

# revision_id: unique per content
revision_id = "rev_" + hashlib.sha256(content.encode()).hexdigest()[:16]
```

**Example Row**:

| artifact_uid | revision_id | artifact_id | artifact_type | source_system | source_id | content_hash | is_chunked | chunk_count | is_latest | ingested_at |
|--------------|-------------|-------------|---------------|---------------|-----------|--------------|------------|-------------|-----------|-------------|
| uid_9f2c1a8b | rev_4e3d2c1b | art_9f2c | doc | google_drive | doc_abc123 | sha256... | true | 5 | true | 2024-03-15 14:00:00 |

### 3.2 event_jobs

**Purpose**: Durable job queue for async event extraction.

```sql
CREATE TABLE event_jobs (
    -- Primary Key
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Job Metadata
    job_type TEXT NOT NULL DEFAULT 'extract_events',
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Job State
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')),
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
```

**State Transitions**:

```
PENDING ──┬──> PROCESSING ──┬──> DONE
          │                 │
          │                 └──> FAILED (max_attempts exceeded)
          │
          └──> PENDING (retry with backoff)
```

**Example Row**:

| job_id | artifact_uid | revision_id | status | attempts | locked_by | created_at | updated_at |
|--------|--------------|-------------|--------|----------|-----------|------------|------------|
| job_abc... | uid_9f2c... | rev_4e3d... | DONE | 1 | worker-1 | 2024-03-15 14:00:00 | 2024-03-15 14:02:30 |

### 3.3 semantic_event

**Purpose**: Store structured semantic events extracted from artifacts.

```sql
CREATE TABLE semantic_event (
    -- Primary Key
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Artifact Reference
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Event Data
    category TEXT NOT NULL
        CHECK (category IN (
            'Commitment', 'Execution', 'Decision', 'Collaboration',
            'QualityRisk', 'Feedback', 'Change', 'Stakeholder'
        )),
    event_time TIMESTAMPTZ NULL,  -- Extracted from text, may be null
    narrative TEXT NOT NULL,      -- 1-2 sentence summary

    -- Structured Data (JSONB for flexibility)
    subject_json JSONB NOT NULL,  -- {"type": "person|project|...", "ref": "..."}
    actors_json JSONB NOT NULL,   -- [{"ref": "...", "role": "owner|..."}]

    -- Quality Metadata
    confidence DOUBLE PRECISION NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_run_id UUID NOT NULL,  -- Links to event_jobs.job_id

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Event Categories**:

| Category | Description | Example Narrative |
|----------|-------------|-------------------|
| `Commitment` | Promises, deadlines, deliverables | "Alice will deliver MVP by Q1" |
| `Execution` | Actions taken, completions | "Deployed v2.3 to production" |
| `Decision` | Choices made, directions set | "Decided to use Postgres over Kafka" |
| `Collaboration` | Meetings, discussions, handoffs | "Engineering and design synced on UI" |
| `QualityRisk` | Issues, blockers, concerns | "Security audit found XSS vulnerability" |
| `Feedback` | User input, reviews, critiques | "Users reported login flow is confusing" |
| `Change` | Modifications, pivots, updates | "Changed pricing from $99 to $149" |
| `Stakeholder` | Who's involved, roles, responsibilities | "Added Bob as security reviewer" |

**JSONB Examples**:

```json
// subject_json
{
  "type": "project",
  "ref": "mcp-memory-v3"
}

// actors_json
[
  {
    "ref": "Alice Chen",
    "role": "owner"
  },
  {
    "ref": "Bob Smith",
    "role": "contributor"
  }
]
```

**Example Row**:

| event_id | artifact_uid | revision_id | category | event_time | narrative | subject_json | actors_json | confidence | extraction_run_id |
|----------|--------------|-------------|----------|------------|-----------|--------------|-------------|------------|-------------------|
| evt_abc... | uid_9f2c... | rev_4e3d... | Decision | 2024-03-15 14:30:00 | Team decided freemium pricing | {"type":"project","ref":"pricing"} | [{"ref":"Alice","role":"owner"}] | 0.95 | job_abc... |

### 3.4 event_evidence

**Purpose**: Link events to exact text spans in artifacts with quotes and character offsets.

```sql
CREATE TABLE event_evidence (
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
    quote TEXT NOT NULL,  -- Extracted quote (max 25 words)

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Foreign Key (CASCADE delete when event is deleted)
    FOREIGN KEY (event_id)
        REFERENCES semantic_event(event_id)
        ON DELETE CASCADE,

    -- Constraints
    CHECK (end_char > start_char)
);
```

**Evidence Constraints**:

1. **Quote length**: <= 25 words (enforced in application)
2. **Offset validity**: `end_char > start_char`
3. **Chunk consistency**: If `chunk_id` is set, it must exist in ChromaDB (not enforced by FK)
4. **Cascade delete**: When event is deleted, evidence is deleted automatically

**Example Row**:

| evidence_id | event_id | artifact_uid | revision_id | chunk_id | start_char | end_char | quote |
|-------------|----------|--------------|-------------|----------|------------|----------|-------|
| evi_abc... | evt_def... | uid_9f2c... | rev_4e3d... | art_9f2c::chunk::002::xyz | 1250 | 1315 | "we're going with freemium pricing model for launch" |

---

## 4. Indexes

### 4.1 artifact_revision Indexes

```sql
-- Primary key index (automatic)
CREATE UNIQUE INDEX artifact_revision_pkey
    ON artifact_revision (artifact_uid, revision_id);

-- Latest revision lookup
CREATE INDEX idx_artifact_revision_uid_latest
    ON artifact_revision (artifact_uid, is_latest);

-- Time-based queries
CREATE INDEX idx_artifact_revision_ingested
    ON artifact_revision (ingested_at DESC);

-- Source lookup for deduplication
CREATE INDEX idx_artifact_revision_source
    ON artifact_revision (source_system, source_id);

-- ChromaDB reference (rare lookups)
CREATE INDEX idx_artifact_revision_artifact_id
    ON artifact_revision (artifact_id);
```

### 4.2 event_jobs Indexes

```sql
-- Primary key index (automatic)
CREATE UNIQUE INDEX event_jobs_pkey
    ON event_jobs (job_id);

-- Idempotency constraint (automatic)
CREATE UNIQUE INDEX event_jobs_unique_revision
    ON event_jobs (artifact_uid, revision_id, job_type);

-- Job claiming (most critical index)
CREATE INDEX idx_event_jobs_claimable
    ON event_jobs (status, next_run_at)
    WHERE status = 'PENDING';  -- Partial index for efficiency

-- Revision lookup
CREATE INDEX idx_event_jobs_revision
    ON event_jobs (artifact_uid, revision_id);

-- Status monitoring
CREATE INDEX idx_event_jobs_status
    ON event_jobs (status);
```

### 4.3 semantic_event Indexes

```sql
-- Primary key index (automatic)
CREATE UNIQUE INDEX semantic_event_pkey
    ON semantic_event (event_id);

-- Revision lookup (most common query)
CREATE INDEX idx_semantic_event_revision
    ON semantic_event (artifact_uid, revision_id);

-- Category + time filtering
CREATE INDEX idx_semantic_event_category_time
    ON semantic_event (category, event_time DESC NULLS LAST);

-- Extraction run traceability
CREATE INDEX idx_semantic_event_extraction
    ON semantic_event (extraction_run_id);

-- Full-text search on narrative (GIN index)
CREATE INDEX idx_semantic_event_narrative_fts
    ON semantic_event USING GIN (to_tsvector('english', narrative));

-- JSONB indexes for fast filtering
CREATE INDEX idx_semantic_event_subject_type
    ON semantic_event ((subject_json->>'type'));

CREATE INDEX idx_semantic_event_actors
    ON semantic_event USING GIN (actors_json);
```

### 4.4 event_evidence Indexes

```sql
-- Primary key index (automatic)
CREATE UNIQUE INDEX event_evidence_pkey
    ON event_evidence (evidence_id);

-- Event lookup (most common query)
CREATE INDEX idx_event_evidence_event
    ON event_evidence (event_id);

-- Revision lookup
CREATE INDEX idx_event_evidence_revision
    ON event_evidence (artifact_uid, revision_id);

-- Chunk lookup (partial index)
CREATE INDEX idx_event_evidence_chunk
    ON event_evidence (chunk_id)
    WHERE chunk_id IS NOT NULL;
```

---

## 5. Query Patterns

### 5.1 Ingestion Queries

#### Check for Duplicate Revision

```sql
SELECT revision_id, artifact_id, is_chunked, chunk_count
FROM artifact_revision
WHERE artifact_uid = :artifact_uid
  AND revision_id = :revision_id;
```

**Index Used**: `artifact_revision_pkey`

#### Insert New Revision

```sql
BEGIN;

-- Mark old revisions as not latest
UPDATE artifact_revision
SET is_latest = false
WHERE artifact_uid = :artifact_uid
  AND is_latest = true;

-- Insert new revision
INSERT INTO artifact_revision (
    artifact_uid, revision_id, artifact_id, artifact_type,
    source_system, source_id, source_ts, content_hash,
    token_count, is_chunked, chunk_count, sensitivity,
    visibility_scope, retention_policy, is_latest
) VALUES (
    :uid, :rev, :aid, :atype, :ssys, :sid, :sts, :hash,
    :tokens, :chunked, :nchunks, :sens, :vis, :ret, true
);

COMMIT;
```

**Index Used**: `idx_artifact_revision_uid_latest`

#### Enqueue Extraction Job

```sql
INSERT INTO event_jobs (artifact_uid, revision_id, status, next_run_at)
VALUES (:uid, :rev, 'PENDING', now())
ON CONFLICT (artifact_uid, revision_id, job_type) DO NOTHING
RETURNING job_id;
```

**Index Used**: `event_jobs_unique_revision` (constraint enforcement)

### 5.2 Worker Queries

#### Claim Job (Atomic)

```sql
BEGIN;

-- Claim one job atomically
SELECT job_id, artifact_uid, revision_id, attempts
FROM event_jobs
WHERE status = 'PENDING'
  AND next_run_at <= now()
ORDER BY created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;

-- Update to PROCESSING
UPDATE event_jobs
SET status = 'PROCESSING',
    locked_at = now(),
    locked_by = :worker_id,
    attempts = attempts + 1,
    updated_at = now()
WHERE job_id = :claimed_job_id;

COMMIT;
```

**Index Used**: `idx_event_jobs_claimable` (partial index on PENDING jobs)

#### Load Artifact Revision

```sql
SELECT artifact_id, is_chunked, chunk_count
FROM artifact_revision
WHERE artifact_uid = :uid
  AND revision_id = :rev;
```

**Index Used**: `artifact_revision_pkey`

#### Write Events (Atomic Replace-on-Success)

```sql
BEGIN;

-- Delete old events for this revision
DELETE FROM semantic_event
WHERE artifact_uid = :uid AND revision_id = :rev;
-- Evidence cascades automatically via FK

-- Insert new events
INSERT INTO semantic_event (
    artifact_uid, revision_id, category, event_time,
    narrative, subject_json, actors_json, confidence,
    extraction_run_id
) VALUES (
    :uid, :rev, :category, :event_time,
    :narrative, :subject::jsonb, :actors::jsonb, :confidence, :run_id
)
RETURNING event_id;

-- Insert evidence for each event
INSERT INTO event_evidence (
    event_id, artifact_uid, revision_id, chunk_id,
    start_char, end_char, quote
) VALUES (
    :event_id, :uid, :rev, :chunk_id,
    :start_char, :end_char, :quote
);

COMMIT;
```

**Index Used**: `idx_semantic_event_revision` (for DELETE)

#### Mark Job Done

```sql
UPDATE event_jobs
SET status = 'DONE',
    updated_at = now()
WHERE job_id = :job_id;
```

**Index Used**: `event_jobs_pkey`

### 5.3 Query Queries

#### Event Search (Full-Text + Filters)

```sql
SELECT
    e.event_id,
    e.artifact_uid,
    e.revision_id,
    e.category,
    e.event_time,
    e.narrative,
    e.subject_json,
    e.actors_json,
    e.confidence
FROM semantic_event e
WHERE e.category = :category
  AND to_tsvector('english', e.narrative) @@ to_tsquery('english', :query)
  AND e.event_time >= :time_from
  AND e.event_time <= :time_to
ORDER BY e.event_time DESC NULLS LAST, e.created_at DESC
LIMIT :limit;
```

**Indexes Used**:
- `idx_semantic_event_category_time` (category filter + sort)
- `idx_semantic_event_narrative_fts` (full-text search)

#### Fetch Evidence for Event

```sql
SELECT
    ev.evidence_id,
    ev.quote,
    ev.start_char,
    ev.end_char,
    ev.chunk_id
FROM event_evidence ev
WHERE ev.event_id = :event_id
ORDER BY ev.start_char;
```

**Index Used**: `idx_event_evidence_event`

#### List Events for Revision

```sql
-- Resolve revision_id if not provided
SELECT revision_id
FROM artifact_revision
WHERE artifact_uid = :uid
  AND is_latest = true;

-- Fetch events
SELECT
    event_id,
    category,
    narrative,
    event_time,
    subject_json,
    actors_json,
    confidence
FROM semantic_event
WHERE artifact_uid = :uid
  AND revision_id = :rev
ORDER BY event_time DESC NULLS LAST, created_at DESC;
```

**Indexes Used**:
- `idx_artifact_revision_uid_latest` (resolve latest revision)
- `idx_semantic_event_revision` (fetch events)

#### Check Job Status

```sql
SELECT
    job_id,
    artifact_uid,
    revision_id,
    status,
    attempts,
    max_attempts,
    created_at,
    updated_at,
    locked_by,
    last_error_code,
    last_error_message,
    next_run_at
FROM event_jobs
WHERE artifact_uid = :uid
  AND revision_id = :rev;
```

**Index Used**: `idx_event_jobs_revision`

---

## 6. Migration Strategy

### 6.1 Migration Files

```
migrations/
├── 001_enable_uuid.sql
├── 002_artifact_revision.sql
├── 003_event_jobs.sql
├── 004_semantic_event.sql
├── 005_event_evidence.sql
└── 006_triggers.sql
```

### 6.2 Migration 001: Enable UUID Extension

```sql
-- migrations/001_enable_uuid.sql

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- Or use gen_random_uuid() which is built-in for Postgres 13+
```

### 6.3 Migration 002: artifact_revision

```sql
-- migrations/002_artifact_revision.sql

CREATE TABLE artifact_revision (
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN ('email', 'doc', 'chat', 'transcript', 'note')),
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_ts TIMESTAMPTZ NULL,
    content_hash TEXT NOT NULL,
    token_count INT NOT NULL,
    is_chunked BOOLEAN NOT NULL,
    chunk_count INT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal'
        CHECK (sensitivity IN ('normal', 'sensitive', 'highly_sensitive')),
    visibility_scope TEXT NOT NULL DEFAULT 'me'
        CHECK (visibility_scope IN ('me', 'team', 'org', 'custom')),
    retention_policy TEXT NOT NULL DEFAULT 'forever'
        CHECK (retention_policy IN ('forever', '1y', 'until_resolved', 'custom')),
    is_latest BOOLEAN NOT NULL DEFAULT true,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_uid, revision_id)
);

CREATE INDEX idx_artifact_revision_uid_latest
    ON artifact_revision (artifact_uid, is_latest);
CREATE INDEX idx_artifact_revision_ingested
    ON artifact_revision (ingested_at DESC);
CREATE INDEX idx_artifact_revision_source
    ON artifact_revision (source_system, source_id);
CREATE INDEX idx_artifact_revision_artifact_id
    ON artifact_revision (artifact_id);
```

### 6.4 Migration 003: event_jobs

```sql
-- migrations/003_event_jobs.sql

CREATE TABLE event_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL DEFAULT 'extract_events',
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')),
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ NULL,
    locked_by TEXT NULL,
    last_error_code TEXT NULL,
    last_error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (artifact_uid, revision_id, job_type)
);

CREATE INDEX idx_event_jobs_claimable
    ON event_jobs (status, next_run_at)
    WHERE status = 'PENDING';
CREATE INDEX idx_event_jobs_revision
    ON event_jobs (artifact_uid, revision_id);
CREATE INDEX idx_event_jobs_status
    ON event_jobs (status);
```

### 6.5 Migration 004: semantic_event

```sql
-- migrations/004_semantic_event.sql

CREATE TABLE semantic_event (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    category TEXT NOT NULL
        CHECK (category IN (
            'Commitment', 'Execution', 'Decision', 'Collaboration',
            'QualityRisk', 'Feedback', 'Change', 'Stakeholder'
        )),
    event_time TIMESTAMPTZ NULL,
    narrative TEXT NOT NULL,
    subject_json JSONB NOT NULL,
    actors_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_run_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_semantic_event_revision
    ON semantic_event (artifact_uid, revision_id);
CREATE INDEX idx_semantic_event_category_time
    ON semantic_event (category, event_time DESC NULLS LAST);
CREATE INDEX idx_semantic_event_extraction
    ON semantic_event (extraction_run_id);
CREATE INDEX idx_semantic_event_narrative_fts
    ON semantic_event USING GIN (to_tsvector('english', narrative));
CREATE INDEX idx_semantic_event_subject_type
    ON semantic_event ((subject_json->>'type'));
CREATE INDEX idx_semantic_event_actors
    ON semantic_event USING GIN (actors_json);
```

### 6.6 Migration 005: event_evidence

```sql
-- migrations/005_event_evidence.sql

CREATE TABLE event_evidence (
    evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL,
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    chunk_id TEXT NULL,
    start_char INT NOT NULL,
    end_char INT NOT NULL,
    quote TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (event_id)
        REFERENCES semantic_event(event_id)
        ON DELETE CASCADE,
    CHECK (end_char > start_char)
);

CREATE INDEX idx_event_evidence_event
    ON event_evidence (event_id);
CREATE INDEX idx_event_evidence_revision
    ON event_evidence (artifact_uid, revision_id);
CREATE INDEX idx_event_evidence_chunk
    ON event_evidence (chunk_id)
    WHERE chunk_id IS NOT NULL;
```

### 6.7 Migration 006: Triggers

```sql
-- migrations/006_triggers.sql

-- Auto-update updated_at column on event_jobs
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_event_jobs_updated_at
BEFORE UPDATE ON event_jobs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
```

### 6.8 Docker Compose Integration

```yaml
# docker-compose.yml

postgres:
  image: postgres:16-alpine
  container_name: postgres-events
  ports:
    - "5432:5432"
  environment:
    - POSTGRES_DB=events
    - POSTGRES_USER=events
    - POSTGRES_PASSWORD=events
  volumes:
    - postgres-data:/var/lib/postgresql/data
    - ./migrations:/docker-entrypoint-initdb.d  # Auto-run migrations on startup
  restart: unless-stopped
```

**Auto-Migration**: Files in `/docker-entrypoint-initdb.d` run alphabetically on first startup.

---

## Appendix: Query Performance Testing

### Test Data Setup

```sql
-- Generate 1M events for testing
INSERT INTO artifact_revision (artifact_uid, revision_id, artifact_id, artifact_type, source_system, source_id, content_hash, token_count, is_chunked, chunk_count)
SELECT
    'uid_' || md5(random()::text)::varchar(16),
    'rev_' || md5(random()::text)::varchar(16),
    'art_' || md5(random()::text)::varchar(8),
    (ARRAY['email', 'doc', 'chat', 'transcript', 'note'])[floor(random() * 5 + 1)],
    'test_corpus',
    'test_' || i::text,
    md5(random()::text),
    floor(random() * 10000)::int,
    random() > 0.7,
    floor(random() * 10)::int
FROM generate_series(1, 200000) i;

-- Generate 1M events
-- (Similar INSERT for semantic_event and event_evidence)
```

### Benchmark Queries

```sql
-- Query 1: Event search with full-text (expected: < 500ms)
EXPLAIN ANALYZE
SELECT * FROM semantic_event
WHERE category = 'Decision'
  AND to_tsvector('english', narrative) @@ to_tsquery('english', 'pricing')
ORDER BY event_time DESC NULLS LAST
LIMIT 20;

-- Query 2: List events for revision (expected: < 200ms)
EXPLAIN ANALYZE
SELECT * FROM semantic_event
WHERE artifact_uid = 'uid_abc123'
  AND revision_id = 'rev_def456'
ORDER BY event_time DESC;

-- Query 3: Job claiming (expected: < 50ms)
EXPLAIN ANALYZE
SELECT * FROM event_jobs
WHERE status = 'PENDING'
  AND next_run_at <= now()
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

---

**End of Database Design Document**
