# ADR-004: Two-Collection Model (History/Memory)

**Status:** Accepted

**Date:** 2025-12-25

**Context:**

The memory system needs to store two different types of information:
1. **Verbatim conversation history** - every message turn for context replay
2. **Deliberate memories** - high-value information worth remembering long-term

We need to decide on the collection structure in ChromaDB that best supports these different access patterns and use cases.

Alternative collection structures considered:
1. **Two collections**: Separate `history` and `memory` collections
2. **Single collection**: Store everything in one collection with type metadata
3. **Multiple specialized collections**: `history`, `episodic`, `semantic`, `procedural`, `narrative`
4. **Hierarchical collections**: `history` with subcollections by time period
5. **Hybrid**: History in relational DB (PostgreSQL), memory in vector DB

**Decision:**

We will implement a **two-collection model** for V1:
- **`history` collection**: Stores every conversation turn
- **`memory` collection**: Stores deliberate, high-confidence memories only

**Collection characteristics:**

### history Collection
**Purpose**: Complete conversation replay and recent context
**Write pattern**: Append-only, every message
**Read pattern**: Get last N by conversation_id, chronological order
**Size**: Large (hundreds to thousands per conversation)
**Retention**: Potentially long-term, or summarized later
**Query type**: Metadata filtering (conversation_id, turn_index)
**Example**: "User: I prefer dark mode" (raw message)

### memory Collection
**Purpose**: Semantic recall of important information
**Write pattern**: Selective, gated by confidence and policy
**Read pattern**: Vector similarity search, filtered by metadata
**Size**: Small (tens to hundreds total)
**Retention**: Long-term, high value
**Query type**: Semantic search with metadata filters
**Example**: "User prefers dark mode in applications" (distilled fact)

**Decision rationale:**

1. **Different access patterns**: History needs exact replay (ordered); memory needs semantic search (relevance-ranked)
2. **Different write patterns**: History is append-all; memory is selective
3. **Different scale**: History grows linearly; memory grows sublinearly
4. **Clear semantics**: Developers immediately understand the distinction
5. **Simple V1 scope**: Two collections is minimal viable model
6. **V2 expansion path**: Easy to add more memory collections later

**Consequences:**

**Positive:**
- **Clarity**: Clear distinction between "everything said" vs "worth remembering"
- **Query optimization**: Each collection optimized for its access pattern
- **Storage efficiency**: Memory collection remains small and fast
- **Policy simplicity**: Easy to implement "should this be stored?" logic
- **Testing**: Each collection can be tested independently
- **Future flexibility**: Can add more collections without changing V1 collections

**Negative:**
- **Duplication risk**: Same information might appear in both collections (acceptable tradeoff)
- **Coordination**: Must maintain two collections instead of one
- **Complexity**: More code to manage two collections vs one
- **Data consistency**: No automatic sync between collections (not required for V1)

**Schema design:**

### history Collection Schema
```json
{
  "text": "User: I prefer dark mode",
  "metadata": {
    "conversation_id": "conv_123",
    "role": "user",
    "ts": "2025-12-25T12:00:00Z",
    "turn_index": 42,
    "message_id": "msg_abc123",
    "channel": "web"
  }
}
```

### memory Collection Schema
```json
{
  "text": "User prefers dark mode in applications",
  "metadata": {
    "type": "preference",
    "confidence": 0.85,
    "ts": "2025-12-25T12:01:00Z",
    "conversation_id": "conv_123",
    "entities": "user,ui",
    "source": "chat",
    "tags": "preference,ui"
  }
}
```

**V2 expansion strategy:**

When V1 is validated, we can expand to multi-collection memory model:

```
history             (unchanged - complete transcript)
history_summaries   (new - periodic summaries for context compression)
mem_episodic        (new - "what happened when")
mem_semantic        (new - "facts and knowledge")
mem_procedural      (new - "how to do things")
mem_narrative       (new - "story of the relationship")
```

This expansion:
- Keeps V1 `memory` collection as-is or migrates to `mem_semantic`
- Adds routing logic: `MemoryRouter.get_collection(memory_type)`
- Preserves backward compatibility
- Enables specialized memory types

**Relationship between collections:**

```
┌──────────────────────────────────────────┐
│         User Message arrives             │
└──────────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌─────────────────┐  ┌─────────────────┐
│    ALWAYS       │  │    SOMETIMES    │
│    append to    │  │    extract and  │
│    history      │  │    store in     │
│                 │  │    memory       │
└─────────────────┘  └─────────────────┘
         │                   │
         ▼                   ▼
┌─────────────────┐  ┌─────────────────┐
│    history      │  │    memory       │
│   collection    │  │   collection    │
└─────────────────┘  └─────────────────┘
         │                   │
         └─────────┬─────────┘
                   ▼
         ┌─────────────────────┐
         │  Context assembled  │
         │  for LLM response   │
         └─────────────────────┘
```

**History-to-memory promotion flow (V2):**

In V2, we may add automatic promotion:
1. Summarization job processes history in batches
2. Identifies high-value information
3. Extracts memories with confidence scores
4. Stores in appropriate memory collection
5. Optionally marks history as "summarized"

This is explicitly **out of scope for V1** but the two-collection model enables it.

**Why not more collections in V1?**

We explicitly chose NOT to implement episodic/semantic/procedural/narrative collections in V1 because:
- Adds complexity before validation
- Requires sophisticated routing logic
- Memory type taxonomy may need refinement after usage
- V1 goal is to validate basic persistence and recall
- Can add collections without breaking existing code

**Why not single collection?**

Rejected single collection because:
- Conflates different access patterns (metadata filter vs semantic search)
- Makes policy logic more complex ("store everything" vs "store selectively")
- Harder to optimize (history wants ordered scan, memory wants vector search)
- Confuses semantics (is this "what was said" or "what to remember"?)

**Why not separate databases?**

Considered putting history in PostgreSQL and memory in ChromaDB but rejected because:
- Adds operational complexity (two databases to manage)
- V1 ChromaDB can handle history scale adequately
- Can migrate later if needed without changing agent-app interfaces
- Docker Compose simpler with fewer services

**Collection management:**

Bootstrap ensures both collections exist:
```python
gateway.ensure_collections(["history", "memory"])
```

No complex schema migration needed for V1 (append-only, no updates).

**Related decisions:**
- ADR-002: ChromaDB as Vector Store
- ADR-003: Separation of Concerns

**Review date:** After V1 usage data shows actual collection sizes and access patterns

**Success metrics:**
- History collection: 100-1000 turns per conversation, fast ordered retrieval
- Memory collection: 10-100 total memories, sub-500ms semantic queries
- Clear user mental model of what goes where
