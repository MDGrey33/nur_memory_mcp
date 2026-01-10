# V8 Spec: Explicit Edge Definitions

**Version**: 8.0.0
**Status**: SUPERSEDED by V9
**Created**: 2026-01-10
**Closed**: 2026-01-10

> **Note**: This spec is closed. Core implementation complete. Remaining API items (`edge_types`, `include_edges`) moved to [V9](./v9-consolidation.md).

---

## Problem Statement

The current graph expansion (V7) uses implicit relationships via SQL joins on `event_actor` and `event_subject` tables. While functional for basic entity co-occurrence, it lacks:

1. **Named relationships**: Can't distinguish "Bob manages Alice" from "Bob met Alice"
2. **Decision chains**: No way to link decisions to their outcomes
3. **Timeline causality**: Can't express "Event A caused Event B"
4. **Direct entity links**: Relationships exist only through shared events

### Current Benchmark Results

| Metric | Score | Notes |
|--------|-------|-------|
| Graph Connection F1 | 0.51 | Finding entities via events |
| Graph Doc F1 | 0.27 | Finding related documents |

The low Doc F1 indicates graph expansion isn't surfacing the right related content.

---

## Proposed Solution

### Explicit Edge Model

```
┌─────────────────────────────────────────────────────────────────┐
│                     KNOWLEDGE GRAPH                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   NODES                           EDGES                          │
│   ─────                           ─────                          │
│   (Bob:Person)  ───MANAGES────>   (Alice:Person)                │
│   (Bob:Person)  ───COMMITTED────> (API v2:Deliverable)          │
│   (Meeting:Event) ─DECIDED────>   (Use Postgres:Decision)       │
│   (Decision A)  ───CAUSED─────>   (Refactor B:Event)            │
│   (Sprint 1)    ───PRECEDED───>   (Sprint 2:Event)              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Edge Categories

| Category | Edge Types | Use Case |
|----------|------------|----------|
| **Interpersonal** | MANAGES, REPORTS_TO, WORKS_WITH, COLLABORATES_WITH | Org structure queries |
| **Ownership** | OWNS, ASSIGNED_TO, RESPONSIBLE_FOR, CONTRIBUTED_TO | Accountability |
| **Decisions** | DECIDED, APPROVED, REJECTED, DEFERRED, OVERRULED | Decision audit trails |
| **Causality** | CAUSED, ENABLED, BLOCKED, TRIGGERED, RESOLVED | Root cause analysis |
| **Temporal** | PRECEDED, FOLLOWED, DURING, SUPERSEDED | Timeline reconstruction |
| **Reference** | MENTIONED, DISCUSSED, CITED, RELATES_TO | Context expansion |

### Schema Changes

```sql
-- New table: explicit edges between entities
CREATE TABLE entity_edge (
    edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source and target entities
    source_entity_id UUID NOT NULL REFERENCES entity(entity_id),
    target_entity_id UUID NOT NULL REFERENCES entity(entity_id),

    -- Relationship definition
    relationship_type VARCHAR(50) NOT NULL,  -- e.g., "MANAGES", "DECIDED"
    relationship_name TEXT,                   -- Optional custom label

    -- Provenance
    artifact_uid TEXT NOT NULL,              -- Document where edge was extracted
    revision_id TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.8,

    -- Evidence
    evidence_quote TEXT,                     -- Supporting text span

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CHECK (source_entity_id != target_entity_id),
    UNIQUE (source_entity_id, target_entity_id, relationship_type, artifact_uid)
);

-- Indexes for traversal
CREATE INDEX idx_entity_edge_source ON entity_edge(source_entity_id);
CREATE INDEX idx_entity_edge_target ON entity_edge(target_entity_id);
CREATE INDEX idx_entity_edge_type ON entity_edge(relationship_type);
```

### Extraction Prompt Changes

Current (V7):
```
Extract events with actors and subjects...
```

Proposed (V8):
```
Extract entities and their relationships from the text.

For each relationship found, provide:
- source_entity: The entity performing or initiating
- target_entity: The entity receiving or affected
- relationship_type: One of [MANAGES, WORKS_WITH, DECIDED, COMMITTED_TO, ...]
- evidence: Quote from text supporting this relationship

Example:
Text: "Bob assigned the API task to Alice, who committed to finishing by Friday."

Relationships:
1. {source: "Bob", target: "Alice", type: "ASSIGNED_TO", evidence: "Bob assigned the API task to Alice"}
2. {source: "Alice", target: "API task", type: "COMMITTED_TO", evidence: "Alice committed to finishing by Friday"}
```

---

## Implementation Plan

### Phase 1: Schema & Extraction (3-4 days)

1. Add `entity_edge` table to init.sql
2. Create edge extraction prompt
3. Update `event_extraction_service.py` to extract edges
4. Store edges in new table

### Phase 2: Retrieval Integration (2-3 days)

1. Update `retrieval_service.py` graph expansion to use edges
2. Add edge-based traversal queries
3. Score results by edge relevance

### Phase 3: Query Capabilities (2-3 days)

1. Add relationship-type filtering to recall()
2. Support queries like "Who does Bob manage?"
3. Timeline queries using temporal edges

---

## API Changes

### recall() additions

```python
recall(
    query="...",
    # Existing params...

    # New V8 params
    edge_types: List[str] = None,      # Filter by relationship type
    traverse_depth: int = 1,            # How many hops to traverse
    include_edges: bool = False,        # Return edge details
)
```

### Response additions

```json
{
  "results": [...],
  "related": [...],
  "entities": [...],
  "edges": [
    {
      "source": "Bob Smith",
      "target": "Alice Chen",
      "type": "MANAGES",
      "confidence": 0.9,
      "evidence": "Bob oversees Alice's work on the API"
    }
  ]
}
```

---

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Graph Connection F1 | 0.51 | 0.70 |
| Graph Doc F1 | 0.27 | 0.50 |
| New: Edge Precision | N/A | 0.60 |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM extraction cost (2x calls) | Batch edge extraction with event extraction |
| Edge explosion (too many edges) | Confidence threshold, limit per document |
| Schema migration | No prod data, clean reset acceptable |

---

## Dependencies

- V7.3 dynamic categories (completed)
- V7.3 temporal queries (completed)
- Benchmark infrastructure (in place)

---

## References

- [Cognee KnowledgeGraph model](https://github.com/topoteretes/cognee)
- [V7.3 Research: Category Expansion](./v7.3-category-expansion-research.md)
- [Entity Event Knowledge Graphs Whitepaper](https://allegrograph.com/wp-content/uploads/2020/06/Entity-Event-Knowledge-Graphs-White-Paper-v692020.pdf)
