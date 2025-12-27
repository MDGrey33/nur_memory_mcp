# MCP Memory Server V3: Technical Specification
# Semantic Events System

**Version:** 3.0
**Date:** 2025-12-27
**Author:** Technical PM
**Status:** Approved for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Database Schema](#3-database-schema)
4. [New MCP Tools](#4-new-mcp-tools)
5. [Worker Specification](#5-worker-specification)
6. [LLM Prompts](#6-llm-prompts)
7. [Configuration](#7-configuration)
8. [API Contracts](#8-api-contracts)
9. [Error Handling](#9-error-handling)
10. [Testing Requirements](#10-testing-requirements)
11. [Implementation Sequence](#11-implementation-sequence)
12. [Non-Functional Requirements](#12-non-functional-requirements)

---

## 1. Executive Summary

### 1.1 What V3 Adds

V3 transforms the MCP Memory Server from a pure text retrieval system into an **intelligent semantic events platform** that extracts, structures, and makes queryable the key decisions, commitments, and activities buried in documents.

**Core Value Proposition:**
- **Artifacts remain source of truth** for full fidelity text retrieval
- **Events become queryable index** for structured "what happened" queries
- **Evidence traceability** ensures every event links back to exact text with quotes and offsets
- **Async extraction** keeps ingestion fast while ensuring reliability

### 1.2 Key Changes from V2

| Aspect | V2 | V3 |
|--------|----|----|
| **Data Model** | Artifacts only | Artifacts + Revisions + Events |
| **Extraction** | None | LLM-based event extraction |
| **Storage** | ChromaDB only | ChromaDB + Postgres |
| **Querying** | Text search only | Text + Structured events |
| **Versioning** | Replace on re-ingest | Immutable revision history |
| **Processing** | Synchronous | Async job queue |

### 1.3 Use Cases Unlocked

1. **Decision Archaeology**: "What decisions were made about the pricing model?"
2. **Commitment Tracking**: "What did Alice commit to deliver by Q1?"
3. **Feedback Analysis**: "What feedback did we receive on the new UI?"
4. **Change Detection**: "What changed between revision 1 and 2?"
5. **Stakeholder Mapping**: "Who was involved in the authentication redesign?"

### 1.4 Success Metrics

- Ingestion remains < 1s for 95% of documents
- Event extraction completes within 5 minutes for 90% of documents
- Zero partial writes (atomic guarantees)
- 100% evidence traceability (every event has valid quotes)

---

## 2. System Architecture

### 2.1 Container Architecture

V3 adds **2 new containers** to the V2 stack:

```
┌────────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE STACK                         │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐ │
│  │  mcp-server  │  │   chroma     │  │  postgres    │  │ event- │ │
│  │  (FastMCP)   │  │  (HTTP)      │  │  (DB+Queue)  │  │ worker │ │
│  │              │  │              │  │              │  │        │ │
│  │  Port: 3000  │  │  Port: 8001  │  │  Port: 5432  │  │  (N/A) │ │
│  │              │  │  (ext)       │  │              │  │        │ │
│  │              │  │  8000 (int)  │  │              │  │        │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───┬────┘ │
│         │                 │                 │              │      │
│         └─────────────────┼─────────────────┼──────────────┘      │
│                           │                 │                     │
└───────────────────────────┼─────────────────┼─────────────────────┘
                            │                 │
                            ▼                 ▼
                    ┌──────────────┐  ┌──────────────┐
                    │  ChromaDB    │  │  Postgres    │
                    │  Storage     │  │  Storage     │
                    │  (Volume)    │  │  (Volume)    │
                    └──────────────┘  └──────────────┘
```

**IMPORTANT PORT CORRECTION:**
- ChromaDB external port: **8001** (host → container)
- ChromaDB internal port: **8000** (container listens)
- V2 docs incorrectly stated 8100 - this is corrected in V3

### 2.2 Component Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                           MCP SERVER                                   │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                      Tool Layer (V2 + V3)                         │ │
│  │                                                                   │ │
│  │  V2 Tools (Unchanged):                                           │ │
│  │  • memory_store/search/list/delete                               │ │
│  │  • history_append/get                                            │ │
│  │  • artifact_ingest/search/get/delete  ← MODIFIED for V3         │ │
│  │  • hybrid_search                                                 │ │
│  │  • embedding_health                                              │ │
│  │                                                                   │ │
│  │  V3 Tools (NEW):                                                 │ │
│  │  • event_search         - Query structured events                │ │
│  │  • event_get            - Get event + evidence                   │ │
│  │  • event_list_for_revision - Events for artifact revision        │ │
│  │  • event_reextract      - Force re-extraction                    │ │
│  │  • job_status           - Check async job status                 │ │
│  │                                                                   │ │
│  └────────────────────────────┬─────────────────────────────────────┘ │
│                               │                                        │
│  ┌────────────────────────────┼─────────────────────────────────────┐ │
│  │         Service Layer      │                                      │ │
│  │                            │                                      │ │
│  │  ┌──────────────┐  ┌───────┴──────┐  ┌──────────────┐  ┌──────┐ │ │
│  │  │ Embedding    │  │ Chunking     │  │ Retrieval    │  │ PG   │ │ │
│  │  │ Service      │  │ Service      │  │ Service      │  │Client│ │ │
│  │  │ (OpenAI)     │  │ (tiktoken)   │  │ (RRF)        │  │(NEW) │ │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────┘ │ │
│  │                                                                   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                               │                                        │
│  ┌────────────────────────────┼─────────────────────────────────────┐ │
│  │         Storage Layer      │                                      │ │
│  │                            │                                      │ │
│  │  ┌──────────────┐  ┌───────┴──────┐                              │ │
│  │  │ ChromaDB     │  │ Postgres     │                              │ │
│  │  │ Client       │  │ Client       │                              │ │
│  │  │              │  │              │                              │ │
│  │  │ Collections: │  │ Tables:      │                              │ │
│  │  │ • memory     │  │ • artifact_  │                              │ │
│  │  │ • history    │  │   revision   │                              │ │
│  │  │ • artifacts  │  │ • event_jobs │                              │ │
│  │  │ • artifact_  │  │ • semantic_  │                              │ │
│  │  │   chunks     │  │   event      │                              │ │
│  │  │              │  │ • event_     │                              │ │
│  │  │              │  │   evidence   │                              │ │
│  │  └──────────────┘  └──────────────┘                              │ │
│  │                                                                   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│                        EVENT WORKER                                    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                     Worker Loop (Infinite)                        │ │
│  │                                                                   │ │
│  │  1. Poll Postgres for PENDING jobs (every POLL_INTERVAL_MS)     │ │
│  │  2. Claim job via SELECT ... FOR UPDATE SKIP LOCKED             │ │
│  │  3. Fetch artifact text from ChromaDB                            │ │
│  │  4. Call LLM for each chunk (Prompt A: extract)                  │ │
│  │  5. Call LLM for revision (Prompt B: canonicalize)               │ │
│  │  6. Write events + evidence to Postgres (atomic transaction)    │ │
│  │  7. Mark job DONE or handle failure (retry logic)                │ │
│  │                                                                   │ │
│  └────────────────────────────┬─────────────────────────────────────┘ │
│                               │                                        │
│  ┌────────────────────────────┼─────────────────────────────────────┐ │
│  │         Service Layer      │                                      │ │
│  │                            │                                      │ │
│  │  ┌──────────────┐  ┌───────┴──────┐  ┌──────────────┐           │ │
│  │  │ OpenAI Client│  │ ChromaDB     │  │ Postgres     │           │ │
│  │  │ (Extraction) │  │ Client       │  │ Client       │           │ │
│  │  │              │  │ (Read chunks)│  │ (Write events)│          │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │ │
│  │                                                                   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Data Flow: End-to-End

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INGESTION FLOW (V3)                               │
└──────────────────────────────────────────────────────────────────────┘

User calls: artifact_ingest(...)
       │
       ▼
┌──────────────────┐
│ 1. MCP Server    │
│                  │
│ • Validate input │
│ • Compute hashes │
│ • Check dups     │
│ • Chunk if needed│
│ • Generate embeds│
│ • Write to Chroma│
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. Postgres      │
│                  │
│ BEGIN TXMN:      │
│ • UPSERT         │
│   artifact_      │
│   revision       │
│ • INSERT         │
│   event_jobs     │
│   (PENDING)      │
│ COMMIT           │
└────────┬─────────┘
         │
         ▼
Return to user:
{
  "artifact_id": "art_abc123",
  "revision_id": "rev_def456",
  "is_chunked": true,
  "num_chunks": 5,
  "job_status": "PENDING"
}

═════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────┐
│                    EXTRACTION FLOW (Async)                            │
└──────────────────────────────────────────────────────────────────────┘

Event Worker (infinite loop):
       │
       ▼
┌──────────────────┐
│ 1. Poll Jobs     │
│                  │
│ SELECT * FROM    │
│ event_jobs       │
│ WHERE status =   │
│   'PENDING'      │
│ AND next_run_at  │
│   <= now()       │
│ ORDER BY         │
│   created_at     │
│ FOR UPDATE       │
│ SKIP LOCKED      │
│ LIMIT 1          │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. Claim Job     │
│                  │
│ UPDATE:          │
│ • status =       │
│   'PROCESSING'   │
│ • locked_at =    │
│   now()          │
│ • locked_by =    │
│   WORKER_ID      │
│ • attempts++     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 3. Fetch Text    │
│                  │
│ • Load artifact_ │
│   revision       │
│ • Fetch from     │
│   ChromaDB:      │
│   - If chunked:  │
│     get all      │
│     chunks       │
│   - If not:      │
│     get artifact │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 4. Extract       │
│   (Prompt A)     │
│                  │
│ For each chunk:  │
│ • Call OpenAI    │
│   with strict    │
│   JSON mode      │
│ • Parse entities │
│ • Parse events   │
│ • Validate schema│
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 5. Canonicalize  │
│   (Prompt B)     │
│                  │
│ • Aggregate all  │
│   chunk results  │
│ • Call OpenAI    │
│   with merged    │
│   context        │
│ • Dedupe events  │
│ • Merge evidence │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 6. Write Events  │
│                  │
│ BEGIN TXMN:      │
│ • DELETE old     │
│   events for     │
│   (artifact_uid, │
│    revision_id)  │
│ • INSERT new     │
│   semantic_event │
│   rows           │
│ • INSERT         │
│   event_evidence │
│   rows           │
│ COMMIT           │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 7. Mark Done     │
│                  │
│ UPDATE:          │
│ • status = 'DONE'│
│ • updated_at =   │
│   now()          │
└──────────────────┘

═════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────┐
│                      QUERY FLOW (V3)                                  │
└──────────────────────────────────────────────────────────────────────┘

User calls: event_search(query="decision about pricing", category="Decision")
       │
       ▼
┌──────────────────┐
│ 1. MCP Server    │
│                  │
│ • Validate query │
│ • Build filters  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 2. Postgres FTS  │
│                  │
│ SELECT           │
│   e.event_id,    │
│   e.category,    │
│   e.narrative,   │
│   e.subject_json,│
│   e.actors_json, │
│   e.event_time,  │
│   e.confidence   │
│ FROM             │
│   semantic_event │
│   e              │
│ WHERE            │
│   e.category =   │
│     'Decision'   │
│ AND              │
│   to_tsvector(   │
│     e.narrative  │
│   ) @@           │
│   to_tsquery(    │
│     'pricing'    │
│   )              │
│ LIMIT 20         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 3. Fetch Evidence│
│   (if requested) │
│                  │
│ For each event:  │
│ SELECT           │
│   ev.quote,      │
│   ev.start_char, │
│   ev.end_char,   │
│   ev.chunk_id    │
│ FROM             │
│   event_evidence │
│   ev             │
│ WHERE            │
│   ev.event_id =  │
│     e.event_id   │
└────────┬─────────┘
         │
         ▼
Return to user:
[
  {
    "event_id": "evt_abc123",
    "category": "Decision",
    "narrative": "Team decided to adopt freemium pricing model",
    "event_time": "2024-03-15T14:30:00Z",
    "subject": {"type": "project", "ref": "pricing-model"},
    "actors": [
      {"ref": "Alice", "role": "owner"},
      {"ref": "Bob", "role": "stakeholder"}
    ],
    "confidence": 0.95,
    "evidence": [
      {
        "quote": "we're going with freemium for launch",
        "start_char": 1250,
        "end_char": 1290,
        "chunk_id": "art_def456::chunk::002::xyz789"
      }
    ]
  }
]
```

### 2.4 Deployment (Docker Compose)

```yaml
version: '3.8'

services:
  mcp-server:
    build: .
    image: mcp-memory:v3
    container_name: mcp-server
    ports:
      - "3000:3000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_EMBED_MODEL=text-embedding-3-large
      - OPENAI_EVENT_MODEL=gpt-4-turbo-preview
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - EVENTS_DB_DSN=postgresql://events:events@postgres:5432/events
      - MCP_PORT=3000
      - LOG_LEVEL=INFO
    depends_on:
      - chroma
      - postgres
    restart: unless-stopped

  chroma:
    image: chromadb/chroma:latest
    container_name: chroma-db
    ports:
      - "8001:8000"  # External:Internal (CORRECTED from v2 docs)
    volumes:
      - chroma-data:/chroma/chroma
    environment:
      - ANONYMIZED_TELEMETRY=False
    restart: unless-stopped

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
      - ./migrations:/docker-entrypoint-initdb.d
    restart: unless-stopped

  event-worker:
    build: .
    image: mcp-memory:v3
    container_name: event-worker
    command: python -m src.worker
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_EVENT_MODEL=gpt-4-turbo-preview
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - EVENTS_DB_DSN=postgresql://events:events@postgres:5432/events
      - WORKER_ID=event-worker-1
      - POLL_INTERVAL_MS=1000
      - EVENT_MAX_ATTEMPTS=5
      - LOG_LEVEL=INFO
    depends_on:
      - chroma
      - postgres
    restart: unless-stopped

volumes:
  chroma-data:
  postgres-data:
```

---

## 3. Database Schema

### 3.1 Overview

V3 introduces **4 new Postgres tables** to manage artifact versioning, async job queue, and semantic events:

1. `artifact_revision` - Immutable artifact version records
2. `event_jobs` - Durable job queue for async extraction
3. `semantic_event` - Structured semantic events
4. `event_evidence` - Evidence spans linking events to artifact text

### 3.2 artifact_revision

**Purpose:** Track immutable revisions of artifacts with content hashes for deduplication.

**CRITICAL FIX:** This table uses `(artifact_uid, revision_id)` composite primary key. The `artifact_uid` is stable across revisions, `revision_id` is unique per revision.

```sql
CREATE TABLE artifact_revision (
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
CREATE INDEX idx_artifact_revision_uid_latest ON artifact_revision (artifact_uid, is_latest);
CREATE INDEX idx_artifact_revision_ingested ON artifact_revision (ingested_at DESC);
CREATE INDEX idx_artifact_revision_source ON artifact_revision (source_system, source_id);
CREATE INDEX idx_artifact_revision_artifact_id ON artifact_revision (artifact_id);
```

**ID Generation Logic:**

```python
# artifact_uid: stable across revisions
if source_id:
    artifact_uid = "uid_" + hashlib.sha256(
        f"{source_system}:{source_id}".encode()
    ).hexdigest()[:16]
else:
    artifact_uid = "uid_" + uuid4().hex[:16]

# revision_id: unique per revision
revision_id = "rev_" + hashlib.sha256(
    content.encode()
).hexdigest()[:16]
```

**Deduplication Rules:**

1. Same `artifact_uid` + same `content_hash` = **No-op** (return existing revision)
2. Same `artifact_uid` + different `content_hash` = **New revision** (enqueue job)
3. New `artifact_uid` = **New artifact** (enqueue job)

**Version Management:**

When inserting a new revision for existing `artifact_uid`:
```sql
-- First, mark old revisions as not latest
UPDATE artifact_revision
SET is_latest = false
WHERE artifact_uid = :artifact_uid
AND is_latest = true;

-- Then insert new revision
INSERT INTO artifact_revision (..., is_latest) VALUES (..., true);
```

### 3.3 event_jobs

**Purpose:** Durable job queue for async event extraction using Postgres as lightweight Kafka replacement.

```sql
CREATE TABLE event_jobs (
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
CREATE INDEX idx_event_jobs_claimable ON event_jobs (status, next_run_at) WHERE status = 'PENDING';
CREATE INDEX idx_event_jobs_revision ON event_jobs (artifact_uid, revision_id);
CREATE INDEX idx_event_jobs_status ON event_jobs (status);
```

**Job States:**

| State | Description |
|-------|-------------|
| `PENDING` | Job created, waiting to be claimed |
| `PROCESSING` | Job claimed by worker, extraction in progress |
| `DONE` | Extraction succeeded, events written |
| `FAILED` | Max attempts exceeded, terminal failure |

**Job Claiming (Worker):**

```sql
BEGIN;

-- Claim one job atomically
SELECT job_id, artifact_uid, revision_id
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

**Retry Logic:**

```python
# On transient failure (OpenAI 429, network timeout):
backoff_seconds = min(30 * (2 ** attempts), 600)  # Max 10 minutes
next_run_at = now() + timedelta(seconds=backoff_seconds)

UPDATE event_jobs
SET status = 'PENDING',
    next_run_at = :next_run_at,
    last_error_code = :error_code,
    last_error_message = :error_message,
    updated_at = now()
WHERE job_id = :job_id;

# On terminal failure (attempts >= max_attempts):
UPDATE event_jobs
SET status = 'FAILED',
    last_error_code = :error_code,
    last_error_message = :error_message,
    updated_at = now()
WHERE job_id = :job_id;
```

### 3.4 semantic_event

**Purpose:** Store structured semantic events extracted from artifacts.

```sql
CREATE TABLE semantic_event (
    -- Primary Key
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Artifact Reference
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Event Data
    category TEXT NOT NULL CHECK (category IN ('Commitment', 'Execution', 'Decision', 'Collaboration', 'QualityRisk', 'Feedback', 'Change', 'Stakeholder')),
    event_time TIMESTAMPTZ NULL,  -- Extracted from text, may be null
    narrative TEXT NOT NULL,  -- 1-2 sentence summary

    -- Structured Data (JSONB for flexibility)
    subject_json JSONB NOT NULL,  -- {"type": "person|project|object|other", "ref": "..."}
    actors_json JSONB NOT NULL,   -- [{"ref": "...", "role": "owner|contributor|..."}]

    -- Quality Metadata
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_run_id UUID NOT NULL,  -- Job ID for traceability

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_semantic_event_revision ON semantic_event (artifact_uid, revision_id);
CREATE INDEX idx_semantic_event_category_time ON semantic_event (category, event_time DESC NULLS LAST);
CREATE INDEX idx_semantic_event_extraction ON semantic_event (extraction_run_id);

-- Full-Text Search (Postgres FTS)
CREATE INDEX idx_semantic_event_narrative_fts ON semantic_event USING GIN (to_tsvector('english', narrative));

-- JSONB Indexes (for fast filtering)
CREATE INDEX idx_semantic_event_subject_type ON semantic_event ((subject_json->>'type'));
CREATE INDEX idx_semantic_event_actors ON semantic_event USING GIN (actors_json);
```

**Event Categories (Fixed Taxonomy):**

| Category | Description | Example |
|----------|-------------|---------|
| `Commitment` | Promises, deadlines, deliverables | "Alice will deliver MVP by Q1" |
| `Execution` | Actions taken, completions | "Deployed v2.3 to production" |
| `Decision` | Choices made, directions set | "Decided to use Postgres over Kafka" |
| `Collaboration` | Meetings, discussions, handoffs | "Engineering and design synced on UI" |
| `QualityRisk` | Issues, blockers, concerns | "Security audit found XSS vulnerability" |
| `Feedback` | User input, reviews, critiques | "Users reported login flow is confusing" |
| `Change` | Modifications, pivots, updates | "Changed pricing from $99 to $149" |
| `Stakeholder` | Who's involved, roles, responsibilities | "Added Bob as security reviewer" |

**JSONB Schema Examples:**

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
  },
  {
    "ref": "Engineering Team",
    "role": "stakeholder"
  }
]
```

### 3.5 event_evidence

**Purpose:** Link events to exact text spans in artifacts with quotes and character offsets.

**CRITICAL FIX:** This table was missing a primary key in the requirements doc. We add `evidence_id UUID PRIMARY KEY` for proper database design.

```sql
CREATE TABLE event_evidence (
    -- Primary Key (ADDED)
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

    -- Foreign Key
    FOREIGN KEY (event_id) REFERENCES semantic_event(event_id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_event_evidence_event ON event_evidence (event_id);
CREATE INDEX idx_event_evidence_revision ON event_evidence (artifact_uid, revision_id);
CREATE INDEX idx_event_evidence_chunk ON event_evidence (chunk_id) WHERE chunk_id IS NOT NULL;
```

**Evidence Constraints:**

1. **Quote length**: <= 25 words (enforced in application)
2. **Offset validity**: `end_char > start_char`
3. **Chunk consistency**: If `chunk_id` is set, it must exist in ChromaDB
4. **Cascade delete**: When event is deleted, evidence is deleted automatically

**Example Evidence:**

```json
{
  "evidence_id": "evi_abc123",
  "event_id": "evt_def456",
  "artifact_uid": "uid_9f2c1a8b",
  "revision_id": "rev_4e3d2c1b",
  "chunk_id": "art_9f2c::chunk::002::xyz789",
  "start_char": 1250,
  "end_char": 1315,
  "quote": "we're going with freemium pricing model for the initial launch phase"
}
```

### 3.6 Migration Script

```sql
-- migrations/001_v3_schema.sql

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create tables in dependency order
\i artifact_revision.sql
\i event_jobs.sql
\i semantic_event.sql
\i event_evidence.sql

-- Create update trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_event_jobs_updated_at BEFORE UPDATE
ON event_jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed data validation (optional)
INSERT INTO artifact_revision (
    artifact_uid, revision_id, artifact_id, artifact_type,
    source_system, source_id, source_ts, content_hash,
    token_count, is_chunked, chunk_count, sensitivity,
    visibility_scope, retention_policy, is_latest
) VALUES (
    'uid_test123', 'rev_test456', 'art_test789', 'note',
    'test_corpus', 'test_doc_1', now(), 'hash_test',
    100, false, 0, 'normal', 'me', 'forever', true
);
```

---

## 4. New MCP Tools

### 4.1 event_search

**Purpose:** Query structured events with filters and optional evidence.

```python
@mcp.tool()
def event_search(
    query: Optional[str] = None,
    limit: int = 20,
    category: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    artifact_uid: Optional[str] = None,
    include_evidence: bool = True
) -> dict:
    """
    Search semantic events with structured filters.

    Args:
        query: Full-text search on narrative (optional, searches all if omitted)
        limit: Maximum results (1-100, default 20)
        category: Filter by event category (Commitment, Decision, etc.)
        time_from: Filter events after this time (ISO8601)
        time_to: Filter events before this time (ISO8601)
        artifact_uid: Filter to specific artifact
        include_evidence: Include evidence quotes (default true)

    Returns:
        {
            "events": [
                {
                    "event_id": "evt_abc123",
                    "artifact_uid": "uid_def456",
                    "revision_id": "rev_ghi789",
                    "category": "Decision",
                    "event_time": "2024-03-15T14:30:00Z",
                    "narrative": "...",
                    "subject": {"type": "project", "ref": "..."},
                    "actors": [{"ref": "...", "role": "owner"}],
                    "confidence": 0.95,
                    "evidence": [  # Only if include_evidence=true
                        {
                            "quote": "...",
                            "start_char": 1250,
                            "end_char": 1290,
                            "chunk_id": "art_..."
                        }
                    ]
                }
            ],
            "total": 42,
            "filters_applied": {
                "query": "pricing",
                "category": "Decision",
                "time_from": "2024-01-01T00:00:00Z"
            }
        }
    """
```

**Implementation Details:**

```python
# Build base query
query_parts = ["SELECT e.* FROM semantic_event e WHERE 1=1"]
params = {}

# Add filters
if category:
    query_parts.append("AND e.category = :category")
    params["category"] = category

if time_from:
    query_parts.append("AND e.event_time >= :time_from")
    params["time_from"] = time_from

if time_to:
    query_parts.append("AND e.event_time <= :time_to")
    params["time_to"] = time_to

if artifact_uid:
    query_parts.append("AND e.artifact_uid = :artifact_uid")
    params["artifact_uid"] = artifact_uid

# Full-text search on narrative
if query:
    query_parts.append("AND to_tsvector('english', e.narrative) @@ to_tsquery('english', :query)")
    params["query"] = query

# Order and limit
query_parts.append("ORDER BY e.event_time DESC NULLS LAST, e.created_at DESC")
query_parts.append("LIMIT :limit")
params["limit"] = limit

# Execute
sql = " ".join(query_parts)
events = postgres_client.execute(sql, params)

# Fetch evidence if requested
if include_evidence:
    for event in events:
        event["evidence"] = postgres_client.execute(
            "SELECT quote, start_char, end_char, chunk_id FROM event_evidence WHERE event_id = :event_id",
            {"event_id": event["event_id"]}
        )

return {"events": events, "total": len(events), "filters_applied": {...}}
```

### 4.2 event_get

**Purpose:** Retrieve a single event by ID with full details including evidence.

```python
@mcp.tool()
def event_get(event_id: str) -> dict:
    """
    Get a single event by ID with all evidence.

    Args:
        event_id: Event UUID (e.g., evt_abc123)

    Returns:
        {
            "event_id": "evt_abc123",
            "artifact_uid": "uid_def456",
            "revision_id": "rev_ghi789",
            "category": "Decision",
            "event_time": "2024-03-15T14:30:00Z",
            "narrative": "Team decided to adopt freemium pricing model",
            "subject": {"type": "project", "ref": "pricing-model"},
            "actors": [
                {"ref": "Alice", "role": "owner"},
                {"ref": "Bob", "role": "stakeholder"}
            ],
            "confidence": 0.95,
            "evidence": [
                {
                    "evidence_id": "evi_jkl012",
                    "quote": "we're going with freemium for launch",
                    "start_char": 1250,
                    "end_char": 1290,
                    "chunk_id": "art_def456::chunk::002::xyz789",
                    "artifact_id": "art_def456"
                }
            ],
            "extraction_run_id": "job_mno345",
            "created_at": "2024-03-15T15:00:00Z"
        }

        Or if not found:
        {
            "error": "Event evt_abc123 not found"
        }
    """
```

**Implementation:**

```python
# Fetch event
event = postgres_client.execute(
    "SELECT * FROM semantic_event WHERE event_id = :event_id",
    {"event_id": event_id}
)

if not event:
    return {"error": f"Event {event_id} not found"}

# Fetch evidence
evidence = postgres_client.execute(
    "SELECT * FROM event_evidence WHERE event_id = :event_id ORDER BY start_char",
    {"event_id": event_id}
)

event["evidence"] = evidence
return event
```

### 4.3 event_list_for_revision

**Purpose:** List all events for a specific artifact revision (or latest if not specified).

```python
@mcp.tool()
def event_list_for_revision(
    artifact_uid: str,
    revision_id: Optional[str] = None,
    include_evidence: bool = False
) -> dict:
    """
    List all events for an artifact revision.

    Args:
        artifact_uid: Artifact UID (e.g., uid_abc123)
        revision_id: Specific revision (defaults to latest)
        include_evidence: Include evidence quotes (default false)

    Returns:
        {
            "artifact_uid": "uid_abc123",
            "revision_id": "rev_def456",
            "is_latest": true,
            "events": [
                {
                    "event_id": "evt_...",
                    "category": "Decision",
                    "narrative": "...",
                    "event_time": "2024-03-15T14:30:00Z",
                    "confidence": 0.95,
                    "evidence": [...]  # Only if include_evidence=true
                }
            ],
            "total": 7
        }

        Or if not found:
        {
            "error": "Artifact uid_abc123 not found"
        }
    """
```

**Implementation:**

```python
# Resolve revision_id if not provided
if not revision_id:
    revision_row = postgres_client.execute(
        "SELECT revision_id FROM artifact_revision WHERE artifact_uid = :uid AND is_latest = true",
        {"uid": artifact_uid}
    )
    if not revision_row:
        return {"error": f"Artifact {artifact_uid} not found"}
    revision_id = revision_row["revision_id"]

# Fetch events
events = postgres_client.execute(
    """
    SELECT event_id, category, narrative, event_time, subject_json, actors_json, confidence
    FROM semantic_event
    WHERE artifact_uid = :uid AND revision_id = :rev
    ORDER BY event_time DESC NULLS LAST, created_at DESC
    """,
    {"uid": artifact_uid, "rev": revision_id}
)

# Optionally fetch evidence
if include_evidence:
    for event in events:
        event["evidence"] = postgres_client.execute(
            "SELECT quote, start_char, end_char, chunk_id FROM event_evidence WHERE event_id = :eid",
            {"eid": event["event_id"]}
        )

return {
    "artifact_uid": artifact_uid,
    "revision_id": revision_id,
    "is_latest": is_latest,
    "events": events,
    "total": len(events)
}
```

### 4.4 event_reextract

**Purpose:** Force re-extraction of events for an artifact revision.

```python
@mcp.tool()
def event_reextract(
    artifact_uid: str,
    revision_id: Optional[str] = None,
    force: bool = False
) -> dict:
    """
    Force re-extraction of events for a revision.

    Use cases:
    - Prompt improvements (better extraction)
    - Failed extraction needs retry
    - Manual override of existing events

    Args:
        artifact_uid: Artifact UID
        revision_id: Specific revision (defaults to latest)
        force: If true, enqueue even if job already DONE (default false)

    Returns:
        {
            "job_id": "job_abc123",
            "artifact_uid": "uid_def456",
            "revision_id": "rev_ghi789",
            "status": "PENDING",
            "message": "Re-extraction job enqueued"
        }

        Or if error:
        {
            "error": "Artifact uid_abc123 not found"
        }
    """
```

**Implementation:**

```python
# Resolve revision_id if not provided
if not revision_id:
    revision_row = postgres_client.execute(
        "SELECT revision_id FROM artifact_revision WHERE artifact_uid = :uid AND is_latest = true",
        {"uid": artifact_uid}
    )
    if not revision_row:
        return {"error": f"Artifact {artifact_uid} not found"}
    revision_id = revision_row["revision_id"]

# Check existing job status
existing_job = postgres_client.execute(
    "SELECT job_id, status FROM event_jobs WHERE artifact_uid = :uid AND revision_id = :rev",
    {"uid": artifact_uid, "rev": revision_id}
)

if existing_job:
    if existing_job["status"] in ["PENDING", "PROCESSING"] and not force:
        return {
            "job_id": existing_job["job_id"],
            "status": existing_job["status"],
            "message": "Job already in progress (use force=true to override)"
        }

    if force:
        # Delete existing events and reset job
        postgres_client.execute(
            "DELETE FROM semantic_event WHERE artifact_uid = :uid AND revision_id = :rev",
            {"uid": artifact_uid, "rev": revision_id}
        )
        postgres_client.execute(
            "UPDATE event_jobs SET status = 'PENDING', attempts = 0, next_run_at = now() WHERE job_id = :jid",
            {"jid": existing_job["job_id"]}
        )
        return {
            "job_id": existing_job["job_id"],
            "status": "PENDING",
            "message": "Job reset and re-enqueued (force=true)"
        }

# Create new job
job_id = postgres_client.execute(
    """
    INSERT INTO event_jobs (artifact_uid, revision_id, status, next_run_at)
    VALUES (:uid, :rev, 'PENDING', now())
    RETURNING job_id
    """,
    {"uid": artifact_uid, "rev": revision_id}
)["job_id"]

return {
    "job_id": job_id,
    "artifact_uid": artifact_uid,
    "revision_id": revision_id,
    "status": "PENDING",
    "message": "Re-extraction job enqueued"
}
```

### 4.5 job_status

**Purpose:** Check the status of an extraction job.

```python
@mcp.tool()
def job_status(
    artifact_uid: str,
    revision_id: Optional[str] = None
) -> dict:
    """
    Check extraction job status for an artifact revision.

    Args:
        artifact_uid: Artifact UID
        revision_id: Specific revision (defaults to latest)

    Returns:
        {
            "job_id": "job_abc123",
            "artifact_uid": "uid_def456",
            "revision_id": "rev_ghi789",
            "status": "DONE",
            "attempts": 1,
            "max_attempts": 5,
            "created_at": "2024-03-15T14:00:00Z",
            "updated_at": "2024-03-15T14:02:00Z",
            "locked_by": "event-worker-1",
            "last_error_code": null,
            "last_error_message": null,
            "next_run_at": null
        }

        Possible statuses:
        - PENDING: Job not yet claimed
        - PROCESSING: Worker is extracting events
        - DONE: Extraction completed successfully
        - FAILED: Terminal failure (max attempts exceeded)

        Or if not found:
        {
            "error": "No job found for artifact uid_abc123"
        }
    """
```

**Implementation:**

```python
# Resolve revision_id if not provided
if not revision_id:
    revision_row = postgres_client.execute(
        "SELECT revision_id FROM artifact_revision WHERE artifact_uid = :uid AND is_latest = true",
        {"uid": artifact_uid}
    )
    if not revision_row:
        return {"error": f"Artifact {artifact_uid} not found"}
    revision_id = revision_row["revision_id"]

# Fetch job status
job = postgres_client.execute(
    "SELECT * FROM event_jobs WHERE artifact_uid = :uid AND revision_id = :rev",
    {"uid": artifact_uid, "rev": revision_id}
)

if not job:
    return {"error": f"No job found for artifact {artifact_uid}"}

return job
```

### 4.6 Modified Tool: artifact_ingest

**Changes from V2:**

1. Generate `artifact_uid` and `revision_id`
2. Upsert `artifact_revision` to Postgres
3. Enqueue `event_jobs` row for async extraction
4. Return `revision_id` and `job_status` in response

```python
@mcp.tool()
def artifact_ingest(
    artifact_type: str,
    source_system: str,
    content: str,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    participants: Optional[List[str]] = None,
    ts: Optional[str] = None,
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever"
) -> dict:
    """
    Ingest artifact with V3 enhancements: versioning + async event extraction.

    V3 Changes:
    - Returns artifact_uid, revision_id
    - Enqueues async job for event extraction
    - Returns job_status field
    """
```

**Modified Implementation:**

```python
# ... V2 validation and chunking logic unchanged ...

# NEW: Generate artifact_uid (stable) and revision_id (per content)
if source_id:
    artifact_uid = "uid_" + hashlib.sha256(
        f"{source_system}:{source_id}".encode()
    ).hexdigest()[:16]
else:
    artifact_uid = "uid_" + uuid4().hex[:16]

revision_id = "rev_" + hashlib.sha256(content.encode()).hexdigest()[:16]

# NEW: Check for duplicate revision
existing_revision = postgres_client.execute(
    "SELECT revision_id FROM artifact_revision WHERE artifact_uid = :uid AND revision_id = :rev",
    {"uid": artifact_uid, "rev": revision_id}
)

if existing_revision:
    # Same content hash - no-op
    return {
        "artifact_id": artifact_id,
        "artifact_uid": artifact_uid,
        "revision_id": revision_id,
        "is_chunked": is_chunked,
        "num_chunks": num_chunks,
        "status": "unchanged",
        "job_status": "N/A"
    }

# ... V2 ChromaDB write logic unchanged ...

# NEW: Write to Postgres
postgres_client.execute(
    """
    -- Mark old revisions as not latest
    UPDATE artifact_revision SET is_latest = false
    WHERE artifact_uid = :uid AND is_latest = true;

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
    """,
    {
        "uid": artifact_uid,
        "rev": revision_id,
        "aid": artifact_id,
        "atype": artifact_type,
        "ssys": source_system,
        "sid": source_id or "",
        "sts": ts,
        "hash": content_hash,
        "tokens": token_count,
        "chunked": is_chunked,
        "nchunks": num_chunks,
        "sens": sensitivity,
        "vis": visibility_scope,
        "ret": retention_policy
    }
)

# NEW: Enqueue extraction job
job_id = postgres_client.execute(
    """
    INSERT INTO event_jobs (artifact_uid, revision_id, status, next_run_at)
    VALUES (:uid, :rev, 'PENDING', now())
    ON CONFLICT (artifact_uid, revision_id, job_type) DO NOTHING
    RETURNING job_id
    """,
    {"uid": artifact_uid, "rev": revision_id}
)

return {
    "artifact_id": artifact_id,
    "artifact_uid": artifact_uid,
    "revision_id": revision_id,
    "is_chunked": is_chunked,
    "num_chunks": num_chunks,
    "stored_ids": stored_ids,
    "job_id": job_id["job_id"] if job_id else None,
    "job_status": "PENDING"
}
```

---

## 5. Worker Specification

### 5.1 Worker Architecture

```python
# src/worker.py

import os
import time
import logging
from typing import List, Dict
from datetime import datetime, timedelta

from storage.postgres_client import PostgresClient
from storage.chroma_client import ChromaClientManager
from services.embedding_service import EmbeddingService
from services.extraction_service import ExtractionService  # NEW

logger = logging.getLogger("event-worker")

class EventWorker:
    """
    Async worker that claims extraction jobs and processes them.
    """

    def __init__(
        self,
        postgres_client: PostgresClient,
        chroma_client: ChromaClientManager,
        extraction_service: ExtractionService,
        worker_id: str,
        poll_interval_ms: int = 1000,
        max_attempts: int = 5
    ):
        self.postgres = postgres_client
        self.chroma = chroma_client
        self.extraction = extraction_service
        self.worker_id = worker_id
        self.poll_interval = poll_interval_ms / 1000.0  # Convert to seconds
        self.max_attempts = max_attempts

    def run(self):
        """Main worker loop."""
        logger.info(f"Worker {self.worker_id} started (poll interval: {self.poll_interval}s)")

        while True:
            try:
                # Claim a job
                job = self.claim_job()

                if job:
                    logger.info(f"Claimed job {job['job_id']} for {job['artifact_uid']}/{job['revision_id']}")
                    self.process_job(job)
                else:
                    # No jobs available, sleep
                    time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Worker shutting down...")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(self.poll_interval)

    def claim_job(self) -> Dict:
        """Claim one pending job atomically."""
        return self.postgres.execute_transaction([
            {
                "sql": """
                    SELECT job_id, artifact_uid, revision_id, attempts
                    FROM event_jobs
                    WHERE status = 'PENDING'
                      AND next_run_at <= now()
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                """,
                "fetch": "one"
            },
            {
                "sql": """
                    UPDATE event_jobs
                    SET status = 'PROCESSING',
                        locked_at = now(),
                        locked_by = :worker_id,
                        attempts = attempts + 1,
                        updated_at = now()
                    WHERE job_id = :job_id
                """,
                "params": lambda results: {
                    "worker_id": self.worker_id,
                    "job_id": results[0]["job_id"] if results[0] else None
                }
            }
        ])

    def process_job(self, job: Dict):
        """Process a single extraction job."""
        job_id = job["job_id"]
        artifact_uid = job["artifact_uid"]
        revision_id = job["revision_id"]
        attempts = job["attempts"]

        try:
            # Step 1: Load artifact revision
            revision = self.load_artifact_revision(artifact_uid, revision_id)

            # Step 2: Fetch text from ChromaDB
            text_chunks = self.fetch_artifact_text(revision)

            # Step 3: Extract events from each chunk (Prompt A)
            chunk_extractions = []
            for chunk in text_chunks:
                extraction = self.extraction.extract_from_chunk(chunk)
                chunk_extractions.append(extraction)

            # Step 4: Canonicalize across revision (Prompt B)
            canonical_events = self.extraction.canonicalize_events(chunk_extractions)

            # Step 5: Write events + evidence to Postgres (atomic)
            self.write_events(artifact_uid, revision_id, canonical_events, job_id)

            # Step 6: Mark job DONE
            self.mark_job_done(job_id)

            logger.info(f"Job {job_id} completed: {len(canonical_events)} events extracted")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            self.handle_job_failure(job_id, attempts, str(e))

    def load_artifact_revision(self, artifact_uid: str, revision_id: str) -> Dict:
        """Load artifact revision metadata from Postgres."""
        revision = self.postgres.execute(
            "SELECT * FROM artifact_revision WHERE artifact_uid = :uid AND revision_id = :rev",
            {"uid": artifact_uid, "rev": revision_id}
        )
        if not revision:
            raise ValueError(f"Artifact revision {artifact_uid}/{revision_id} not found")
        return revision

    def fetch_artifact_text(self, revision: Dict) -> List[Dict]:
        """Fetch artifact text or chunks from ChromaDB."""
        artifact_id = revision["artifact_id"]
        is_chunked = revision["is_chunked"]

        if not is_chunked:
            # Fetch single artifact
            result = self.chroma.get_artifacts_collection().get(ids=[artifact_id])
            if not result or not result["documents"]:
                raise ValueError(f"Artifact {artifact_id} not found in ChromaDB")
            return [{
                "chunk_id": None,
                "chunk_index": 0,
                "content": result["documents"][0],
                "start_char": 0,
                "end_char": len(result["documents"][0])
            }]
        else:
            # Fetch all chunks
            chunks = self.chroma.get_artifact_chunks_collection().get(
                where={"artifact_id": artifact_id}
            )
            if not chunks or not chunks["documents"]:
                raise ValueError(f"No chunks found for artifact {artifact_id}")

            # Sort by chunk_index
            chunk_data = []
            for i in range(len(chunks["ids"])):
                chunk_data.append({
                    "chunk_id": chunks["ids"][i],
                    "chunk_index": chunks["metadatas"][i]["chunk_index"],
                    "content": chunks["documents"][i],
                    "start_char": chunks["metadatas"][i]["start_char"],
                    "end_char": chunks["metadatas"][i]["end_char"]
                })
            chunk_data.sort(key=lambda x: x["chunk_index"])
            return chunk_data

    def write_events(self, artifact_uid: str, revision_id: str, events: List[Dict], job_id: str):
        """Write canonical events + evidence to Postgres atomically."""

        # Begin transaction
        with self.postgres.transaction():
            # Delete old events for this revision (replace-on-success)
            self.postgres.execute(
                "DELETE FROM semantic_event WHERE artifact_uid = :uid AND revision_id = :rev",
                {"uid": artifact_uid, "rev": revision_id}
            )

            # Insert new events
            for event in events:
                event_id = self.postgres.execute(
                    """
                    INSERT INTO semantic_event (
                        artifact_uid, revision_id, category, event_time,
                        narrative, subject_json, actors_json, confidence,
                        extraction_run_id
                    ) VALUES (
                        :uid, :rev, :category, :event_time,
                        :narrative, :subject, :actors, :confidence, :run_id
                    )
                    RETURNING event_id
                    """,
                    {
                        "uid": artifact_uid,
                        "rev": revision_id,
                        "category": event["category"],
                        "event_time": event.get("event_time"),
                        "narrative": event["narrative"],
                        "subject": event["subject"],
                        "actors": event["actors"],
                        "confidence": event["confidence"],
                        "run_id": job_id
                    }
                )["event_id"]

                # Insert evidence for this event
                for evidence in event["evidence_list"]:
                    self.postgres.execute(
                        """
                        INSERT INTO event_evidence (
                            event_id, artifact_uid, revision_id, chunk_id,
                            start_char, end_char, quote
                        ) VALUES (
                            :event_id, :uid, :rev, :chunk_id,
                            :start_char, :end_char, :quote
                        )
                        """,
                        {
                            "event_id": event_id,
                            "uid": artifact_uid,
                            "rev": revision_id,
                            "chunk_id": evidence.get("chunk_id"),
                            "start_char": evidence["start_char"],
                            "end_char": evidence["end_char"],
                            "quote": evidence["quote"]
                        }
                    )

    def mark_job_done(self, job_id: str):
        """Mark job as DONE."""
        self.postgres.execute(
            "UPDATE event_jobs SET status = 'DONE', updated_at = now() WHERE job_id = :jid",
            {"jid": job_id}
        )

    def handle_job_failure(self, job_id: str, attempts: int, error_message: str):
        """Handle job failure with retry logic."""
        if attempts >= self.max_attempts:
            # Terminal failure
            self.postgres.execute(
                """
                UPDATE event_jobs
                SET status = 'FAILED',
                    last_error_code = 'MAX_ATTEMPTS_EXCEEDED',
                    last_error_message = :error,
                    updated_at = now()
                WHERE job_id = :jid
                """,
                {"jid": job_id, "error": error_message}
            )
            logger.error(f"Job {job_id} failed terminally after {attempts} attempts")
        else:
            # Retry with exponential backoff
            backoff_seconds = min(30 * (2 ** attempts), 600)  # Max 10 minutes
            next_run_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)

            self.postgres.execute(
                """
                UPDATE event_jobs
                SET status = 'PENDING',
                    next_run_at = :next_run,
                    last_error_code = 'TRANSIENT_FAILURE',
                    last_error_message = :error,
                    updated_at = now()
                WHERE job_id = :jid
                """,
                {"jid": job_id, "next_run": next_run_at, "error": error_message}
            )
            logger.warning(f"Job {job_id} failed, retrying in {backoff_seconds}s (attempt {attempts}/{self.max_attempts})")


if __name__ == "__main__":
    # Initialize services
    postgres_client = PostgresClient(os.getenv("EVENTS_DB_DSN"))
    chroma_manager = ChromaClientManager(
        host=os.getenv("CHROMA_HOST", "localhost"),
        port=int(os.getenv("CHROMA_PORT", "8000"))
    )
    extraction_service = ExtractionService(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_EVENT_MODEL", "gpt-4-turbo-preview")
    )

    # Create and run worker
    worker = EventWorker(
        postgres_client=postgres_client,
        chroma_client=chroma_manager,
        extraction_service=extraction_service,
        worker_id=os.getenv("WORKER_ID", "event-worker-1"),
        poll_interval_ms=int(os.getenv("POLL_INTERVAL_MS", "1000")),
        max_attempts=int(os.getenv("EVENT_MAX_ATTEMPTS", "5"))
    )

    worker.run()
```

### 5.2 Extraction Service

```python
# src/services/extraction_service.py

import json
import logging
from typing import List, Dict
from openai import OpenAI

logger = logging.getLogger("extraction-service")

class ExtractionService:
    """
    LLM-based event extraction using strict JSON mode.
    """

    def __init__(self, openai_api_key: str, model: str = "gpt-4-turbo-preview"):
        self.client = OpenAI(api_key=openai_api_key)
        self.model = model

    def extract_from_chunk(self, chunk: Dict) -> Dict:
        """
        Extract entities and events from a single chunk (Prompt A).

        Args:
            chunk: {
                "chunk_id": str,
                "chunk_index": int,
                "content": str,
                "start_char": int,
                "end_char": int
            }

        Returns:
            {
                "chunk_id": str,
                "entities": [...],
                "events": [...]
            }
        """
        prompt = self._build_prompt_a(chunk["content"])

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a semantic event extraction assistant. Extract only what is directly supported by the text."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )

        result = json.loads(response.choices[0].message.content)
        result["chunk_id"] = chunk["chunk_id"]
        result["chunk_start_char"] = chunk["start_char"]

        return result

    def canonicalize_events(self, chunk_extractions: List[Dict]) -> List[Dict]:
        """
        Canonicalize events across all chunks (Prompt B).

        Args:
            chunk_extractions: List of chunk extraction results

        Returns:
            List of canonical events with evidence_list
        """
        prompt = self._build_prompt_b(chunk_extractions)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a semantic event canonicalization assistant. Merge duplicate events conservatively."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )

        result = json.loads(response.choices[0].message.content)
        return result["canonical_events"]

    def _build_prompt_a(self, chunk_text: str) -> str:
        """Build Prompt A (extract) - see section 6.1 for full text."""
        # Full prompt in section 6.1
        return PROMPT_A_TEMPLATE.format(chunk_text=chunk_text)

    def _build_prompt_b(self, chunk_extractions: List[Dict]) -> str:
        """Build Prompt B (canonicalize) - see section 6.2 for full text."""
        # Full prompt in section 6.2
        return PROMPT_B_TEMPLATE.format(
            chunk_extractions=json.dumps(chunk_extractions, indent=2)
        )
```

---

## 6. LLM Prompts

### 6.1 Prompt A: Extract (Per Chunk)

```
You are a semantic event extraction assistant. Your task is to extract entities and semantic events from a text chunk.

RULES:
1. Only extract what is DIRECTLY SUPPORTED by the text. Do not infer or assume.
2. Evidence quotes must be <= 25 words.
3. Evidence offsets are character positions (0-indexed) within this chunk.
4. Output ONLY valid JSON, no markdown fences or explanations.

INPUT TEXT:
---
{chunk_text}
---

OUTPUT SCHEMA:
{
  "entities": [
    {
      "name": "Alice Chen",
      "type": "person|org|project|object|place|time",
      "aliases": ["Alice", "A Chen"]
    }
  ],
  "events": [
    {
      "category": "Commitment|Execution|Decision|Collaboration|QualityRisk|Feedback|Change|Stakeholder",
      "subject": {
        "type": "person|project|object|other",
        "ref": "pricing-model-v3"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner|contributor|reviewer|stakeholder|other"
        }
      ],
      "event_time": "2024-03-15T14:30:00Z or null",
      "narrative": "1-2 sentence summary of what happened",
      "evidence": {
        "quote": "exact quote from text, max 25 words",
        "start_char": 0,
        "end_char": 100
      },
      "confidence": 0.0-1.0
    }
  ]
}

EVENT CATEGORIES:
- Commitment: Promises, deadlines, deliverables
- Execution: Actions taken, completions
- Decision: Choices made, directions set
- Collaboration: Meetings, discussions, handoffs
- QualityRisk: Issues, blockers, concerns
- Feedback: User input, reviews, critiques
- Change: Modifications, pivots, updates
- Stakeholder: Who's involved, roles, responsibilities

EXTRACT CONSERVATIVELY. Better to miss an event than to hallucinate one.
```

### 6.2 Prompt B: Canonicalize (Per Revision)

```
You are a semantic event canonicalization assistant. Your task is to merge duplicate events across multiple chunks and produce a canonical list.

RULES:
1. DO NOT invent new events. Only work with events from the input.
2. Merge events conservatively: only merge if they clearly describe the SAME occurrence.
3. When merging, combine evidence lists from all source events.
4. Preserve the most detailed narrative.
5. Aggregate actors from all merged events (deduplicate by ref).
6. Output ONLY valid JSON, no markdown fences or explanations.

INPUT CHUNK EXTRACTIONS:
---
{chunk_extractions}
---

OUTPUT SCHEMA:
{
  "canonical_events": [
    {
      "category": "Decision",
      "subject": {
        "type": "project",
        "ref": "pricing-model-v3"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner"
        },
        {
          "ref": "Bob Smith",
          "role": "contributor"
        }
      ],
      "event_time": "2024-03-15T14:30:00Z or null",
      "narrative": "Team decided to adopt freemium pricing model for initial launch",
      "evidence_list": [
        {
          "chunk_id": "art_abc::chunk::002::xyz",
          "quote": "we're going with freemium for launch",
          "start_char": 1250,
          "end_char": 1290
        },
        {
          "chunk_id": "art_abc::chunk::003::xyz",
          "quote": "freemium pricing model approved by leadership",
          "start_char": 50,
          "end_char": 95
        }
      ],
      "confidence": 0.95
    }
  ]
}

MERGE CONSERVATIVELY. When in doubt, keep events separate.
```

---

## 7. Configuration

### 7.1 Environment Variables

**Existing V2 Variables (Unchanged):**

```bash
# OpenAI Embeddings
OPENAI_API_KEY=sk-...
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_EMBED_DIMS=3072
OPENAI_TIMEOUT=30
OPENAI_MAX_RETRIES=3
OPENAI_BATCH_SIZE=100

# ChromaDB
CHROMA_HOST=chroma
CHROMA_PORT=8000  # CORRECTED from 8100 in v2 docs

# Chunking
SINGLE_PIECE_MAX_TOKENS=1200
CHUNK_TARGET_TOKENS=900
CHUNK_OVERLAP_TOKENS=100

# Server
MCP_PORT=3000
LOG_LEVEL=INFO

# RRF
RRF_CONSTANT=60
```

**New V3 Variables:**

```bash
# Postgres Event DB
EVENTS_DB_DSN=postgresql://events:events@postgres:5432/events

# Worker Configuration
WORKER_ID=event-worker-1
POLL_INTERVAL_MS=1000
EVENT_MAX_ATTEMPTS=5

# Event Extraction Model
OPENAI_EVENT_MODEL=gpt-4-turbo-preview
# Alternatives: gpt-4o, gpt-4-turbo, gpt-4
```

### 7.2 Updated config.py

```python
# src/config.py

import os
from dataclasses import dataclass

@dataclass
class Config:
    """V3 Configuration with Postgres and Worker settings."""

    # V2 Fields (unchanged)
    openai_api_key: str
    openai_embed_model: str
    openai_embed_dims: int
    openai_timeout: int
    openai_max_retries: int
    openai_batch_size: int
    single_piece_max_tokens: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    chroma_host: str
    chroma_port: int
    mcp_port: int
    log_level: str
    rrf_constant: int

    # V3 NEW Fields
    events_db_dsn: str
    worker_id: str
    poll_interval_ms: int
    event_max_attempts: int
    openai_event_model: str


def load_config() -> Config:
    """Load V3 configuration from environment."""

    # Required
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")

    events_db_dsn = os.getenv("EVENTS_DB_DSN")
    if not events_db_dsn:
        raise ValueError("EVENTS_DB_DSN is required")

    return Config(
        # V2 fields
        openai_api_key=openai_api_key,
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
        openai_embed_dims=int(os.getenv("OPENAI_EMBED_DIMS", "3072")),
        openai_timeout=int(os.getenv("OPENAI_TIMEOUT", "30")),
        openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
        openai_batch_size=int(os.getenv("OPENAI_BATCH_SIZE", "100")),
        single_piece_max_tokens=int(os.getenv("SINGLE_PIECE_MAX_TOKENS", "1200")),
        chunk_target_tokens=int(os.getenv("CHUNK_TARGET_TOKENS", "900")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "100")),
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),  # CORRECTED
        mcp_port=int(os.getenv("MCP_PORT", "3000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        rrf_constant=int(os.getenv("RRF_CONSTANT", "60")),

        # V3 fields
        events_db_dsn=events_db_dsn,
        worker_id=os.getenv("WORKER_ID", "event-worker-1"),
        poll_interval_ms=int(os.getenv("POLL_INTERVAL_MS", "1000")),
        event_max_attempts=int(os.getenv("EVENT_MAX_ATTEMPTS", "5")),
        openai_event_model=os.getenv("OPENAI_EVENT_MODEL", "gpt-4-turbo-preview")
    )
```

---

## 8. API Contracts

### 8.1 Event Search Request/Response

**Request:**

```json
{
  "query": "decision about pricing",
  "limit": 20,
  "category": "Decision",
  "time_from": "2024-01-01T00:00:00Z",
  "time_to": "2024-12-31T23:59:59Z",
  "artifact_uid": "uid_abc123",
  "include_evidence": true
}
```

**Response (Success):**

```json
{
  "events": [
    {
      "event_id": "evt_abc123",
      "artifact_uid": "uid_def456",
      "revision_id": "rev_ghi789",
      "category": "Decision",
      "event_time": "2024-03-15T14:30:00Z",
      "narrative": "Team decided to adopt freemium pricing model for initial launch",
      "subject": {
        "type": "project",
        "ref": "pricing-model-v3"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner"
        },
        {
          "ref": "Bob Smith",
          "role": "contributor"
        }
      ],
      "confidence": 0.95,
      "evidence": [
        {
          "quote": "we're going with freemium for launch",
          "start_char": 1250,
          "end_char": 1290,
          "chunk_id": "art_def456::chunk::002::xyz789"
        }
      ]
    }
  ],
  "total": 1,
  "filters_applied": {
    "query": "decision about pricing",
    "category": "Decision",
    "time_from": "2024-01-01T00:00:00Z"
  }
}
```

**Response (Error):**

```json
{
  "error": "Invalid category: InvalidCategory. Must be one of: Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder"
}
```

### 8.2 Job Status Request/Response

**Request:**

```json
{
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456"
}
```

**Response (PENDING):**

```json
{
  "job_id": "job_abc123",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PENDING",
  "attempts": 0,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:00:00Z",
  "locked_by": null,
  "last_error_code": null,
  "last_error_message": null,
  "next_run_at": "2024-03-15T14:00:00Z"
}
```

**Response (PROCESSING):**

```json
{
  "job_id": "job_abc123",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PROCESSING",
  "attempts": 1,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:01:00Z",
  "locked_by": "event-worker-1",
  "locked_at": "2024-03-15T14:01:00Z",
  "last_error_code": null,
  "last_error_message": null,
  "next_run_at": null
}
```

**Response (DONE):**

```json
{
  "job_id": "job_abc123",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "DONE",
  "attempts": 1,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:02:30Z",
  "locked_by": "event-worker-1",
  "last_error_code": null,
  "last_error_message": null,
  "next_run_at": null
}
```

**Response (FAILED):**

```json
{
  "job_id": "job_abc123",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "FAILED",
  "attempts": 5,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:10:00Z",
  "locked_by": "event-worker-1",
  "last_error_code": "MAX_ATTEMPTS_EXCEEDED",
  "last_error_message": "OpenAI API rate limit exceeded after 5 attempts",
  "next_run_at": null
}
```

### 8.3 Artifact Ingest Response (V3)

**Response:**

```json
{
  "artifact_id": "art_abc123",
  "artifact_uid": "uid_def456",
  "revision_id": "rev_ghi789",
  "is_chunked": true,
  "num_chunks": 5,
  "stored_ids": [
    "art_abc123",
    "art_abc123::chunk::000::xyz",
    "art_abc123::chunk::001::abc",
    "art_abc123::chunk::002::def",
    "art_abc123::chunk::003::ghi",
    "art_abc123::chunk::004::jkl"
  ],
  "job_id": "job_mno345",
  "job_status": "PENDING"
}
```

---

## 9. Error Handling

### 9.1 Error Categories

| Error Code | Description | Retry? | User Action |
|------------|-------------|--------|-------------|
| `OPENAI_RATE_LIMIT` | OpenAI 429 rate limit | Yes | Wait for backoff |
| `OPENAI_TIMEOUT` | OpenAI API timeout | Yes | Wait for backoff |
| `OPENAI_INVALID_MODEL` | Invalid model name | No | Fix config |
| `CHROMA_CONNECTION_ERROR` | ChromaDB unreachable | Yes | Check Chroma container |
| `POSTGRES_CONNECTION_ERROR` | Postgres unreachable | Yes | Check Postgres container |
| `ARTIFACT_NOT_FOUND` | Artifact missing in Chroma | No | Re-ingest artifact |
| `INVALID_JSON_SCHEMA` | LLM returned invalid JSON | Yes | Retry with same prompt |
| `MAX_ATTEMPTS_EXCEEDED` | Job failed after 5 attempts | No | Manual intervention |

### 9.2 Retry Policy

```python
def calculate_backoff(attempts: int) -> int:
    """
    Exponential backoff with cap.

    Attempt 1: 30s
    Attempt 2: 60s
    Attempt 3: 120s
    Attempt 4: 240s
    Attempt 5: 480s (capped at 600s = 10min)
    """
    backoff_seconds = min(30 * (2 ** (attempts - 1)), 600)
    return backoff_seconds
```

### 9.3 Error Response Format

**Standard Error Response:**

```json
{
  "error": "Human-readable error message",
  "error_code": "ERROR_CODE_CONSTANT",
  "details": {
    "field": "additional context"
  }
}
```

**Examples:**

```json
// Validation error
{
  "error": "Invalid category: BadCategory. Must be one of: Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder",
  "error_code": "VALIDATION_ERROR"
}

// Not found error
{
  "error": "Event evt_nonexistent not found",
  "error_code": "NOT_FOUND"
}

// Job failure error
{
  "error": "Extraction job failed after 5 attempts",
  "error_code": "MAX_ATTEMPTS_EXCEEDED",
  "details": {
    "job_id": "job_abc123",
    "last_error": "OpenAI API rate limit exceeded"
  }
}
```

### 9.4 Atomic Transaction Guarantees

**V3 provides these atomicity guarantees:**

1. **Ingestion**: Artifact + revision + job are written atomically to Postgres
2. **Event Extraction**: All events + evidence for a revision are written in one transaction
3. **Replace-on-Success**: Old events are deleted and new events inserted atomically

**Transaction Boundaries:**

```python
# Ingestion (mcp-server)
with postgres_client.transaction():
    # Update is_latest flags
    # Insert artifact_revision
    # Insert event_jobs

# Extraction (event-worker)
with postgres_client.transaction():
    # Delete old events
    # Insert new events
    # Insert evidence
```

**No Partial Writes:**

- If embedding generation fails → No ChromaDB write, no Postgres write
- If Chroma write fails → No Postgres write
- If event extraction fails → No event write, job marked for retry
- If transaction rollback → Database state unchanged

---

## 10. Testing Requirements

### 10.1 Unit Tests

**Database Layer:**

```python
# tests/unit/test_postgres_client.py

def test_artifact_revision_insert():
    """Test artifact_revision row insertion."""
    # Insert revision
    # Assert primary key constraint
    # Assert unique constraint on (uid, rev)

def test_event_jobs_idempotency():
    """Test job enqueue idempotency."""
    # Insert job twice with same (uid, rev, job_type)
    # Assert only 1 row exists

def test_event_evidence_cascade_delete():
    """Test evidence deleted when event deleted."""
    # Insert event + evidence
    # Delete event
    # Assert evidence deleted
```

**Worker Logic:**

```python
# tests/unit/test_worker.py

def test_claim_job():
    """Test job claiming with SKIP LOCKED."""
    # Create 2 pending jobs
    # Claim job in worker 1
    # Assert worker 2 claims different job

def test_retry_backoff():
    """Test exponential backoff calculation."""
    assert calculate_backoff(1) == 30
    assert calculate_backoff(2) == 60
    assert calculate_backoff(3) == 120
    assert calculate_backoff(5) >= 480
```

**Extraction Service:**

```python
# tests/unit/test_extraction_service.py

def test_extract_from_chunk():
    """Test Prompt A extraction."""
    # Mock OpenAI response
    # Call extract_from_chunk
    # Assert entities parsed
    # Assert events parsed
    # Assert evidence offsets valid

def test_canonicalize_events():
    """Test Prompt B canonicalization."""
    # Mock chunk extractions with duplicate events
    # Call canonicalize_events
    # Assert duplicates merged
    # Assert evidence lists combined
```

### 10.2 Integration Tests

```python
# tests/integration/test_v3_flow.py

def test_ingestion_creates_job():
    """Test artifact_ingest creates Postgres job."""
    # Call artifact_ingest
    # Assert artifact_revision row exists
    # Assert event_jobs row exists with PENDING status

def test_worker_processes_job():
    """Test worker claims and processes job."""
    # Insert artifact + enqueue job
    # Run worker for 1 iteration
    # Assert job status = DONE
    # Assert events exist in semantic_event
    # Assert evidence exists in event_evidence

def test_event_search_returns_results():
    """Test event_search queries Postgres."""
    # Insert artifact + events
    # Call event_search(query="decision")
    # Assert events returned
    # Assert evidence included
```

### 10.3 End-to-End Tests

**E2E Scenario 1: Small Artifact → Events Available**

```python
def test_e2e_small_artifact():
    """
    Test complete flow for small unchunked artifact.
    """
    # 1. Call artifact_ingest with small text
    result = artifact_ingest(
        artifact_type="note",
        source_system="test",
        content="Decision: We will use Postgres for event storage starting Monday."
    )
    assert result["is_chunked"] == False
    assert result["job_status"] == "PENDING"

    # 2. Check job_status
    job = job_status(result["artifact_uid"])
    assert job["status"] in ["PENDING", "PROCESSING"]

    # 3. Wait for worker to complete (poll or sleep)
    wait_for_job_done(result["job_id"], timeout=60)

    # 4. Call event_search
    events = event_search(query="Postgres", category="Decision")
    assert len(events["events"]) >= 1

    # 5. Verify evidence
    event = events["events"][0]
    assert event["category"] == "Decision"
    assert "Postgres" in event["narrative"]
    assert len(event["evidence"]) >= 1
    assert "Postgres" in event["evidence"][0]["quote"]
```

**E2E Scenario 2: Large Artifact → Chunking → Events**

```python
def test_e2e_large_artifact():
    """
    Test complete flow for large chunked artifact.
    """
    # 1. Ingest long document (>1200 tokens)
    content = generate_long_document(tokens=3000, decisions=3, commitments=2)
    result = artifact_ingest(
        artifact_type="doc",
        source_system="test",
        content=content
    )
    assert result["is_chunked"] == True
    assert result["num_chunks"] >= 3

    # 2. Wait for extraction
    wait_for_job_done(result["job_id"], timeout=120)

    # 3. Call event_list_for_revision
    events = event_list_for_revision(result["artifact_uid"], include_evidence=True)
    assert events["total"] >= 5  # 3 decisions + 2 commitments

    # 4. Verify evidence spans chunks
    decision_events = [e for e in events["events"] if e["category"] == "Decision"]
    assert len(decision_events) >= 3

    # 5. Verify chunk_id in evidence
    for event in decision_events:
        for evidence in event["evidence"]:
            assert evidence["chunk_id"] is not None
            assert "::chunk::" in evidence["chunk_id"]
```

**E2E Scenario 3: Idempotency - Re-ingest Same Content**

```python
def test_e2e_idempotency():
    """
    Test re-ingesting same content produces no duplicate job.
    """
    content = "Decision: Use Postgres."

    # 1. First ingest
    result1 = artifact_ingest(
        artifact_type="note",
        source_system="test",
        source_id="test_doc_1",
        content=content
    )

    # 2. Second ingest (same source_id, same content)
    result2 = artifact_ingest(
        artifact_type="note",
        source_system="test",
        source_id="test_doc_1",
        content=content
    )

    # 3. Assert same revision_id
    assert result1["revision_id"] == result2["revision_id"]
    assert result2["status"] == "unchanged"

    # 4. Assert no duplicate job
    jobs = postgres_client.execute(
        "SELECT COUNT(*) as count FROM event_jobs WHERE artifact_uid = :uid",
        {"uid": result1["artifact_uid"]}
    )
    assert jobs["count"] == 1
```

**E2E Scenario 4: New Revision Creates New Events**

```python
def test_e2e_new_revision():
    """
    Test updating content creates new revision with new events.
    """
    # 1. Ingest v1
    result1 = artifact_ingest(
        artifact_type="note",
        source_system="test",
        source_id="test_doc_1",
        content="Decision: Use MySQL."
    )
    wait_for_job_done(result1["job_id"])

    # 2. Ingest v2 (changed content)
    result2 = artifact_ingest(
        artifact_type="note",
        source_system="test",
        source_id="test_doc_1",
        content="Decision: Actually, use Postgres instead."
    )

    # 3. Assert different revision_id
    assert result1["revision_id"] != result2["revision_id"]
    assert result1["artifact_uid"] == result2["artifact_uid"]  # Same artifact

    # 4. Wait for v2 extraction
    wait_for_job_done(result2["job_id"])

    # 5. Query v1 events
    events_v1 = event_list_for_revision(result1["artifact_uid"], result1["revision_id"])
    assert any("MySQL" in e["narrative"] for e in events_v1["events"])

    # 6. Query v2 events (latest)
    events_v2 = event_list_for_revision(result2["artifact_uid"])
    assert any("Postgres" in e["narrative"] for e in events_v2["events"])
```

**E2E Scenario 5: Failure Mode - OpenAI Failure**

```python
def test_e2e_openai_failure():
    """
    Test worker handles OpenAI failure gracefully.
    """
    # 1. Inject OpenAI failure (mock or invalid API key in worker env)
    with override_env(OPENAI_API_KEY="sk-invalid"):
        # 2. Ingest artifact
        result = artifact_ingest(
            artifact_type="note",
            source_system="test",
            content="Decision: Test failure handling."
        )

        # 3. Wait for worker to fail
        time.sleep(5)

        # 4. Check job status
        job = job_status(result["artifact_uid"])
        assert job["status"] in ["PENDING", "FAILED"]  # Retrying or failed
        assert job["last_error_message"] is not None

        # 5. Verify no events written
        events = event_list_for_revision(result["artifact_uid"])
        assert events["total"] == 0

    # 6. Restore valid API key and retry
    result_reextract = event_reextract(result["artifact_uid"], force=True)
    wait_for_job_done(result_reextract["job_id"])

    # 7. Verify events now exist
    events = event_list_for_revision(result["artifact_uid"])
    assert events["total"] >= 1
```

### 10.4 Performance Tests

```python
def test_performance_ingestion():
    """Test ingestion remains fast (<1s for 90% of docs)."""
    latencies = []
    for i in range(100):
        start = time.time()
        artifact_ingest(
            artifact_type="note",
            source_system="test",
            content=f"Decision {i}: Do something."
        )
        latencies.append(time.time() - start)

    p90 = sorted(latencies)[89]
    assert p90 < 1.0  # 90th percentile < 1 second

def test_performance_extraction():
    """Test extraction completes within 5 minutes for 90% of docs."""
    # Ingest 20 documents
    jobs = []
    for i in range(20):
        result = artifact_ingest(
            artifact_type="doc",
            source_system="test",
            content=generate_document(tokens=2000)
        )
        jobs.append(result["job_id"])

    # Measure extraction time
    start = time.time()
    for job_id in jobs:
        wait_for_job_done(job_id, timeout=600)
    total_time = time.time() - start

    avg_time = total_time / 20
    assert avg_time < 300  # Average < 5 minutes
```

---

## 11. Implementation Sequence

### 11.1 Phase 1: Database Foundation (Week 1)

**Tasks:**
1. Create `migrations/001_v3_schema.sql` with all 4 tables
2. Implement `src/storage/postgres_client.py` with connection pooling
3. Add Postgres to `docker-compose.yml`
4. Write unit tests for schema validation
5. Create migration runner script

**Deliverables:**
- Postgres container running with schema
- Python client can connect and execute queries
- All tables created with correct constraints

### 11.2 Phase 2: Ingestion Changes (Week 1-2)

**Tasks:**
1. Modify `artifact_ingest` to generate `artifact_uid` + `revision_id`
2. Add Postgres writes to `artifact_revision`
3. Enqueue jobs to `event_jobs`
4. Update response format with new fields
5. Write integration tests for ingestion flow

**Deliverables:**
- `artifact_ingest` returns `artifact_uid`, `revision_id`, `job_id`
- Postgres tables populated after ingestion
- Idempotency tests pass

### 11.3 Phase 3: Worker Implementation (Week 2)

**Tasks:**
1. Create `src/worker.py` with job claiming logic
2. Implement `src/services/extraction_service.py`
3. Add Prompt A and Prompt B templates
4. Implement atomic event write logic
5. Add retry and backoff handling
6. Write unit tests for worker components

**Deliverables:**
- Worker can claim jobs with SKIP LOCKED
- Worker extracts events using OpenAI
- Worker writes events atomically to Postgres
- Retry logic works correctly

### 11.4 Phase 4: Event Query Tools (Week 3)

**Tasks:**
1. Implement `event_search` tool
2. Implement `event_get` tool
3. Implement `event_list_for_revision` tool
4. Implement `event_reextract` tool
5. Implement `job_status` tool
6. Write integration tests for all tools

**Deliverables:**
- All 5 new MCP tools functional
- Postgres FTS queries work correctly
- Evidence is returned with events

### 11.5 Phase 5: End-to-End Testing (Week 3-4)

**Tasks:**
1. Write E2E tests for all 5 scenarios
2. Run performance benchmarks
3. Test failure modes (OpenAI down, Postgres down)
4. Validate atomic guarantees
5. Test multi-worker concurrency

**Deliverables:**
- All E2E tests pass
- Performance targets met (ingestion <1s, extraction <5min)
- No partial writes in failure scenarios

### 11.6 Phase 6: Documentation & Deployment (Week 4)

**Tasks:**
1. Update README with V3 setup instructions
2. Create migration guide from V2 to V3
3. Write operational runbook (monitoring, troubleshooting)
4. Update docker-compose.yml with production settings
5. Create example queries and use cases

**Deliverables:**
- Complete V3 documentation
- Production-ready docker-compose.yml
- Migration guide for existing users

---

## 12. Non-Functional Requirements

### 12.1 Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Ingestion latency (p90) | < 1s | Time from `artifact_ingest` call to return |
| Extraction latency (p90) | < 5 min | Time from job PENDING to DONE |
| Event search latency (p95) | < 500ms | Time for `event_search` query |
| Worker throughput | >= 10 jobs/hour | Jobs processed per worker |

### 12.2 Reliability

| Requirement | Implementation |
|-------------|----------------|
| No partial writes | Postgres transactions with ACID guarantees |
| Job idempotency | Unique constraint on (artifact_uid, revision_id, job_type) |
| Retry transient failures | Exponential backoff up to 5 attempts |
| Graceful degradation | Ingestion succeeds even if worker down (async) |

### 12.3 Scalability

| Dimension | V3 Design | Future Enhancements |
|-----------|-----------|---------------------|
| Worker count | 1-10 workers | Horizontal scaling with worker pool |
| Job throughput | 100s/hour | Kafka for 1000s/hour |
| Event storage | 100K-1M events | Postgres partitioning by time |
| Query performance | Postgres FTS | Elasticsearch for complex queries |

### 12.4 Observability

**Logging:**
- Worker logs job claim, extraction start/end, success/failure
- MCP server logs tool calls with artifact_uid/revision_id
- All errors logged with stack traces

**Metrics (future):**
- Job queue depth (PENDING jobs)
- Extraction latency histogram
- OpenAI API latency and error rate
- Event count by category

**Health Checks:**
- MCP server: `/health` endpoint checks Postgres + Chroma
- Worker: Heartbeat updates in Postgres (future)

### 12.5 Security

| Aspect | V3 Implementation | Future Enhancements |
|--------|-------------------|---------------------|
| API authentication | None (local trust) | API key authentication |
| Postgres access | Hardcoded credentials | Secrets management |
| OpenAI key storage | Environment variable | Vault or KMS |
| Privacy enforcement | Metadata only | Query-time filtering by visibility_scope |
| Audit logging | Basic server logs | Structured audit trail in Postgres |

---

## Appendix A: SQL DDL Reference

```sql
-- Complete DDL for all V3 tables

-- artifact_revision
CREATE TABLE artifact_revision (
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('email', 'doc', 'chat', 'transcript', 'note')),
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_ts TIMESTAMPTZ NULL,
    content_hash TEXT NOT NULL,
    token_count INT NOT NULL,
    is_chunked BOOLEAN NOT NULL,
    chunk_count INT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal', 'sensitive', 'highly_sensitive')),
    visibility_scope TEXT NOT NULL DEFAULT 'me' CHECK (visibility_scope IN ('me', 'team', 'org', 'custom')),
    retention_policy TEXT NOT NULL DEFAULT 'forever' CHECK (retention_policy IN ('forever', '1y', 'until_resolved', 'custom')),
    is_latest BOOLEAN NOT NULL DEFAULT true,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_uid, revision_id)
);

CREATE INDEX idx_artifact_revision_uid_latest ON artifact_revision (artifact_uid, is_latest);
CREATE INDEX idx_artifact_revision_ingested ON artifact_revision (ingested_at DESC);
CREATE INDEX idx_artifact_revision_source ON artifact_revision (source_system, source_id);
CREATE INDEX idx_artifact_revision_artifact_id ON artifact_revision (artifact_id);

-- event_jobs
CREATE TABLE event_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL DEFAULT 'extract_events',
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'DONE', 'FAILED')),
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

CREATE INDEX idx_event_jobs_claimable ON event_jobs (status, next_run_at) WHERE status = 'PENDING';
CREATE INDEX idx_event_jobs_revision ON event_jobs (artifact_uid, revision_id);
CREATE INDEX idx_event_jobs_status ON event_jobs (status);

-- semantic_event
CREATE TABLE semantic_event (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('Commitment', 'Execution', 'Decision', 'Collaboration', 'QualityRisk', 'Feedback', 'Change', 'Stakeholder')),
    event_time TIMESTAMPTZ NULL,
    narrative TEXT NOT NULL,
    subject_json JSONB NOT NULL,
    actors_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    extraction_run_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_semantic_event_revision ON semantic_event (artifact_uid, revision_id);
CREATE INDEX idx_semantic_event_category_time ON semantic_event (category, event_time DESC NULLS LAST);
CREATE INDEX idx_semantic_event_extraction ON semantic_event (extraction_run_id);
CREATE INDEX idx_semantic_event_narrative_fts ON semantic_event USING GIN (to_tsvector('english', narrative));
CREATE INDEX idx_semantic_event_subject_type ON semantic_event ((subject_json->>'type'));
CREATE INDEX idx_semantic_event_actors ON semantic_event USING GIN (actors_json);

-- event_evidence
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
    FOREIGN KEY (event_id) REFERENCES semantic_event(event_id) ON DELETE CASCADE
);

CREATE INDEX idx_event_evidence_event ON event_evidence (event_id);
CREATE INDEX idx_event_evidence_revision ON event_evidence (artifact_uid, revision_id);
CREATE INDEX idx_event_evidence_chunk ON event_evidence (chunk_id) WHERE chunk_id IS NOT NULL;
```

---

## Appendix B: Python Type Hints

```python
# Type hints for V3 API contracts

from typing import Optional, List, Dict
from datetime import datetime
from dataclasses import dataclass

@dataclass
class EventSearchRequest:
    query: Optional[str] = None
    limit: int = 20
    category: Optional[str] = None
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    artifact_uid: Optional[str] = None
    include_evidence: bool = True

@dataclass
class Evidence:
    quote: str
    start_char: int
    end_char: int
    chunk_id: Optional[str]

@dataclass
class Event:
    event_id: str
    artifact_uid: str
    revision_id: str
    category: str
    event_time: Optional[datetime]
    narrative: str
    subject: Dict  # {"type": str, "ref": str}
    actors: List[Dict]  # [{"ref": str, "role": str}]
    confidence: float
    evidence: List[Evidence]

@dataclass
class EventSearchResponse:
    events: List[Event]
    total: int
    filters_applied: Dict

@dataclass
class JobStatus:
    job_id: str
    artifact_uid: str
    revision_id: str
    status: str  # PENDING|PROCESSING|DONE|FAILED
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    locked_by: Optional[str]
    locked_at: Optional[datetime]
    last_error_code: Optional[str]
    last_error_message: Optional[str]
    next_run_at: Optional[datetime]
```

---

## Appendix C: Example Queries

**Find all decisions about pricing:**
```python
event_search(query="pricing", category="Decision", limit=10)
```

**Find commitments due in Q1 2024:**
```python
event_search(
    category="Commitment",
    time_from="2024-01-01T00:00:00Z",
    time_to="2024-03-31T23:59:59Z"
)
```

**Get all events for an artifact:**
```python
event_list_for_revision(artifact_uid="uid_abc123", include_evidence=True)
```

**Check if extraction is complete:**
```python
job_status(artifact_uid="uid_abc123")
```

**Force re-extraction with improved prompts:**
```python
event_reextract(artifact_uid="uid_abc123", force=True)
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-27 | Technical PM | Initial V3 specification |

---

**END OF SPECIFICATION**
