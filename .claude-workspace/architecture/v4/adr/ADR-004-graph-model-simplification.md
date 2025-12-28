# ADR-004: Graph Model Simplification

**Status:** Accepted
**Date:** 2025-12-28
**Deciders:** Senior Architect, Technical PM
**Context Level:** V4 Graph-backed Context Expansion

---

## Context

V4 introduces a property graph to enable context expansion in `hybrid_search`. Early design discussions considered several node types:

- `Entity` - Canonical entities (people, orgs, projects)
- `Event` - Semantic events (decisions, commitments, etc.)
- `Revision` - Artifact revisions (snapshots of documents)
- `Artifact` - Logical documents

The question is: **how complex should the graph model be?**

### V4 Use Case

The primary use case for the graph is **1-hop traversal from query results**:

```
User searches for "pricing decision"
    |
    v
Primary results: [Event A, Event B]
    |
    v
Graph expansion: Find events connected via shared entities
    |
    v
Query: Which entities are in Event A/B?
       What other events involve those entities?
    |
    v
Related context: [Event C, Event D] (same actors/subjects)
```

### Graph Model Options

#### Option A: Full Document Graph

Include all document relationships in the graph.

```cypher
(:Artifact)-[:HAS_REVISION]->(:Revision)
(:Revision)-[:CONTAINS]->(:Event)
(:Event)-[:ACTED_IN]-(:Entity)
(:Event)-[:ABOUT]->(:Entity)
(:Entity)-[:POSSIBLY_SAME]->(:Entity)
```

**Pros:**
- Complete document lineage in graph
- Can query "all events in this revision" via graph
- Natural model for document-centric queries

**Cons:**
- More nodes (Artifact, Revision per document)
- More edges (HAS_REVISION, CONTAINS)
- Complex MERGE operations for each document
- Redundant: revision info already on Event node properties

**Node/Edge Count (per document):**
- 1 Artifact node
- 1 Revision node
- ~5 Event nodes (average)
- ~3 Entity nodes (average)
- 2 extra edges (HAS_REVISION, CONTAINS)

#### Option B: Event-Entity Graph Only

Only model the relationships needed for entity-centric traversal.

```cypher
(:Entity)-[:ACTED_IN {role}]->(:Event)
(:Event)-[:ABOUT]->(:Entity)
(:Entity)-[:POSSIBLY_SAME {confidence, reason}]->(:Entity)
```

Event nodes include revision information as properties:
```cypher
(:Event {
    event_id,
    category,
    narrative,
    artifact_uid,      -- Identifies document
    revision_id,       -- Identifies version
    event_time,
    confidence
})
```

**Pros:**
- Simpler graph (only Entity and Event nodes)
- Fewer MERGE operations
- Revision info queryable via Event properties
- Sufficient for 1-hop expansion use case

**Cons:**
- "Events in same revision" requires property filter, not graph traversal
- No explicit document structure in graph

**Node/Edge Count (per document):**
- ~5 Event nodes
- ~3 Entity nodes
- 0 extra structural nodes

---

## Decision

**We will implement Option B: Event-Entity Graph Only (No Revision Nodes)**

### Rationale

1. **YAGNI (You Aren't Gonna Need It)**: The V4 use case is entity-centric traversal: "find events connected via shared actors/subjects". We don't need document-centric graph queries like "traverse from Artifact to all its Events" - that's efficiently done via SQL.

2. **"Events in Same Revision" is Trivial Without Graph**:
   ```sql
   SELECT * FROM semantic_event
   WHERE artifact_uid = $uid AND revision_id = $rev
   ```
   Adding Revision nodes to the graph provides no benefit over this simple query.

3. **Reduced Complexity**:
   - 2 node types instead of 4
   - 3 edge types instead of 5
   - Simpler MERGE operations
   - Fewer indexes to maintain

4. **Event Properties Suffice**: By storing `artifact_uid` and `revision_id` on Event nodes, we preserve all document context needed for queries:
   ```cypher
   // Find events from same document
   MATCH (e:Event {artifact_uid: $uid, revision_id: $rev})
   RETURN e
   ```

5. **Future Extensibility**: If we later need document-centric graph queries, we can add Revision nodes without breaking existing queries. The Event-Entity structure is forward-compatible.

---

## Implementation Details

### Graph Node Types

#### Entity Node

```cypher
(:Entity {
    entity_id: UUID,        -- Primary key, matches entity.entity_id
    canonical_name: STRING,  -- Display name
    type: STRING,            -- person|org|project|object|place|other
    role: STRING,            -- Job title (nullable)
    organization: STRING     -- Company affiliation (nullable)
})
```

**Index Strategy:**
- Primary index on `entity_id` (for MERGE lookups)
- Secondary index on `type, canonical_name` (for name-based queries)

#### Event Node

```cypher
(:Event {
    event_id: UUID,          -- Primary key, matches semantic_event.event_id
    category: STRING,        -- Commitment|Decision|etc.
    narrative: STRING,       -- Event summary
    artifact_uid: STRING,    -- Document identifier (for filtering)
    revision_id: STRING,     -- Version identifier (for filtering)
    event_time: TIMESTAMP,   -- When event occurred (nullable)
    confidence: FLOAT        -- Extraction confidence
})
```

**Index Strategy:**
- Primary index on `event_id` (for MERGE lookups)
- Composite index on `artifact_uid, revision_id` (for document queries)
- Index on `category` (for category filtering)

### Graph Edge Types

#### ACTED_IN (Entity -> Event)

```cypher
(:Entity)-[:ACTED_IN {role: STRING}]->(:Event)
```

Role values: `owner`, `contributor`, `reviewer`, `stakeholder`, `other`

**Semantics**: The entity performed an action in this event.

#### ABOUT (Event -> Entity)

```cypher
(:Event)-[:ABOUT]->(:Entity)
```

**Semantics**: The event is about this entity (subject of the event).

#### POSSIBLY_SAME (Entity -> Entity)

```cypher
(:Entity)-[:POSSIBLY_SAME {
    confidence: FLOAT,
    reason: STRING
}]->(:Entity)
```

**Semantics**: These two entities might be the same, but the system was uncertain. Used for the manual review queue.

### Example Graph for a Document

Document: "Alice Chen decided to use Postgres for the pricing service."

**Entities:**
- Alice Chen (person, Engineering Manager)
- Postgres (project, database)
- Pricing Service (project)

**Events:**
- Decision: "Team decided to use Postgres for backend" (confidence: 0.95)

**Graph:**
```
(:Entity {name: "Alice Chen"})
        |
        | ACTED_IN {role: "owner"}
        v
(:Event {category: "Decision", narrative: "..."})
        |
        | ABOUT
        v
(:Entity {name: "Pricing Service"})
```

### Queries That Work Without Revision Nodes

| Query | SQL | Cypher |
|-------|-----|--------|
| Events in same revision | `WHERE artifact_uid = $uid AND revision_id = $rev` | `MATCH (e:Event {artifact_uid: $uid, revision_id: $rev})` |
| Events by same actor | N/A (requires join) | `MATCH (actor)-[:ACTED_IN]->(e:Event)` |
| 1-hop expansion | Complex recursive CTE | Simple 2-hop pattern |

---

## Consequences

### Positive

1. **Simpler Graph**: 2 node types, 3 edge types (vs. 4 and 5)
2. **Faster Upserts**: Fewer MERGE operations per document
3. **Lower Storage**: ~40% fewer nodes and edges
4. **Easier Debugging**: Smaller graph is easier to visualize and reason about
5. **Same Query Power**: All V4 use cases supported

### Negative

1. **No Document Structure in Graph**: Can't traverse "Artifact -> Revisions -> Events" in graph
2. **Property Filtering**: "Same revision" queries use property filters instead of edge traversal
3. **Future Constraints**: If we need document-centric graph queries, must add nodes later

### Mitigations

| Concern | Mitigation |
|---------|------------|
| Need document traversal | SQL queries on artifact_revision + semantic_event |
| Want Revision nodes later | Forward-compatible: can add without breaking existing queries |
| Property filter performance | Composite index on (artifact_uid, revision_id) |

---

## Comparison: With vs. Without Revision Nodes

### Graph Size (1000 documents, 5 events/doc, 3 entities/doc)

| Model | Nodes | Edges |
|-------|-------|-------|
| With Revision nodes | 1000 Artifacts + 1000 Revisions + 5000 Events + 3000 Entities = **10,000** | ~7000 ACTED_IN/ABOUT + 2000 HAS_REVISION + 5000 CONTAINS = **~14,000** |
| Without Revision nodes | 5000 Events + 3000 Entities = **8,000** | ~7000 ACTED_IN/ABOUT = **~7,000** |

**Result**: 20% fewer nodes, 50% fewer edges without Revision nodes.

### Query Complexity: "Find events related to Query Result via shared actors"

**With Revision nodes:**
```cypher
MATCH (seed:Event) WHERE seed.event_id IN $seed_ids
OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
MATCH (actor)-[:ACTED_IN]->(related:Event)
WHERE NOT related.event_id IN $seed_ids
RETURN related
```

**Without Revision nodes:** (Identical query)
```cypher
MATCH (seed:Event) WHERE seed.event_id IN $seed_ids
OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
MATCH (actor)-[:ACTED_IN]->(related:Event)
WHERE NOT related.event_id IN $seed_ids
RETURN related
```

**Result**: No difference in query complexity for entity-centric traversal.

---

## Related ADRs

- **ADR-001**: Entity Resolution Strategy
- **ADR-002**: Graph Database Choice (Apache AGE)
- **ADR-003**: Entity Resolution Timing

---

## References

- V4 Brief: `/v4.md`
- V4 Specification: `/.claude-workspace/specs/v4-specification.md`
