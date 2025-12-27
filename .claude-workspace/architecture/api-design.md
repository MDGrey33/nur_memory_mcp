# API Design: MCP Tools V3

**Version:** 3.0
**Date:** 2025-12-27
**Author:** Senior Architect
**Status:** Approved for Implementation

---

## Table of Contents

1. [Overview](#1-overview)
2. [API Conventions](#2-api-conventions)
3. [V3 New Tools](#3-v3-new-tools)
4. [V3 Modified Tools](#4-v3-modified-tools)
5. [V2 Unchanged Tools](#5-v2-unchanged-tools)
6. [Error Handling](#6-error-handling)
7. [Versioning Strategy](#7-versioning-strategy)

---

## 1. Overview

### 1.1 Tool Summary

V3 adds **5 new tools** and modifies **1 existing tool**, bringing the total to **17 MCP tools**:

| Category | V2 Tools | V3 New Tools | V3 Modified | Total |
|----------|----------|--------------|-------------|-------|
| **Memory** | 4 | 0 | 0 | 4 |
| **History** | 2 | 0 | 0 | 2 |
| **Artifacts** | 4 | 0 | 1 | 4 |
| **Hybrid** | 2 | 0 | 0 | 2 |
| **Events** | 0 | 5 | 0 | 5 |
| **Total** | **12** | **5** | **1** | **17** |

### 1.2 V3 New Tools

| Tool | Purpose |
|------|---------|
| `event_search` | Query structured events with filters and optional evidence |
| `event_get` | Retrieve a single event by ID with full details |
| `event_list_for_revision` | List all events for a specific artifact revision |
| `event_reextract` | Force re-extraction of events for a revision |
| `job_status` | Check the status of an async extraction job |

### 1.3 Design Principles

1. **Consistency**: Follow V2 naming conventions (snake_case, verb_noun pattern)
2. **Optionality**: Make common parameters optional with sensible defaults
3. **Evidence**: Include evidence by default where relevant (can be disabled)
4. **Error Clarity**: Return structured error objects with clear messages
5. **Type Safety**: Use Pydantic models for validation and documentation

---

## 2. API Conventions

### 2.1 Naming Conventions

**Tools**: `{noun}_{verb}` pattern
- Examples: `event_search`, `event_get`, `job_status`
- Exceptions: `artifact_ingest` (legacy V2), `embedding_health` (legacy V2)

**Parameters**: `snake_case`
- Examples: `artifact_uid`, `include_evidence`, `time_from`

**Response Keys**: `snake_case`
- Examples: `event_id`, `job_status`, `filters_applied`

### 2.2 Common Parameter Patterns

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max results (1-100) |
| `include_evidence` | bool | true | Include evidence quotes |
| `artifact_uid` | str | required | Stable artifact identifier |
| `revision_id` | str | null (latest) | Specific revision or latest |

### 2.3 Response Formats

**Success Response** (structured object):
```json
{
  "events": [...],
  "total": 42,
  "filters_applied": {...}
}
```

**Error Response** (structured object):
```json
{
  "error": "Artifact uid_abc123 not found",
  "error_code": "NOT_FOUND",
  "details": {...}
}
```

**Simple Success** (string):
```
"Stored memory: mem_abc12345"
```

### 2.4 ID Formats

| Entity | Format | Example |
|--------|--------|---------|
| artifact_uid | `uid_{sha256[:16]}` | `uid_9f2c1a8b4e3d2c1b` |
| revision_id | `rev_{sha256[:16]}` | `rev_4e3d2c1b9f2c1a8b` |
| event_id | `evt_{uuid}` or UUID | `evt_123e4567-e89b-12d3-a456-426614174000` |
| job_id | `job_{uuid}` or UUID | `job_987f6543-e21c-43d2-b789-123456789012` |
| evidence_id | `evi_{uuid}` or UUID | `evi_abc12345-d678-90ef-g123-456789abcdef` |

---

## 3. V3 New Tools

### 3.1 event_search

**Purpose**: Query structured events with filters and optional evidence.

#### Signature

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
        dict: Events list with metadata

    Examples:
        # Search all Decision events
        event_search(category="Decision")

        # Search for pricing decisions
        event_search(query="pricing", category="Decision")

        # Search events in Q1 2024
        event_search(time_from="2024-01-01T00:00:00Z", time_to="2024-03-31T23:59:59Z")
    """
```

#### Request Example

```json
{
  "query": "pricing decision",
  "limit": 10,
  "category": "Decision",
  "time_from": "2024-01-01T00:00:00Z",
  "time_to": "2024-12-31T23:59:59Z",
  "include_evidence": true
}
```

#### Response Example (Success)

```json
{
  "events": [
    {
      "event_id": "evt_abc123",
      "artifact_uid": "uid_def456",
      "revision_id": "rev_ghi789",
      "category": "Decision",
      "event_time": "2024-03-15T14:30:00Z",
      "narrative": "Team decided to adopt freemium pricing model",
      "subject": {
        "type": "project",
        "ref": "pricing-model"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner"
        },
        {
          "ref": "Bob Smith",
          "role": "stakeholder"
        }
      ],
      "confidence": 0.95,
      "evidence": [
        {
          "evidence_id": "evi_jkl012",
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
    "query": "pricing decision",
    "category": "Decision",
    "time_from": "2024-01-01T00:00:00Z",
    "time_to": "2024-12-31T23:59:59Z"
  }
}
```

#### Response Example (No Results)

```json
{
  "events": [],
  "total": 0,
  "filters_applied": {
    "query": "nonexistent",
    "category": null,
    "time_from": null,
    "time_to": null
  }
}
```

#### Error Example

```json
{
  "error": "Invalid category: InvalidCategory. Must be one of: Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder",
  "error_code": "INVALID_CATEGORY"
}
```

---

### 3.2 event_get

**Purpose**: Retrieve a single event by ID with full details including evidence.

#### Signature

```python
@mcp.tool()
def event_get(event_id: str) -> dict:
    """
    Get a single event by ID with all evidence.

    Args:
        event_id: Event UUID (e.g., evt_abc123 or full UUID)

    Returns:
        dict: Full event details with evidence

    Examples:
        # Get event by ID
        event_get("evt_abc123")
    """
```

#### Request Example

```json
{
  "event_id": "evt_abc123"
}
```

#### Response Example (Success)

```json
{
  "event_id": "evt_abc123",
  "artifact_uid": "uid_def456",
  "revision_id": "rev_ghi789",
  "category": "Decision",
  "event_time": "2024-03-15T14:30:00Z",
  "narrative": "Team decided to adopt freemium pricing model",
  "subject": {
    "type": "project",
    "ref": "pricing-model"
  },
  "actors": [
    {
      "ref": "Alice Chen",
      "role": "owner"
    },
    {
      "ref": "Bob Smith",
      "role": "stakeholder"
    }
  ],
  "confidence": 0.95,
  "evidence": [
    {
      "evidence_id": "evi_jkl012",
      "quote": "we're going with freemium for launch",
      "start_char": 1250,
      "end_char": 1290,
      "chunk_id": "art_def456::chunk::002::xyz789"
    }
  ],
  "extraction_run_id": "job_mno345",
  "created_at": "2024-03-15T15:00:00Z"
}
```

#### Error Example

```json
{
  "error": "Event evt_abc123 not found",
  "error_code": "NOT_FOUND"
}
```

---

### 3.3 event_list_for_revision

**Purpose**: List all events for a specific artifact revision (or latest if not specified).

#### Signature

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
        include_evidence: Include evidence quotes (default false for performance)

    Returns:
        dict: Revision metadata + events list

    Examples:
        # Get events for latest revision
        event_list_for_revision("uid_abc123")

        # Get events for specific revision with evidence
        event_list_for_revision("uid_abc123", "rev_def456", include_evidence=True)
    """
```

#### Request Example

```json
{
  "artifact_uid": "uid_abc123",
  "revision_id": null,
  "include_evidence": false
}
```

#### Response Example (Success)

```json
{
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "is_latest": true,
  "events": [
    {
      "event_id": "evt_ghi789",
      "category": "Decision",
      "narrative": "Team decided to adopt freemium pricing",
      "event_time": "2024-03-15T14:30:00Z",
      "subject": {
        "type": "project",
        "ref": "pricing-model"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner"
        }
      ],
      "confidence": 0.95
    },
    {
      "event_id": "evt_jkl012",
      "category": "Commitment",
      "narrative": "Alice committed to Q1 delivery",
      "event_time": "2024-03-15T14:45:00Z",
      "subject": {
        "type": "project",
        "ref": "MVP"
      },
      "actors": [
        {
          "ref": "Alice Chen",
          "role": "owner"
        }
      ],
      "confidence": 0.90
    }
  ],
  "total": 2
}
```

#### Error Example

```json
{
  "error": "Artifact uid_abc123 not found",
  "error_code": "NOT_FOUND"
}
```

---

### 3.4 event_reextract

**Purpose**: Force re-extraction of events for an artifact revision.

#### Signature

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
        dict: Job metadata

    Examples:
        # Re-extract latest revision (only if no job exists or job failed)
        event_reextract("uid_abc123")

        # Force re-extract even if already done
        event_reextract("uid_abc123", force=True)
    """
```

#### Request Example

```json
{
  "artifact_uid": "uid_abc123",
  "revision_id": null,
  "force": true
}
```

#### Response Example (Success - New Job)

```json
{
  "job_id": "job_xyz789",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PENDING",
  "message": "Re-extraction job enqueued"
}
```

#### Response Example (Success - Job Already Exists)

```json
{
  "job_id": "job_xyz789",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PROCESSING",
  "message": "Job already in progress (use force=true to override)"
}
```

#### Response Example (Success - Force Reextract)

```json
{
  "job_id": "job_xyz789",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PENDING",
  "message": "Job reset and re-enqueued (force=true)"
}
```

#### Error Example

```json
{
  "error": "Artifact uid_abc123 not found",
  "error_code": "NOT_FOUND"
}
```

---

### 3.5 job_status

**Purpose**: Check the status of an async extraction job.

#### Signature

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
        dict: Job status details

    Possible statuses:
        - PENDING: Job not yet claimed by worker
        - PROCESSING: Worker is extracting events
        - DONE: Extraction completed successfully
        - FAILED: Terminal failure (max attempts exceeded)

    Examples:
        # Check job status for latest revision
        job_status("uid_abc123")

        # Check specific revision
        job_status("uid_abc123", "rev_def456")
    """
```

#### Request Example

```json
{
  "artifact_uid": "uid_abc123",
  "revision_id": null
}
```

#### Response Example (Success - DONE)

```json
{
  "job_id": "job_xyz789",
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

#### Response Example (Success - PROCESSING)

```json
{
  "job_id": "job_xyz789",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "PROCESSING",
  "attempts": 1,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:01:00Z",
  "locked_by": "event-worker-1",
  "last_error_code": null,
  "last_error_message": null,
  "next_run_at": null
}
```

#### Response Example (Success - FAILED)

```json
{
  "job_id": "job_xyz789",
  "artifact_uid": "uid_abc123",
  "revision_id": "rev_def456",
  "status": "FAILED",
  "attempts": 5,
  "max_attempts": 5,
  "created_at": "2024-03-15T14:00:00Z",
  "updated_at": "2024-03-15T14:10:00Z",
  "locked_by": "event-worker-1",
  "last_error_code": "OPENAI_TIMEOUT",
  "last_error_message": "OpenAI API timeout after 30s",
  "next_run_at": null
}
```

#### Error Example

```json
{
  "error": "No job found for artifact uid_abc123",
  "error_code": "NOT_FOUND"
}
```

---

## 4. V3 Modified Tools

### 4.1 artifact_ingest (Modified)

**Changes from V2**:

1. Generate `artifact_uid` and `revision_id`
2. Upsert `artifact_revision` to Postgres
3. Enqueue `event_jobs` row for async extraction
4. Return `revision_id` and `job_status` in response

#### Signature

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
    - Returns job_id and job_status fields

    Args:
        artifact_type: Type of artifact (email, doc, chat, transcript, note)
        source_system: Source system (gmail, slack, drive, manual, etc.)
        content: Full artifact text content
        source_id: Unique ID in source system (optional)
        source_url: URL to original artifact (optional)
        title: Artifact title (optional)
        author: Author name (optional)
        participants: List of participant names (optional)
        ts: Source timestamp (ISO8601) (optional)
        sensitivity: normal, sensitive, highly_sensitive (default: normal)
        visibility_scope: me, team, org, custom (default: me)
        retention_policy: forever, 1y, until_resolved, custom (default: forever)

    Returns:
        dict: Ingestion result with artifact IDs and job status

    Examples:
        # Ingest a document
        artifact_ingest(
            artifact_type="doc",
            source_system="google_drive",
            content="Project proposal...",
            source_id="doc_abc123",
            title="Q1 Project Proposal",
            author="Alice Chen"
        )
    """
```

#### Request Example

```json
{
  "artifact_type": "doc",
  "source_system": "google_drive",
  "content": "Q1 Project Proposal\n\nWe are proposing...",
  "source_id": "doc_abc123",
  "source_url": "https://docs.google.com/document/d/abc123",
  "title": "Q1 Project Proposal",
  "author": "Alice Chen",
  "ts": "2024-03-15T14:00:00Z",
  "sensitivity": "normal",
  "visibility_scope": "team"
}
```

#### Response Example (Success - New Revision)

```json
{
  "artifact_id": "art_9f2c",
  "artifact_uid": "uid_9f2c1a8b4e3d2c1b",
  "revision_id": "rev_4e3d2c1b9f2c1a8b",
  "is_chunked": true,
  "num_chunks": 5,
  "stored_ids": [
    "art_9f2c",
    "art_9f2c::chunk::000::xyz789",
    "art_9f2c::chunk::001::abc123",
    "art_9f2c::chunk::002::def456",
    "art_9f2c::chunk::003::ghi789",
    "art_9f2c::chunk::004::jkl012"
  ],
  "job_id": "job_xyz789",
  "job_status": "PENDING"
}
```

#### Response Example (Success - Unchanged)

```json
{
  "artifact_id": "art_9f2c",
  "artifact_uid": "uid_9f2c1a8b4e3d2c1b",
  "revision_id": "rev_4e3d2c1b9f2c1a8b",
  "is_chunked": true,
  "num_chunks": 5,
  "status": "unchanged",
  "job_status": "N/A",
  "message": "Content unchanged, no re-ingestion needed"
}
```

#### Error Example

```json
{
  "error": "Invalid artifact_type: programming. Must be one of: email, doc, chat, transcript, note",
  "error_code": "INVALID_ARTIFACT_TYPE"
}
```

---

## 5. V2 Unchanged Tools

### 5.1 Memory Tools (4 tools)

| Tool | Signature | V3 Changes |
|------|-----------|------------|
| `memory_store` | `(content, type, confidence, conversation_id?)` | None |
| `memory_search` | `(query, limit?, type?)` | None |
| `memory_list` | `(type?, limit?)` | None |
| `memory_delete` | `(memory_id)` | None |

### 5.2 History Tools (2 tools)

| Tool | Signature | V3 Changes |
|------|-----------|------------|
| `history_append` | `(conversation_id, role, content, turn_index)` | None |
| `history_get` | `(conversation_id, limit?)` | None |

### 5.3 Artifact Tools (3 tools - 1 modified above)

| Tool | Signature | V3 Changes |
|------|-----------|------------|
| `artifact_search` | `(query, limit?, type?)` | None |
| `artifact_get` | `(artifact_id, expand_chunks?)` | None |
| `artifact_delete` | `(artifact_id)` | None |

### 5.4 Hybrid Tools (2 tools)

| Tool | Signature | V3 Changes |
|------|-----------|------------|
| `hybrid_search` | `(query, limit?, include_memory?, expand_neighbors?)` | None |
| `embedding_health` | `()` | None |

---

## 6. Error Handling

### 6.1 Error Response Format

**Structured Error Object**:
```json
{
  "error": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE",
  "details": {
    "field": "additional context"
  }
}
```

### 6.2 Error Codes

| Code | HTTP Status | Description | Example |
|------|-------------|-------------|---------|
| `NOT_FOUND` | 404 | Resource not found | Event evt_abc123 not found |
| `INVALID_PARAMETER` | 400 | Invalid parameter value | limit must be between 1 and 100 |
| `INVALID_CATEGORY` | 400 | Invalid event category | Category must be one of: Commitment, ... |
| `INVALID_ARTIFACT_TYPE` | 400 | Invalid artifact type | Type must be one of: email, doc, ... |
| `MISSING_PARAMETER` | 400 | Required parameter missing | artifact_uid is required |
| `DATABASE_ERROR` | 500 | Database operation failed | Failed to connect to Postgres |
| `EXTRACTION_ERROR` | 500 | Event extraction failed | OpenAI API timeout |
| `INTERNAL_ERROR` | 500 | Unhandled exception | Unexpected error: ... |

### 6.3 Validation Errors

**Category Validation**:
```json
{
  "error": "Invalid category: InvalidCategory. Must be one of: Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder",
  "error_code": "INVALID_CATEGORY",
  "details": {
    "provided": "InvalidCategory",
    "valid_options": [
      "Commitment",
      "Execution",
      "Decision",
      "Collaboration",
      "QualityRisk",
      "Feedback",
      "Change",
      "Stakeholder"
    ]
  }
}
```

**Limit Validation**:
```json
{
  "error": "Invalid limit: 150. Must be between 1 and 100",
  "error_code": "INVALID_PARAMETER",
  "details": {
    "parameter": "limit",
    "provided": 150,
    "min": 1,
    "max": 100
  }
}
```

**Time Format Validation**:
```json
{
  "error": "Invalid time format: 2024-13-01. Must be ISO8601 format",
  "error_code": "INVALID_PARAMETER",
  "details": {
    "parameter": "time_from",
    "provided": "2024-13-01",
    "expected_format": "YYYY-MM-DDTHH:MM:SSZ"
  }
}
```

---

## 7. Versioning Strategy

### 7.1 API Versioning

**V3 Approach**: No URL-based versioning (e.g., `/v3/event_search`).

**Rationale**:
1. MCP tools are self-contained (no shared state across versions)
2. Clients discover tools dynamically via MCP protocol
3. Tool names are unique (e.g., `event_search` is V3-only)
4. V2 tools remain unchanged (backward compatible)

### 7.2 Breaking Changes (Future)

If a breaking change is needed for an existing tool:

**Option 1: New Tool Name**
```python
# V3 (current)
@mcp.tool()
def artifact_ingest(...) -> dict:
    pass

# V4 (hypothetical breaking change)
@mcp.tool()
def artifact_ingest_v2(...) -> dict:
    pass
```

**Option 2: Deprecation Period**
```python
@mcp.tool()
@deprecated(message="Use artifact_ingest_v2 instead", removal_version="5.0")
def artifact_ingest(...) -> dict:
    pass
```

### 7.3 Non-Breaking Changes

**Acceptable Changes** (no new tool needed):
1. Add optional parameters (default values must maintain backward compatibility)
2. Add new fields to response objects (clients ignore unknown fields)
3. Add new error codes (clients should handle unknown codes gracefully)

**Example - Adding Optional Parameter**:
```python
# V3.0
def event_search(query: Optional[str] = None, limit: int = 20) -> dict:
    pass

# V3.1 (non-breaking: new optional parameter)
def event_search(
    query: Optional[str] = None,
    limit: int = 20,
    sort_order: str = "desc"  # NEW: defaults to existing behavior
) -> dict:
    pass
```

### 7.4 Documentation Versioning

**Tool Docstrings**: Include version and changelog
```python
@mcp.tool()
def event_search(...) -> dict:
    """
    Search semantic events with structured filters.

    Version: 3.0
    Added: V3.0 (2025-12-27)
    Changelog:
      - V3.0: Initial release

    Args:
        ...
    """
```

**Architecture Docs**: Date and version in header
```markdown
# API Design: MCP Tools V3

**Version:** 3.0
**Date:** 2025-12-27
**Author:** Senior Architect
```

---

## Appendix: Tool Signature Reference

### Quick Reference Table

| Tool | Parameters | Returns | Performance |
|------|-----------|---------|-------------|
| `event_search` | query?, limit=20, category?, time_from?, time_to?, artifact_uid?, include_evidence=true | {events, total, filters_applied} | < 500ms |
| `event_get` | event_id | {event with evidence} | < 200ms |
| `event_list_for_revision` | artifact_uid, revision_id?, include_evidence=false | {artifact_uid, revision_id, events, total} | < 300ms |
| `event_reextract` | artifact_uid, revision_id?, force=false | {job_id, status, message} | < 100ms |
| `job_status` | artifact_uid, revision_id? | {job details} | < 100ms |
| `artifact_ingest` | artifact_type, source_system, content, ... | {artifact_id, artifact_uid, revision_id, job_id, job_status} | < 1s |

### Python Type Hints

```python
from typing import Optional, List, Dict, Union

# Common types
EventID = str  # UUID or evt_* format
ArtifactUID = str  # uid_* format
RevisionID = str  # rev_* format
JobID = str  # job_* format or UUID

# Event category enum
EventCategory = Literal[
    "Commitment",
    "Execution",
    "Decision",
    "Collaboration",
    "QualityRisk",
    "Feedback",
    "Change",
    "Stakeholder"
]

# Response types
EventSearchResponse = Dict[str, Union[List[Dict], int, Dict]]
EventGetResponse = Dict[str, Union[str, Dict, List[Dict], float]]
JobStatusResponse = Dict[str, Union[str, int, Optional[str]]]
```

---

**End of API Design Document**
