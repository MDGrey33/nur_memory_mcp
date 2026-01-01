# ADR-001: Simplified Interface (V5)

## Status
DRAFT - Awaiting Approval

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Date
2025-12-31

## Context

MCP Memory Server needs a simplified interface that provides:
- Unified content storage (documents, preferences, conversations)
- Full semantic features (embeddings, event extraction, graph expansion)
- Simple 4-tool API

This ADR documents the **clean-slate V5 design** with no legacy support.

### Design Goals

1. **Simple interface** - 4 tools instead of 17
2. **Unified data model** - Everything is "content" with a context tag
3. **Full semantic features** - All content gets embeddings, events, graph
4. **Clean implementation** - No legacy code, no migration paths

## Decision

Unify all content storage into a single conceptual model with 4 tools:

```
remember(content, ...)  → Store anything
recall(query, ...)      → Find anything
forget(id, ...)         → Delete anything
status()                → System health
```

### Key Design Principles

1. **Everything is content** - Unified storage with `context` tag
2. **Smart defaults** - Event extraction and graph expansion on by default
3. **Single ID family** - All content uses `art_` prefix, events use `evt_`
4. **Hide implementation** - Users don't need to know about chunks/revisions
5. **Clean slate** - No legacy IDs, collections, or tools

### Interface Design

#### `remember` - Unified Storage

```python
remember(
    content: str,              # Required
    context: str = None,       # meeting, email, preference, fact, note, conversation
    source: str = None,        # gmail, slack, manual, user
    importance: float = 0.5,   # Affects retrieval ranking
    # Conversation tracking
    conversation_id: str = None,
    turn_index: int = None,
    role: str = None,
    # Advanced metadata (V4 parity)
    sensitivity: str = "normal",
    visibility_scope: str = "me",
    retention_policy: str = "forever",
    ...
)
```

**Behavior:**
- Small content (<900 tokens): Store as single-chunk artifact
- Large content (≥900 tokens): Chunk automatically (900/100 overlap, per Decision 3)
- All content: Extract events, update graph (per Decision 1: Semantic Unification)

#### `recall` - Unified Retrieval

```python
recall(
    query: str = None,         # Semantic search
    id: str = None,            # Direct lookup
    context: str = None,       # Filter by type
    expand: bool = True,       # Graph expansion
    # Conversation retrieval
    conversation_id: str = None,
    # Advanced graph params (V4 parity)
    graph_budget: int = 10,
    graph_filters: List[str] = ["Decision", "Commitment", "QualityRisk"],
    include_entities: bool = True,
    ...
)
```

**Behavior:**
- Query provided: Hybrid search with graph expansion
- ID provided: Direct lookup with full context
- conversation_id provided: Get conversation history
- Neither: List/filter mode

#### `forget` - Unified Deletion

```python
forget(
    id: str,                   # art_xxx only
    confirm: bool = False,     # Safety flag
)
```

**Behavior:**
- Only accepts `art_` prefixed IDs
- `evt_` IDs return guidance: "Delete source artifact instead"
- Cascades to chunks, events, graph nodes
- Requires explicit confirmation

#### `status` - System Health

```python
status(
    artifact_id: str = None,   # Optional job status check
) -> {version, environment, services, counts, pending_jobs}
```

## Consequences

### Positive

- **Simple interface** - 4 tools with clear purpose
- **Unified mental model** - Everything is content
- **All content gets full features** - Events, graph, embeddings
- **Clean implementation** - No legacy code complexity
- **Simpler LLM tool selection**

### Negative

- **Clean slate** - Existing V4 data/tools not supported
- **Learning curve** - Users need to learn new interface

### Mitigations

- Clear documentation of V5 interface
- Reset procedure documented for fresh starts
- E2E tests verify full feature set works

## Implementation

V5 is implemented in 2 phases (clean slate):

### Phase 1: Implementation
- Build all 4 tools: remember, recall, forget, status
- Create V5 collections: content, chunks
- Implement internal services
- Add conversation turn event gating
- Unit and integration tests

### Phase 2: Cleanup + Reset
- Remove any legacy code (if present)
- Create reset script
- Run E2E acceptance tests
- Verify graph expansion works
- Update documentation

## Test Strategy

### Unit Tests (Core Services)
- `test_config.py` - Configuration
- `test_errors.py` - Error handling
- `test_models.py` - Data models
- `test_chroma_client.py` - ChromaDB wrapper
- `test_collections.py` - V5 collections (content, chunks)
- `test_chunking_service.py` - Chunking logic
- `test_embedding_service.py` - OpenAI embeddings
- `test_retrieval_service.py` - RRF fusion

### Integration Tests (V5 Tools)
- `test_remember.py` - Remember tool
- `test_recall.py` - Recall tool
- `test_forget.py` - Forget tool
- `test_status.py` - Status tool

### E2E Acceptance Tests
- `test_v5_e2e.py` - Full system tests including graph expansion

## Alternatives Considered

### Alternative 1: Keep Separate with Feature Parity
Add event extraction to memories, keep 17 tools.

**Rejected:** Still too many tools, increases code complexity.

### Alternative 2: Hybrid Approach
Add new tools but keep old ones permanently.

**Rejected:** Maintenance burden, confusing for users.

### Alternative 3: More Aggressive Reduction (2 tools)
Just `store` and `find`.

**Rejected:** Need delete and status for completeness.

### Alternative 4: Drop Advanced Parameters
Simplify to 3-4 params per tool.

**Rejected:** Power users need V4 parity for graph control, sensitivity, etc.

## References

- V5 Specification: `.claude-workspace/specs/v5-specification.md`
- Phase 1: `.claude-workspace/specs/v5-phases/phase-1-implementation.md`
- Phase 2: `.claude-workspace/specs/v5-phases/phase-2-cleanup.md`
