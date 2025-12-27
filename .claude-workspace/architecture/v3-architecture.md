# MCP Memory Server V3: Architecture Document

**Version:** 3.0
**Date:** 2025-12-27
**Author:** Senior Architect
**Status:** Approved for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Component Architecture](#3-component-architecture)
4. [Data Flow Diagrams](#4-data-flow-diagrams)
5. [Technology Stack](#5-technology-stack)
6. [Scalability Considerations](#6-scalability-considerations)
7. [Integration Points](#7-integration-points)
8. [Quality Attributes](#8-quality-attributes)

---

## 1. Executive Summary

### 1.1 What is V3?

V3 transforms MCP Memory from a pure text retrieval system into an **intelligent semantic events platform** that automatically extracts, structures, and makes queryable the key decisions, commitments, and activities buried in documents.

**Core Architecture Principles:**

1. **Separation of Concerns**: Text retrieval (ChromaDB) vs. structured events (Postgres)
2. **Async by Default**: Long-running extraction happens out-of-band via job queue
3. **Immutable Versioning**: Artifacts have stable UIDs, revisions track content changes
4. **Evidence Traceability**: Every extracted event links to exact source text with quotes
5. **Replace-on-Success**: Event extraction is atomic - all or nothing per revision

### 1.2 Key Architectural Changes from V2

| Aspect | V2 | V3 |
|--------|----|----|
| **Storage** | ChromaDB only | ChromaDB + Postgres |
| **Data Model** | Artifacts only | Artifacts + Revisions + Events |
| **Processing** | Synchronous ingestion | Async job queue for extraction |
| **Versioning** | Replace on re-ingest | Immutable revision history |
| **Querying** | Vector search only | Vector + structured SQL queries |
| **Containers** | 2 (MCP + Chroma) | 4 (MCP + Chroma + Postgres + Worker) |

### 1.3 Design Goals

1. **Fast Ingestion**: < 1s for 95% of documents (extraction happens async)
2. **Reliable Extraction**: Retry logic with exponential backoff, max 5 attempts
3. **Atomic Writes**: No partial event states - succeed completely or fail
4. **Queryability**: SQL + full-text search for structured event queries
5. **Maintainability**: Clear separation between MCP server and worker concerns

---

## 2. System Overview

### 2.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                  │
│  Claude Code CLI | Claude Desktop | Cursor IDE | Other MCP Clients   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    MCP TRANSPORT LAYER                                │
│              Streamable HTTP (localhost:3000)                         │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        MCP SERVER                                     │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Tool Layer (17 tools)                     │    │
│  │                                                              │    │
│  │  V2 Tools (12):                     V3 Tools (5):           │    │
│  │  • memory_*                         • event_search          │    │
│  │  • history_*                        • event_get             │    │
│  │  • artifact_* (modified)            • event_list_for_rev    │    │
│  │  • hybrid_search                    • event_reextract       │    │
│  │  • embedding_health                 • job_status            │    │
│  └────────────────────────┬────────────────────────────────────┘    │
│                           │                                          │
│  ┌────────────────────────┼────────────────────────────────────┐    │
│  │      Service Layer     │                                     │    │
│  │  • EmbeddingService    • ChunkingService                    │    │
│  │  • RetrievalService    • PostgresClient (NEW)               │    │
│  └────────────────────────┼────────────────────────────────────┘    │
│                           │                                          │
│  ┌────────────────────────┼────────────────────────────────────┐    │
│  │      Storage Layer     │                                     │    │
│  │  • ChromaDB Client     • Postgres Client (NEW)              │    │
│  └────────────────────────┼────────────────────────────────────┘    │
│                           │                                          │
└───────────────────────────┼──────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────┐ ┌───────────────┐
    │   ChromaDB   │ │ Postgres │ │ Event Worker  │
    │   (Vectors)  │ │ (Events) │ │  (Async)      │
    │   Port: 8001 │ │ Port:5432│ │               │
    └──────────────┘ └──────────┘ └───────┬───────┘
                                          │
                                          ▼
                                  ┌─────────────────┐
                                  │   OpenAI API    │
                                  │   (Extraction)  │
                                  │   GPT-4-Turbo   │
                                  └─────────────────┘
```

### 2.2 Container Architecture

V3 uses **4 Docker containers**:

| Container | Purpose | Dependencies | Ports |
|-----------|---------|--------------|-------|
| **mcp-server** | FastMCP server with 17 tools | chroma, postgres | 3000 |
| **chroma** | Vector storage for embeddings | (none) | 8001:8000 |
| **postgres** | Relational DB for events/jobs | (none) | 5432:5432 |
| **event-worker** | Async event extraction worker | chroma, postgres | (none) |

**Container Communication:**

```
mcp-server  ──┬──> chroma:8000    (Read/Write artifacts, chunks)
              └──> postgres:5432  (Read/Write revisions, events, jobs)

event-worker ─┬──> postgres:5432  (Claim jobs, write events)
              ├──> chroma:8000    (Read artifact text)
              └──> openai API     (LLM extraction)
```

---

## 3. Component Architecture

### 3.1 MCP Server Components

```
src/
├── server.py                    # FastMCP entry point, 17 tool definitions
├── config.py                    # Environment configuration
│
├── services/
│   ├── embedding_service.py     # OpenAI embeddings (V2, unchanged)
│   ├── chunking_service.py      # Token-window chunking (V2, unchanged)
│   ├── retrieval_service.py     # RRF hybrid search (V2, unchanged)
│   ├── privacy_service.py       # Privacy metadata (V2, placeholder)
│   └── postgres_service.py      # NEW: Postgres query abstraction
│
├── storage/
│   ├── chroma_client.py         # ChromaDB HTTP client manager (V2)
│   ├── postgres_client.py       # NEW: Postgres connection pool
│   ├── collections.py           # ChromaDB collection definitions (V2)
│   ├── models.py                # Data models (V2 + V3 events)
│   └── postgres_schema.py       # NEW: SQL DDL and migrations
│
├── tools/
│   ├── memory_tools.py          # V2 memory tools
│   ├── history_tools.py         # V2 history tools
│   ├── artifact_tools.py        # V2 + V3 modifications
│   └── event_tools.py           # NEW: V3 event tools
│
└── utils/
    ├── errors.py                # Custom exceptions
    ├── logging.py               # Logging configuration
    └── id_generation.py         # ID generation helpers
```

### 3.2 Event Worker Components

```
src/
├── worker.py                    # Main worker loop
│
├── services/
│   ├── extraction_service.py   # NEW: LLM-based event extraction
│   │   ├── extract_from_chunk()      # Prompt A: Extract per chunk
│   │   └── canonicalize_events()     # Prompt B: Merge across chunks
│   └── job_service.py          # NEW: Job queue operations
│
└── prompts/
    ├── prompt_a_extract.txt    # NEW: Extraction prompt template
    └── prompt_b_canonicalize.txt # NEW: Canonicalization prompt template
```

### 3.3 Database Components

#### Postgres Schema (4 tables)

1. **artifact_revision**: Immutable artifact version records
   - Primary Key: (artifact_uid, revision_id)
   - Tracks content hash, chunking metadata, privacy fields
   - Links to ChromaDB via artifact_id

2. **event_jobs**: Durable job queue
   - Primary Key: job_id (UUID)
   - States: PENDING → PROCESSING → DONE/FAILED
   - Supports atomic claiming with FOR UPDATE SKIP LOCKED

3. **semantic_event**: Structured events
   - Primary Key: event_id (UUID)
   - 8 event categories (Commitment, Decision, etc.)
   - JSONB for subject/actors flexibility
   - Full-text search on narrative

4. **event_evidence**: Evidence spans
   - Primary Key: evidence_id (UUID)
   - Links events to artifact text with quotes + offsets
   - Cascade delete with events

---

## 4. Data Flow Diagrams

### 4.1 Artifact Ingestion Flow (V3)

```
User: artifact_ingest(...)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: Validation & Hashing (MCP Server)                  │
│                                                              │
│  1. Validate inputs (artifact_type, source_system, etc.)    │
│  2. Generate artifact_uid (stable across revisions)         │
│     • If source_id: sha256(source_system:source_id)        │
│     • Else: random UUID                                     │
│  3. Generate revision_id (unique per content)               │
│     • sha256(content)                                       │
│  4. Check for duplicate revision in Postgres                │
│     • Same uid + same revision_id = NO-OP, return existing  │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: Chunking & Embedding (MCP Server)                  │
│                                                              │
│  5. Count tokens via tiktoken                               │
│  6. If > 1200 tokens: chunk (900 tok, 100 overlap)         │
│  7. Generate embeddings (OpenAI batch API)                  │
│  8. Write to ChromaDB:                                      │
│     • artifacts collection (full text or summary)           │
│     • artifact_chunks collection (if chunked)               │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: Revision Tracking & Job Enqueue (MCP Server)       │
│                                                              │
│  9. BEGIN TRANSACTION                                       │
│ 10. Mark old revisions as not latest:                       │
│     UPDATE artifact_revision SET is_latest = false          │
│     WHERE artifact_uid = :uid AND is_latest = true          │
│ 11. Insert new revision:                                    │
│     INSERT INTO artifact_revision (...)                     │
│ 12. Enqueue extraction job:                                 │
│     INSERT INTO event_jobs (status='PENDING', ...)          │
│ 13. COMMIT                                                  │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
Return to user (< 1s):
{
  "artifact_id": "art_abc123",
  "artifact_uid": "uid_stable",
  "revision_id": "rev_unique",
  "is_chunked": true,
  "num_chunks": 5,
  "job_id": "job_xyz789",
  "job_status": "PENDING"
}
```

### 4.2 Event Extraction Flow (Async Worker)

```
Event Worker (infinite loop, polling every POLL_INTERVAL_MS)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: Job Claiming (Atomic)                              │
│                                                              │
│  BEGIN TRANSACTION                                          │
│    SELECT job_id, artifact_uid, revision_id                 │
│    FROM event_jobs                                          │
│    WHERE status = 'PENDING'                                 │
│      AND next_run_at <= now()                               │
│    ORDER BY created_at ASC                                  │
│    FOR UPDATE SKIP LOCKED                                   │
│    LIMIT 1;                                                 │
│                                                              │
│    UPDATE event_jobs SET                                    │
│      status = 'PROCESSING',                                 │
│      locked_at = now(),                                     │
│      locked_by = :worker_id,                                │
│      attempts = attempts + 1                                │
│    WHERE job_id = :job_id;                                  │
│  COMMIT                                                     │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: Fetch Artifact Text (ChromaDB)                     │
│                                                              │
│  1. Load artifact_revision metadata from Postgres           │
│  2. If unchunked:                                           │
│     • Fetch artifact from artifacts collection              │
│  3. If chunked:                                             │
│     • Fetch all chunks from artifact_chunks collection      │
│     • Sort by chunk_index                                   │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: Extract Events (Prompt A - Per Chunk)              │
│                                                              │
│  For each chunk:                                            │
│    4. Call OpenAI GPT-4-Turbo with Prompt A:               │
│       • Input: chunk text                                   │
│       • Output: JSON with entities + events                 │
│       • response_format: {"type": "json_object"}           │
│       • temperature: 0.0 (deterministic)                    │
│    5. Parse JSON response                                   │
│    6. Validate schema (categories, evidence format)         │
│                                                              │
│  Collect all chunk extractions                              │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 4: Canonicalize Events (Prompt B - Cross-Chunk)       │
│                                                              │
│  7. Call OpenAI GPT-4-Turbo with Prompt B:                 │
│     • Input: All chunk extractions (JSON array)             │
│     • Output: Canonical event list (deduplicated)           │
│     • Merge evidence across chunks                          │
│     • Resolve entity aliases                                │
│  8. Parse canonical events                                  │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 5: Write Events (Atomic Transaction)                  │
│                                                              │
│  BEGIN TRANSACTION                                          │
│    9. Delete old events (replace-on-success):               │
│       DELETE FROM semantic_event                            │
│       WHERE artifact_uid = :uid AND revision_id = :rev;     │
│   10. For each canonical event:                             │
│       INSERT INTO semantic_event (...) RETURNING event_id;  │
│       For each evidence span:                               │
│         INSERT INTO event_evidence (...);                   │
│  COMMIT                                                     │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 6: Mark Job Done                                      │
│                                                              │
│  11. UPDATE event_jobs SET                                  │
│       status = 'DONE',                                      │
│       updated_at = now()                                    │
│      WHERE job_id = :job_id;                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘

Total time: 5-60 seconds (depending on document size, API latency)
```

### 4.3 Event Query Flow (V3)

```
User: event_search(query="pricing decision", category="Decision")
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: Build Query (MCP Server)                           │
│                                                              │
│  1. Validate inputs (category enum, time format)            │
│  2. Build SQL query with filters:                           │
│     SELECT e.*                                              │
│     FROM semantic_event e                                   │
│     WHERE e.category = 'Decision'                           │
│       AND to_tsvector('english', e.narrative)               │
│           @@ to_tsquery('english', 'pricing')               │
│     ORDER BY e.event_time DESC NULLS LAST                   │
│     LIMIT 20;                                               │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: Execute Query (Postgres)                           │
│                                                              │
│  3. Postgres executes query with indexes:                   │
│     • idx_semantic_event_category_time (category filter)    │
│     • idx_semantic_event_narrative_fts (full-text search)   │
│  4. Returns matching event rows                             │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: Fetch Evidence (if include_evidence=true)          │
│                                                              │
│  5. For each event:                                         │
│     SELECT quote, start_char, end_char, chunk_id            │
│     FROM event_evidence                                     │
│     WHERE event_id = :event_id;                             │
│  6. Attach evidence to event objects                        │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
Return to user (< 500ms):
{
  "events": [
    {
      "event_id": "evt_abc123",
      "category": "Decision",
      "narrative": "Team decided to adopt freemium pricing",
      "event_time": "2024-03-15T14:30:00Z",
      "subject": {"type": "project", "ref": "pricing-model"},
      "actors": [{"ref": "Alice", "role": "owner"}],
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
  "total": 1
}
```

---

## 5. Technology Stack

### 5.1 Core Technologies

| Component | Technology | Version | Rationale |
|-----------|-----------|---------|-----------|
| **MCP Server** | Python + FastMCP | 1.0+ | Official MCP SDK, Streamable HTTP support |
| **Worker** | Python | 3.11+ | Same codebase as server, easier deployment |
| **Vector DB** | ChromaDB | 0.4+ | V2 decision, unchanged in V3 |
| **Relational DB** | PostgreSQL | 16+ | ACID guarantees, full-text search, JSONB |
| **Embeddings** | OpenAI API | text-embedding-3-large | V2 decision, unchanged in V3 |
| **Extraction** | OpenAI API | gpt-4-turbo-preview | Structured JSON output, reliability |
| **Tokenization** | tiktoken | 0.5+ | OpenAI token counting for chunking |
| **Container** | Docker Compose | 3.8+ | Multi-container orchestration |

### 5.2 Postgres: Why Not Kafka?

**Decision**: Use Postgres as a lightweight job queue instead of Kafka.

**Rationale** (see ADR-001):

1. **Simplicity**: One database vs. separate message broker
2. **ACID Guarantees**: Transactional job enqueue with revision writes
3. **Sufficient Scale**: < 1000 docs/day, no need for Kafka's throughput
4. **Query Flexibility**: SQL queries on job history/status
5. **Operational Overhead**: No ZooKeeper, no partition management

**Trade-offs Accepted**:
- Not suitable for > 10K jobs/sec (not our use case)
- No built-in pub/sub (we use polling, which is fine at our scale)

### 5.3 Two-Phase LLM Extraction

**Decision**: Use Prompt A (extract per chunk) + Prompt B (canonicalize across chunks).

**Rationale** (see ADR-002):

1. **Chunk-Level Accuracy**: Prompt A sees full context within each chunk
2. **Deduplication**: Prompt B merges duplicates that span chunks
3. **Evidence Traceability**: Each event preserves exact character offsets
4. **Replace-on-Success**: All events written atomically or not at all

**Alternative Considered**: Single-pass extraction across all chunks
- **Rejected**: Token limits, loss of per-chunk evidence offsets

---

## 6. Scalability Considerations

### 6.1 Current Scale (V3 MVP)

| Metric | Target | Notes |
|--------|--------|-------|
| **Documents Ingested** | 100-1000/day | Startup/small team scale |
| **Concurrent Workers** | 1-2 | Single Docker host |
| **Extraction Latency** | 5-60s | Per document, depends on size |
| **Query Latency** | < 500ms | Event search with evidence |
| **Storage Growth** | ~1GB/month | Embeddings + events |

### 6.2 Horizontal Scaling (Future)

**Worker Scaling**:
```yaml
# docker-compose.yml
event-worker-1:
  command: python -m src.worker
  environment:
    WORKER_ID: worker-1

event-worker-2:
  command: python -m src.worker
  environment:
    WORKER_ID: worker-2

# etc...
```

**Postgres Job Queue** supports multiple workers via `FOR UPDATE SKIP LOCKED`:
- Each worker atomically claims one job
- No job is processed by > 1 worker
- Dead workers: jobs self-heal via `next_run_at` retry logic

### 6.3 Bottlenecks & Mitigation

| Bottleneck | Impact | Mitigation |
|------------|--------|------------|
| **OpenAI API Rate Limits** | Worker stalls | Exponential backoff, multiple API keys |
| **Postgres Connection Pool** | MCP server blocked | Increase pool size, use PgBouncer |
| **ChromaDB Single Node** | Storage limit | Horizontal sharding (future V4) |
| **Single MCP Server** | Request throughput | Load balancer + multiple MCP instances |

### 6.4 Storage Growth Projections

**Assumptions**:
- 1000 docs/day
- Avg 5 events/doc
- Avg 3 evidence spans/event

**Annual Growth**:
```
ChromaDB (Vectors):
- Artifacts: 1000 docs × 3072 dims × 4 bytes × 365 = ~4.5 GB
- Chunks: Assume 30% chunked, 3 chunks avg = ~1.3 GB
- Total: ~6 GB/year

Postgres (Events):
- artifact_revision: 1000 × 365 × 500 bytes = ~180 MB
- semantic_event: 1000 × 365 × 5 × 1 KB = ~1.8 GB
- event_evidence: 1000 × 365 × 5 × 3 × 300 bytes = ~1.6 GB
- event_jobs: 1000 × 365 × 500 bytes = ~180 MB
- Total: ~3.8 GB/year

Grand Total: ~10 GB/year (easily fits on single host)
```

---

## 7. Integration Points

### 7.1 External Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server System                         │
└───────┬─────────────────────────────────────┬───────────────┘
        │                                     │
        ▼                                     ▼
┌─────────────────┐                  ┌─────────────────┐
│   OpenAI API    │                  │  MCP Clients    │
│                 │                  │                 │
│ • Embeddings    │                  │ • Claude Code   │
│   text-embed-   │                  │ • Claude Desktop│
│   3-large       │                  │ • Cursor IDE    │
│                 │                  │                 │
│ • Extraction    │                  │  Transport:     │
│   gpt-4-turbo   │                  │  Streamable HTTP│
│                 │                  │  (SSE)          │
└─────────────────┘                  └─────────────────┘
```

### 7.2 MCP Client Integration

**Configuration** (Claude Desktop example):

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:3000/mcp/"]
    }
  }
}
```

**Available Tools** (17 total):

| Category | Tools | Description |
|----------|-------|-------------|
| **Memory** | memory_store, memory_search, memory_list, memory_delete | Semantic memory storage |
| **History** | history_append, history_get | Conversation history |
| **Artifacts** | artifact_ingest, artifact_search, artifact_get, artifact_delete | Document ingestion + search |
| **Hybrid** | hybrid_search, embedding_health | Cross-collection search |
| **Events** | event_search, event_get, event_list_for_revision, event_reextract, job_status | V3 structured events |

### 7.3 Database Integration

**Postgres Connection**:
```python
# Connection pool configuration
POSTGRES_DSN = "postgresql://events:events@postgres:5432/events"
POOL_SIZE = 10
POOL_MAX_OVERFLOW = 20
```

**ChromaDB Connection**:
```python
# HTTP client configuration
CHROMA_HOST = "chroma"
CHROMA_PORT = 8000  # Internal container port
```

### 7.4 Error Handling & Observability

**OpenAI API Errors**:
| Error | Code | Strategy |
|-------|------|----------|
| Rate Limit | 429 | Exponential backoff, max 10 min |
| Timeout | N/A | Retry with same backoff |
| Invalid JSON | N/A | Terminal failure, log for review |

**Database Errors**:
| Error | Strategy |
|-------|----------|
| Connection Timeout | Retry 3x, then fail request |
| Transaction Deadlock | Automatic retry by Postgres |
| Constraint Violation | Return error to user |

**Logging**:
```python
# Structured logging
logger.info("job_claimed", job_id=job_id, artifact_uid=uid)
logger.error("extraction_failed", job_id=job_id, error=str(e))
```

---

## 8. Quality Attributes

### 8.1 Performance

| Operation | Target | Actual (Expected) |
|-----------|--------|-------------------|
| artifact_ingest | < 1s (95th %ile) | 500-800ms |
| event_search | < 500ms | 200-400ms |
| event_get | < 200ms | 50-150ms |
| Event extraction | < 5 min (90th %ile) | 10-60s typical |

### 8.2 Reliability

**Guarantees**:
1. **Atomic Writes**: Events written all-or-nothing per revision
2. **Idempotency**: Re-ingesting same content is a no-op
3. **Retry Logic**: Transient failures retry up to 5x with backoff
4. **Crash Recovery**: Workers can die; jobs self-heal via polling

**Failure Modes**:
| Scenario | Outcome | Recovery |
|----------|---------|----------|
| Worker crashes mid-extraction | Job stuck in PROCESSING | Stale job cleanup (future) or manual reset |
| OpenAI API down | Job retries, eventually FAILED | Manual reextract via tool |
| Postgres down | Ingestion fails, error returned | User retries when DB recovers |
| ChromaDB down | Ingestion fails, error returned | User retries when DB recovers |

### 8.3 Maintainability

**Code Organization**:
- Clear separation: MCP server vs. worker
- Service layer abstracts storage details
- Prompts in separate files for easy tuning

**Testing Strategy**:
- Unit tests: Services, ID generation, chunking
- Integration tests: End-to-end ingestion + extraction
- Contract tests: MCP tool signatures

**Deployment**:
- Single `docker-compose up` command
- Migrations run automatically on Postgres startup
- Environment variables for all configuration

### 8.4 Security

**V3 Status**:
- Privacy metadata stored (sensitivity, visibility_scope, retention_policy)
- NOT enforced in queries (V4 roadmap)
- No authentication (designed for local/trusted network)
- HTTPS via ngrok for external access (optional)

**Future Enhancements**:
- API key authentication
- Query-time privacy filtering
- Retention policy enforcement via cron job

---

## Appendix: Key Design Decisions Summary

| Decision | Rationale | ADR |
|----------|-----------|-----|
| **Postgres over Kafka** | Simplicity, ACID guarantees, sufficient scale | ADR-001 |
| **Two-phase extraction** | Chunk accuracy + deduplication | ADR-002 |
| **Replace-on-success** | Atomic writes, no partial states | ADR-002 |
| **Immutable revisions** | Audit trail, change detection | Spec |
| **Async job queue** | Fast ingestion, reliable extraction | Spec |
| **JSONB for subject/actors** | Flexible schema, extensibility | Spec |
| **8 event categories** | Balanced specificity vs. simplicity | Spec |

---

**End of V3 Architecture Document**
