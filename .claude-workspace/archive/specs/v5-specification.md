# MCP Memory Server V5: Simplified Interface Specification

**Version:** 5.0.0
**Date:** 2026-01-01
**Status:** IMPLEMENTED

---

## 1. Executive Summary

V5 provides a simplified MCP interface with **4 tools**, unified storage, and full semantic features (events, graph expansion).

### Interface

```
remember(content, context?, ...)  → Store anything
recall(query?, id?, expand?, ...) → Find anything (with graph expansion)
forget(id, confirm)               → Delete anything (cascades)
status()                          → System health
```

### Architecture

| Component | V5 Implementation |
|-----------|-------------------|
| **Tools** | 4 (remember, recall, forget, status) |
| **Collections** | 2 ChromaDB (content, chunks) |
| **Database** | PostgreSQL with pgvector |
| **Graph** | SQL joins on entity tables (no AGE) |
| **ID Format** | `art_` + SHA256[:12] |

---

## 2. Tools

### 2.1 `remember()` - Store Content

```python
remember(
    content: str,                    # Required: text to store
    context: str = None,             # meeting, email, note, preference, fact, conversation
    source: str = None,              # gmail, slack, manual, user
    importance: float = 0.5,         # 0.0-1.0
    title: str = None,
    author: str = None,
    participants: List[str] = None,
    date: str = None,                # ISO8601
    conversation_id: str = None,     # For context="conversation"
    turn_index: int = None,
    role: str = None,                # user, assistant, system
) -> {id, summary, events_queued, context, is_chunked, num_chunks, token_count}
```

**Behavior:**
- Content >= 900 tokens: Chunked with 100 token overlap
- All content triggers event extraction (except short conversation turns < 100 tokens)
- Idempotent: Same content → same ID (deduplication)

### 2.2 `recall()` - Find Content

```python
recall(
    query: str = None,               # Semantic search
    id: str = None,                  # Direct lookup (art_xxx or evt_xxx)
    context: str = None,             # Filter by type
    limit: int = 10,
    expand: bool = True,             # Graph expansion (default ON)
    include_events: bool = True,
    include_entities: bool = True,
    graph_budget: int = 10,          # Max related items
    conversation_id: str = None,     # Get conversation history
) -> {results, related, entities, total_count}
```

**Graph Expansion:**
When `expand=True` (default):
1. Primary search finds matching documents
2. Extract events from primary results
3. Find entities (actors/subjects) in those events
4. Find OTHER events with same entities
5. Return as `related[]` with connection reason

**Response Structure:**
```json
{
  "results": [...],           // Primary matches
  "related": [                // Graph-expanded context
    {
      "category": "QualityRisk",
      "reason": "same_actor:Alice Chen",
      "summary": "Bob is waiting on schema review from Alice...",
      "evidence": [{"quote": "...", "start_char": 146, "end_char": 194}]
    }
  ],
  "entities": [               // Discovered entities
    {"name": "Alice Chen", "type": "person", "mention_count": 4}
  ],
  "total_count": 8
}
```

### 2.3 `forget()` - Delete Content

```python
forget(
    id: str,                         # art_xxx only
    confirm: bool = False,           # Safety flag (required)
) -> {deleted, id, cascade: {chunks, events, entities}}
```

**Behavior:**
- Only accepts `art_` IDs
- `evt_` IDs return guidance: "Delete source artifact instead"
- Cascades to: chunks, events, evidence, entity mentions

### 2.4 `status()` - System Health

```python
status(
    artifact_id: str = None,         # Check specific job status
) -> {version, healthy, services, counts, pending_jobs}
```

---

## 3. Data Model

### 3.1 ChromaDB Collections

| Collection | Purpose |
|------------|---------|
| `content` | All stored content (full documents, preferences, conversations) |
| `chunks` | Chunks for large content (>900 tokens) |

### 3.2 PostgreSQL Tables

| Table | Purpose |
|-------|---------|
| `artifact_revision` | Immutable artifact tracking |
| `event_jobs` | Async extraction job queue |
| `semantic_event` | Extracted semantic events |
| `event_evidence` | Evidence spans linking events to source |
| `entity` | Canonical entity registry |
| `entity_alias` | Known aliases per entity |
| `entity_mention` | Surface form occurrences |
| `event_actor` | Actor relationships (entity → event) |
| `event_subject` | Subject relationships (entity → event) |

### 3.3 Valid Context Types

```python
VALID_CONTEXTS = [
    # Document types (chunked, full extraction)
    "meeting", "email", "document", "chat", "transcript", "note",
    # Memory types (small, single-chunk)
    "preference", "fact", "decision", "project",
    # Conversation (timestamped turns)
    "conversation"
]
```

---

## 4. Graph Expansion Algorithm

```
Query: "What did Alice commit to?"
         │
         ▼
┌─────────────────────────────┐
│  1. Primary Search          │
│  ChromaDB semantic search   │
│  → 4 matching documents     │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  2. Get Seed Events         │
│  artifact_id → artifact_uid │
│  → semantic_event           │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  3. Get Seed Entities       │
│  event_actor + event_subject│
│  → Alice Chen, Bob Martinez │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  4. Expand via Entities     │
│  Find OTHER events with     │
│  same actors/subjects       │
│  → 4 related events         │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  5. Return Results          │
│  results: [...primary...]   │
│  related: [...expanded...]  │
│  entities: [...discovered...│
└─────────────────────────────┘
```

---

## 5. Infrastructure

### 5.1 Docker Services

| Service | Image | Purpose |
|---------|-------|---------|
| postgres | pgvector/pgvector:pg16 | Events, entities, jobs |
| chroma | chromadb/chroma:0.5.23 | Vector storage |
| mcp-server | mcp-memory-server:v5 | MCP API |
| event-worker | mcp-memory-server:v5 | Async extraction |

### 5.2 Quick Start

```bash
cd .claude-workspace/deployment
docker compose up -d
# Server at http://localhost:3100/mcp/
```

### 5.3 Running Tests

```bash
# Unit + Integration tests
cd .claude-workspace/implementation/mcp-server
source .venv/bin/activate
pytest

# E2E tests (requires running Docker)
MCP_URL="http://localhost:3100/mcp/" pytest ../../tests/v5/e2e/ --run-e2e -v
```

---

## 6. Legacy Tools

V5 coexists with 17 legacy tools. See [Tool Consolidation Proposal](./tool-consolidation-proposal.md) for consolidation options.

**Recommendation:** Disable legacy tools (comment out `@mcp.tool()` decorators) to reduce context bloat by ~80%.

---

## 7. Test Coverage

| Category | Tests | Status |
|----------|-------|--------|
| V5 Unit | 19 | PASS |
| V5 Integration | 61 | PASS |
| V5 E2E | 11 | PASS |
| **Total** | **223** | **PASS** |

---

## 8. Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Semantic Unification | All content triggers extraction | No feature disparities |
| Clean Slate | No legacy support | Eliminates complexity |
| Chunking | 900 tokens, 100 overlap | Proven defaults |
| Event Deletion | Guide to source | Events are derived data |
| Graph Engine | Postgres SQL joins | No AGE dependency |
| ID Format | art_ + SHA256[:12] | Content-based dedup |

---

## 9. Files

| File | Purpose |
|------|---------|
| `src/server.py` | V5 tools (lines 1574-2414) |
| `src/storage/collections.py` | V5 collections (lines 254-419) |
| `src/services/retrieval_service.py` | hybrid_search_v5, graph expansion |
| `deployment/docker-compose.yml` | Infrastructure config |
| `deployment/init.sql` | Database schema |
