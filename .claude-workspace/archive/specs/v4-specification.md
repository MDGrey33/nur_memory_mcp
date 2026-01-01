# MCP Memory Server V4: Technical Specification
# Graph-backed Context Expansion & Quality-First Entity Resolution

**Version:** 4.0
**Date:** 2025-12-28
**Author:** Technical PM
**Status:** Draft - Pending Architecture Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Functional Requirements](#2-functional-requirements)
3. [Data Model](#3-data-model)
4. [API Contracts](#4-api-contracts)
5. [Processing Pipeline](#5-processing-pipeline)
6. [Graph Stack & Schema](#6-graph-stack--schema)
7. [Dependencies](#7-dependencies)
8. [Acceptance Criteria](#8-acceptance-criteria)
9. [Risks & Mitigations](#9-risks--mitigations)
10. [Implementation Sequence](#10-implementation-sequence)

---

## 1. Executive Summary

### 1.1 What We're Building

V4 transforms `hybrid_search` from a text-retrieval tool into **"portable memory"** by adding:

1. **Graph-backed context expansion** - When searching for "Alice's decisions", automatically surface related events involving Alice from other documents
2. **Quality-first entity resolution** - Correctly identify that "Alice Chen", "A. Chen", and "Alice" are the same person (while distinguishing "Alice Chen at Acme" from "Alice Chen at OtherCorp")
3. **Progressive disclosure** - Return `expand_options` so assistants can offer users "I can also show related context from other documents"

**Key Constraint:** No new user-facing tools. All enhancements are behind the existing `hybrid_search` API with optional parameters.

### 1.2 Why V4?

V3 built a semantic events system that extracts structured events (decisions, commitments, etc.) from documents. However:

- **Events exist in silos** - Searching for "pricing decision" only returns events from documents that mention "pricing", not related discussions by the same people
- **Entity references are strings** - "Alice" in doc A and "Alice Chen" in doc B are not linked, making cross-document context impossible
- **No relationship awareness** - Cannot answer "What else has Alice been involved in?"

V4 adds the relationship layer that makes the semantic events truly interconnected.

### 1.3 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Entity dedup accuracy | > 95% correct merges | Manual review of 100 entity pairs |
| False merge rate | < 2% | Different people incorrectly merged |
| Graph expansion latency | < 300ms additional | P95 for `graph_expand=true` |
| Backward compatibility | 100% | V3 output unchanged when `graph_expand=false` |
| E2E test pass rate | 100% | All 10 defined tests passing |

### 1.4 Scope Boundaries

**In Scope:**
- Entity extraction with context clues (role, org, email)
- Entity deduplication (embedding + LLM confirmation)
- Graph materialization in Postgres (Apache AGE)
- Enhanced `hybrid_search` with graph expansion
- Debug/health endpoints for graph status

**Out of Scope:**
- New user-facing MCP tools
- Multi-hop graph traversal (V4 limited to 1-hop)
- Real-time graph updates (batch via job queue)
- Entity merge UI (manual review stays in database)

---

## 2. Functional Requirements

### 2.1 Entity Extraction with Context Clues

**FR-2.1.1:** The extraction prompt SHALL return an `entities_mentioned` array alongside the existing `events` array.

**FR-2.1.2:** Each entity mention SHALL include:
- `surface_form` - Exact text as it appeared in document
- `canonical_suggestion` - LLM's best guess at the canonical name
- `type` - One of: `person`, `org`, `project`, `object`, `place`, `other`
- `context_clues` - Object with optional `role`, `org`, `email` fields
- `aliases_in_doc` - Other surface forms in the same document referring to this entity
- `confidence` - Float 0.0-1.0 indicating extraction confidence

**FR-2.1.3:** Character offsets SHALL be included when determinable from chunk position.

**Example extraction output:**
```json
{
  "events": [...],
  "entities_mentioned": [
    {
      "surface_form": "Alice Chen",
      "canonical_suggestion": "Alice Chen",
      "type": "person",
      "context_clues": {
        "role": "Engineering Manager",
        "org": "Acme Corp",
        "email": "achen@acme.com"
      },
      "aliases_in_doc": ["Alice", "A. Chen"],
      "confidence": 0.95,
      "start_char": 150,
      "end_char": 160
    }
  ]
}
```

### 2.2 Entity Deduplication (Embedding + LLM Confirmation)

**FR-2.2.1:** Entity deduplication SHALL use a two-phase approach:

**Phase A - Candidate Generation:**
- Generate embedding from context string: `"{canonical_name}, {type}, {role}, {org}"`
- Query existing entities of SAME TYPE with cosine similarity > 0.85
- If no candidates found, create new entity
- If candidates found, proceed to Phase B

**Phase B - LLM Confirmation:**
- For each candidate pair, call LLM with both entity contexts
- LLM returns one of: `same`, `different`, `uncertain`
- `same` - Merge: link new mention to existing entity, add alias
- `different` - Create new entity
- `uncertain` - Create new entity, add `POSSIBLY_SAME` graph edge

**FR-2.2.2:** The LLM confirmation prompt SHALL include:
- Both entity names
- Both entity types
- All available context (role, org, email)
- Source document titles for disambiguation

**FR-2.2.3:** Cost budget per entity dedup: ~$0.001 (using gpt-4o-mini)

### 2.3 Graph Materialization

**FR-2.3.1:** The system SHALL materialize a property graph using Apache AGE extension inside Postgres.

**FR-2.3.2:** Graph SHALL be created as a separate job (`graph_upsert`) enqueued after `extract_events` completes.

**FR-2.3.3:** Graph operations SHALL be idempotent using Cypher `MERGE` semantics.

**FR-2.3.4:** Graph nodes:
- `Entity` - Represents a canonical entity (person, org, project, etc.)
- `Event` - Represents a semantic event

**FR-2.3.5:** Graph edges:
- `ACTED_IN` - Entity acted in an event (with `role` property)
- `ABOUT` - Event is about an entity (subject relationship)
- `POSSIBLY_SAME` - Two entities that might be the same (uncertain merge)

### 2.4 Enhanced hybrid_search with graph_expand

**FR-2.4.1:** `hybrid_search` SHALL accept new optional parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `graph_expand` | bool | false | Enable graph-based context expansion |
| `graph_depth` | int | 1 | Expansion depth (only 1 supported in V4) |
| `graph_budget` | int | 10 | Max additional related items |
| `graph_seed_limit` | int | 5 | How many primary results to use as expansion seeds |
| `graph_filters` | list[str] | null | Category filter (null = all) |
| `include_entities` | bool | true | Include entity list when graph_expand=true |

**FR-2.4.2:** When `graph_expand=false`, output SHALL be identical to V3 (backward compatible).

**FR-2.4.3:** When `graph_expand=true`, output SHALL include three additional sections:
- `related_context` - Graph-derived related items
- `entities` - Canonical entities involved in results
- `expand_options` - Available expansion toggles

**FR-2.4.4:** `related_context` items SHALL have standardized `reason` values:
- `same_actor:{name}` - Connected via shared actor
- `same_subject:{name}` - Connected via shared subject
- `1_hop_via:{category}` - Connected through graph traversal

**FR-2.4.5:** `expand_options` SHALL always be returned (even when `graph_expand=false`) to enable progressive disclosure.

### 2.5 Debug/Health Endpoints

**FR-2.5.1:** `graph_health` internal endpoint SHALL return:
- AGE extension status (enabled/disabled)
- Node counts by label (Entity, Event)
- Edge counts by type (ACTED_IN, ABOUT, POSSIBLY_SAME)
- POSSIBLY_SAME edge count (pending review queue size)

**FR-2.5.2:** `entity_review_queue` internal endpoint SHALL return entities with `needs_review=true`.

**FR-2.5.3:** `job_status` (existing) SHALL include `graph_upsert` job type.

---

## 3. Data Model

### 3.1 New Postgres Tables

V4 adds 5 new tables to the existing V3 schema:

#### 3.1.1 `entity` - Canonical Entity Registry

```sql
CREATE TABLE entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person', 'org', 'project', 'object', 'place', 'other'
    )),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,  -- lowercase, stripped for matching

    -- Rich context for deduplication (nullable)
    role TEXT,           -- e.g., "Engineering Manager"
    organization TEXT,   -- e.g., "Acme Corp"
    email TEXT,          -- e.g., "alice@acme.com"

    -- Embedding for similarity-based dedup candidate search
    context_embedding vector(3072),

    -- Provenance
    first_seen_artifact_uid TEXT NOT NULL,
    first_seen_revision_id TEXT NOT NULL,

    -- For manual review queue (uncertain merges)
    needs_review BOOLEAN DEFAULT false,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX entity_type_name_idx ON entity(entity_type, normalized_name);
CREATE INDEX entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX entity_needs_review_idx ON entity(needs_review) WHERE needs_review = true;
```

**Key Fields:**
- `normalized_name` - Lowercased, whitespace-normalized for exact match lookups
- `context_embedding` - vector(3072) using OpenAI `text-embedding-3-large`
- `needs_review` - Set true when LLM returns "uncertain" decision
- `first_seen_*` - Provenance tracking for entity creation

#### 3.1.2 `entity_alias` - Known Aliases Per Entity

```sql
CREATE TABLE entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(entity_id, normalized_alias)
);

CREATE INDEX entity_alias_lookup_idx ON entity_alias(normalized_alias);
```

**Purpose:** Track all known ways an entity is referenced. When "A. Chen" is merged with "Alice Chen", "A. Chen" becomes an alias.

#### 3.1.3 `entity_mention` - Every Surface Form Occurrence

```sql
CREATE TABLE entity_mention (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    surface_form TEXT NOT NULL,  -- Exact text as appeared

    -- Character offsets for evidence linking
    start_char INT,
    end_char INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX entity_mention_entity_idx ON entity_mention(entity_id);
CREATE INDEX entity_mention_revision_idx ON entity_mention(artifact_uid, revision_id);
```

**Purpose:** Preserve evidence trail. Every time an entity is mentioned, we record exactly how and where.

#### 3.1.4 `event_actor` - Structured Actor Relationships

```sql
CREATE TABLE event_actor (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN (
        'owner', 'contributor', 'reviewer', 'stakeholder', 'other'
    )),

    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX event_actor_entity_idx ON event_actor(entity_id);
```

**Purpose:** Replaces the JSONB `actors_json` with a normalized, queryable structure. V3's `actors_json` is retained for backward compatibility.

#### 3.1.5 `event_subject` - Structured Subject Relationships

```sql
CREATE TABLE event_subject (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX event_subject_entity_idx ON event_subject(entity_id);
```

**Purpose:** Replaces the JSONB `subject_json` with a normalized structure. V3's `subject_json` is retained for backward compatibility.

### 3.2 Schema Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         V4 DATA MODEL                                    │
└─────────────────────────────────────────────────────────────────────────┘

                        EXISTING V3 TABLES
┌────────────────────┐       ┌────────────────────┐
│  artifact_revision │       │    event_jobs      │
│                    │       │                    │
│  artifact_uid (PK) │       │  job_id (PK)       │
│  revision_id (PK)  │       │  job_type          │  ← NEW: 'graph_upsert'
│  artifact_id       │       │  artifact_uid      │
│  content_hash      │       │  revision_id       │
│  ...               │       │  status            │
└────────────────────┘       └────────────────────┘

┌────────────────────┐       ┌────────────────────┐
│   semantic_event   │       │   event_evidence   │
│                    │       │                    │
│  event_id (PK)     │◄──────│  event_id (FK)     │
│  artifact_uid      │       │  evidence_id (PK)  │
│  revision_id       │       │  quote             │
│  category          │       │  start_char        │
│  narrative         │       │  end_char          │
│  subject_json      │       │                    │
│  actors_json       │       │                    │
│  ...               │       └────────────────────┘
└────────────────────┘
         │
         │ NEW V4 RELATIONSHIPS
         │
         ▼
┌────────────────────┐       ┌────────────────────┐
│    event_actor     │       │   event_subject    │
│                    │       │                    │
│  event_id (FK)     │       │  event_id (FK)     │
│  entity_id (FK)    │◄──────│  entity_id (FK)    │
│  role              │       │                    │
└────────────────────┘       └────────────────────┘
         │                            │
         │                            │
         ▼                            ▼
┌─────────────────────────────────────────────────┐
│                    entity                        │
│                                                  │
│  entity_id (PK)                                 │
│  entity_type                                    │
│  canonical_name                                 │
│  normalized_name                                │
│  role, organization, email                      │
│  context_embedding vector(3072)                 │
│  first_seen_artifact_uid                        │
│  first_seen_revision_id                         │
│  needs_review                                   │
└────────────────────┬────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌────────────────────┐   ┌────────────────────┐
│   entity_alias     │   │  entity_mention    │
│                    │   │                    │
│  entity_id (FK)    │   │  entity_id (FK)    │
│  alias             │   │  artifact_uid      │
│  normalized_alias  │   │  revision_id       │
│                    │   │  surface_form      │
│                    │   │  start_char        │
│                    │   │  end_char          │
└────────────────────┘   └────────────────────┘
```

### 3.3 Integration with Existing V3 Tables

**Backward Compatibility Strategy:**
- V3's `semantic_event.actors_json` and `subject_json` remain unchanged
- V4's `event_actor` and `event_subject` are the normalized, graph-queryable versions
- Both are populated during extraction (dual-write)
- V3 queries continue to work; V4 queries use the normalized tables

**Migration Path:**
1. Add V4 tables (non-breaking)
2. Update extraction to populate both JSONB and normalized tables
3. Backfill existing events with entity resolution (batch job)

### 3.4 Graph Schema (Apache AGE)

#### Nodes

```cypher
(:Entity {
    entity_id: UUID,
    canonical_name: STRING,
    type: STRING,
    role: STRING,
    organization: STRING
})

(:Event {
    event_id: UUID,
    category: STRING,
    narrative: STRING,
    artifact_uid: STRING,
    revision_id: STRING,
    event_time: TIMESTAMP,
    confidence: FLOAT
})
```

#### Edges

```cypher
-- Actor relationship
(:Entity)-[:ACTED_IN {role: STRING}]->(:Event)

-- Subject relationship
(:Event)-[:ABOUT]->(:Entity)

-- Uncertain merge (for review queue)
(:Entity)-[:POSSIBLY_SAME {confidence: FLOAT, reason: STRING}]->(:Entity)
```

#### Why No Revision Nodes?

V4 deliberately excludes Revision nodes because:
1. "Events in same revision" is trivially queryable: `WHERE artifact_uid = $uid AND revision_id = $rev`
2. Reduces graph complexity and MERGE operation count
3. All revision info available via Event properties
4. Event-to-Event relationships (same document) can use property filters

---

## 4. API Contracts

### 4.1 Updated `hybrid_search` Signature

**Tool Name:** `hybrid_search`

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query text"
    },
    "limit": {
      "type": "integer",
      "default": 5,
      "description": "Maximum primary results to return"
    },
    "include_memory": {
      "type": "boolean",
      "default": false,
      "description": "Include memory collection in search"
    },
    "expand_neighbors": {
      "type": "boolean",
      "default": false,
      "description": "Include +-1 chunks for context"
    },
    "filters": {
      "type": "object",
      "description": "Optional metadata filters"
    },
    "graph_expand": {
      "type": "boolean",
      "default": false,
      "description": "Enable graph-based context expansion"
    },
    "graph_depth": {
      "type": "integer",
      "default": 1,
      "minimum": 1,
      "maximum": 1,
      "description": "Expansion depth (only 1 supported in V4)"
    },
    "graph_budget": {
      "type": "integer",
      "default": 10,
      "minimum": 1,
      "maximum": 50,
      "description": "Max additional related items"
    },
    "graph_seed_limit": {
      "type": "integer",
      "default": 5,
      "minimum": 1,
      "maximum": 20,
      "description": "How many primary results to use as expansion seeds"
    },
    "graph_filters": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Category filter for related items (null = all)"
    },
    "include_entities": {
      "type": "boolean",
      "default": true,
      "description": "Include entity list when graph_expand=true"
    }
  },
  "required": ["query"]
}
```

### 4.2 Output Schema (V4)

```json
{
  "type": "object",
  "properties": {
    "primary_results": {
      "type": "array",
      "description": "RRF-merged results (unchanged from V3)",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "content": {"type": "string"},
          "type": {"type": "string", "enum": ["artifact", "chunk", "memory", "event"]},
          "metadata": {"type": "object"},
          "rrf_score": {"type": "number"},
          "collections": {"type": "array", "items": {"type": "string"}}
        }
      }
    },
    "related_context": {
      "type": "array",
      "description": "Graph-derived related items (only when graph_expand=true)",
      "items": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["event"]},
          "id": {"type": "string", "format": "uuid"},
          "category": {"type": "string"},
          "reason": {"type": "string"},
          "summary": {"type": "string"},
          "event_time": {"type": "string", "format": "date-time"},
          "evidence": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "quote": {"type": "string"},
                "artifact_uid": {"type": "string"},
                "start_char": {"type": "integer"},
                "end_char": {"type": "integer"}
              }
            }
          }
        }
      }
    },
    "entities": {
      "type": "array",
      "description": "Canonical entities involved (only when include_entities=true)",
      "items": {
        "type": "object",
        "properties": {
          "entity_id": {"type": "string", "format": "uuid"},
          "name": {"type": "string"},
          "type": {"type": "string"},
          "role": {"type": "string"},
          "organization": {"type": "string"},
          "aliases": {"type": "array", "items": {"type": "string"}},
          "mention_count": {"type": "integer"}
        }
      }
    },
    "expand_options": {
      "type": "array",
      "description": "Available expansion toggles (always returned)",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "description": {"type": "string"}
        }
      }
    }
  },
  "required": ["primary_results", "expand_options"]
}
```

### 4.3 Expand Options (Always Returned)

```json
[
  {
    "name": "graph_expand",
    "description": "Add related events/entities (1 hop) for richer context"
  },
  {
    "name": "include_memory",
    "description": "Include stored memories in search"
  },
  {
    "name": "expand_neighbors",
    "description": "Include neighboring chunks for context"
  },
  {
    "name": "graph_budget",
    "description": "Adjust max related items (current: 10)"
  },
  {
    "name": "graph_filters",
    "description": "Filter by category: Decision, Commitment, QualityRisk, etc."
  }
]
```

### 4.4 Internal APIs

#### 4.4.1 Entity Resolution Service

```python
class EntityResolutionService:
    async def resolve_entity(
        self,
        surface_form: str,
        canonical_suggestion: str,
        entity_type: str,
        context_clues: dict,
        artifact_uid: str,
        revision_id: str
    ) -> EntityResolutionResult:
        """
        Resolve an entity mention to a canonical entity.

        Returns:
            EntityResolutionResult:
                - entity_id: UUID of resolved entity
                - is_new: True if new entity created
                - merged_from: UUID if merged with existing
                - uncertain_match: UUID if POSSIBLY_SAME edge created
        """
        pass

    async def generate_context_embedding(
        self,
        canonical_name: str,
        entity_type: str,
        role: str | None,
        org: str | None
    ) -> list[float]:
        """Generate embedding for entity context string."""
        pass

    async def find_dedup_candidates(
        self,
        entity_type: str,
        context_embedding: list[float],
        threshold: float = 0.85
    ) -> list[Entity]:
        """Find candidate entities for deduplication."""
        pass

    async def confirm_merge_with_llm(
        self,
        entity_a: Entity,
        entity_b: Entity,
        context_a: dict,
        context_b: dict
    ) -> MergeDecision:
        """Call LLM to confirm merge decision."""
        pass
```

#### 4.4.2 Graph Service

```python
class GraphService:
    async def upsert_entity_node(self, entity: Entity) -> None:
        """MERGE entity node into graph."""
        pass

    async def upsert_event_node(self, event: SemanticEvent) -> None:
        """MERGE event node into graph."""
        pass

    async def upsert_acted_in_edge(
        self,
        entity_id: UUID,
        event_id: UUID,
        role: str
    ) -> None:
        """MERGE ACTED_IN edge."""
        pass

    async def upsert_about_edge(
        self,
        event_id: UUID,
        entity_id: UUID
    ) -> None:
        """MERGE ABOUT edge."""
        pass

    async def upsert_possibly_same_edge(
        self,
        entity_a_id: UUID,
        entity_b_id: UUID,
        confidence: float,
        reason: str
    ) -> None:
        """MERGE POSSIBLY_SAME edge."""
        pass

    async def expand_from_events(
        self,
        seed_event_ids: list[UUID],
        budget: int,
        category_filter: list[str] | None
    ) -> list[RelatedContext]:
        """1-hop graph expansion from seed events."""
        pass
```

---

## 5. Processing Pipeline

### 5.1 Extended Extract Events Flow

```
artifact_ingest
    │
    ▼
event_jobs.enqueue(job_type='extract_events')
    │
    ▼
Worker: extract_events (EXTENDED for V4)
    │
    ├── [Existing V3] Prompt A: Extract events per chunk
    │
    ├── [NEW V4] Prompt A Extended: Also extract entities_mentioned per chunk
    │       └── Returns: events[], entities_mentioned[]
    │
    ├── [Existing V3] Prompt B: Canonicalize events across chunks
    │
    ├── [NEW V4] Entity Resolution Loop:
    │       For each entity_mentioned:
    │       │
    │       ├── Generate context embedding
    │       │   Text: "{canonical_name}, {type}, {role}, {org}"
    │       │
    │       ├── Find candidates (embedding similarity > 0.85, same type)
    │       │   SQL: SELECT * FROM entity
    │       │        WHERE entity_type = $type
    │       │        AND context_embedding <=> $embedding < 0.15
    │       │        ORDER BY context_embedding <=> $embedding
    │       │        LIMIT 5
    │       │
    │       ├── If candidates found: LLM confirmation call
    │       │   └── Decision: same | different | uncertain
    │       │
    │       ├── Execute decision:
    │       │   ├── same → INSERT entity_mention, INSERT entity_alias
    │       │   ├── different → INSERT entity, INSERT entity_mention
    │       │   └── uncertain → INSERT entity, SET needs_review=true
    │       │
    │       └── Return entity_id for actor/subject linking
    │
    ├── [Existing V3] Write semantic_event + event_evidence
    │
    ├── [NEW V4] Write event_actor + event_subject (linking to resolved entity_ids)
    │
    └── [NEW V4] Enqueue graph_upsert job
        (SAME TRANSACTION - ensures atomicity)
```

### 5.2 New Graph Upsert Flow

```
Worker: graph_upsert
    │
    ├── Read semantic_events for (artifact_uid, revision_id)
    │
    ├── Read entities via event_actor + event_subject
    │
    ├── For each entity:
    │   └── MERGE (:Entity {entity_id: $id, ...})
    │
    ├── For each event:
    │   └── MERGE (:Event {event_id: $id, ...})
    │
    ├── For each event_actor:
    │   └── MERGE (e:Entity)-[:ACTED_IN {role: $role}]->(ev:Event)
    │
    ├── For each event_subject:
    │   └── MERGE (ev:Event)-[:ABOUT]->(e:Entity)
    │
    ├── For each uncertain entity pair:
    │   └── MERGE (e1:Entity)-[:POSSIBLY_SAME {confidence, reason}]->(e2:Entity)
    │
    └── Mark job DONE
```

### 5.3 Job Types Summary

| Job Type | Status | Trigger | Output |
|----------|--------|---------|--------|
| `extract_events` | V3, Extended | artifact_ingest | events + entities |
| `graph_upsert` | NEW V4 | extract_events completion | graph nodes/edges |

### 5.4 Why Entity Resolution in extract_events?

1. **Atomicity** - Single transaction for extraction + resolution avoids race conditions
2. **Context freshness** - Document context is available during extraction
3. **Efficiency** - One LLM call per chunk, not separate entity pass
4. **Simplicity** - graph_upsert becomes pure materialization (no logic)

---

## 6. Graph Stack & Schema

### 6.1 Apache AGE Configuration

**Extension Setup:**
```sql
-- Enable AGE extension
CREATE EXTENSION IF NOT EXISTS age;

-- Load AGE functions
LOAD 'age';

-- Enable ag_catalog in search path
SET search_path = ag_catalog, "$user", public;

-- Create the graph
SELECT create_graph('nur');
```

**Why Apache AGE?**
- Runs inside existing Postgres (no new container)
- SQL-compatible (same connection pool)
- Cypher query language (industry standard)
- Active development and community

### 6.2 Cypher Queries

#### Create Entity Node
```cypher
SELECT * FROM cypher('nur', $$
    MERGE (e:Entity {entity_id: $entity_id})
    ON CREATE SET
        e.canonical_name = $canonical_name,
        e.type = $entity_type,
        e.role = $role,
        e.organization = $organization
    ON MATCH SET
        e.canonical_name = $canonical_name,
        e.role = COALESCE($role, e.role),
        e.organization = COALESCE($organization, e.organization)
    RETURN e
$$, $params) AS (e agtype);
```

#### Create Event Node
```cypher
SELECT * FROM cypher('nur', $$
    MERGE (ev:Event {event_id: $event_id})
    ON CREATE SET
        ev.category = $category,
        ev.narrative = $narrative,
        ev.artifact_uid = $artifact_uid,
        ev.revision_id = $revision_id,
        ev.event_time = $event_time,
        ev.confidence = $confidence
    RETURN ev
$$, $params) AS (ev agtype);
```

#### Create ACTED_IN Edge
```cypher
SELECT * FROM cypher('nur', $$
    MATCH (e:Entity {entity_id: $entity_id})
    MATCH (ev:Event {event_id: $event_id})
    MERGE (e)-[r:ACTED_IN]->(ev)
    ON CREATE SET r.role = $role
    ON MATCH SET r.role = $role
    RETURN r
$$, $params) AS (r agtype);
```

#### Graph Expansion Query
```cypher
SELECT * FROM cypher('nur', $$
    MATCH (seed:Event) WHERE seed.event_id IN $seed_ids

    // Get entities connected to seed events
    OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
    OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)

    WITH seed, collect(DISTINCT actor) + collect(DISTINCT subject) AS entities
    UNWIND entities AS entity

    // Get other events connected to those entities (1 hop)
    MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)
    WHERE NOT related.event_id IN $seed_ids
      AND ($category_filter IS NULL OR related.category IN $category_filter)

    RETURN DISTINCT related, entity,
           CASE
             WHEN (entity)-[:ACTED_IN]->(related) THEN 'same_actor:' + entity.canonical_name
             ELSE 'same_subject:' + entity.canonical_name
           END AS reason
    ORDER BY related.event_time DESC NULLS LAST, related.confidence DESC
    LIMIT $budget
$$, $params) AS (related agtype, entity agtype, reason agtype);
```

### 6.3 Chunk-to-Revision Mapping

When primary results include chunks (from ChromaDB), we need to map to revisions for graph expansion:

```sql
-- Get revision for a chunk's artifact
SELECT artifact_uid, revision_id
FROM artifact_revision
WHERE artifact_id = $artifact_id
  AND is_latest = true;

-- Get events for a revision
SELECT event_id
FROM semantic_event
WHERE artifact_uid = $artifact_uid
  AND revision_id = $revision_id;
```

---

## 7. Dependencies

### 7.1 New Infrastructure Dependencies

| Dependency | Version | Purpose | Breaking Change |
|------------|---------|---------|-----------------|
| Apache AGE | 1.5+ | Graph extension for Postgres | No (extension) |
| pgvector | 0.5+ | Vector similarity search (existing) | No |

**Note:** pgvector is already used in V3 for ChromaDB. V4 uses it in Postgres for entity embeddings.

### 7.2 Python Dependencies

```toml
# New dependencies for V4
asyncpg = "^0.29"  # Already used in V3
age = "^0.0.4"     # AGE Python client (optional, can use raw SQL)
```

### 7.3 OpenAI API Usage

| Operation | Model | Cost/Unit | Est. Volume |
|-----------|-------|-----------|-------------|
| Entity context embedding | text-embedding-3-large | $0.00013/1K tokens | 50 tokens/entity |
| Entity dedup confirmation | gpt-4o-mini | $0.15/$0.60 per 1M tokens | 200 tokens/pair |

**Cost per Document (Quality Path):**
- Extraction (including entities): ~$0.015 (gpt-4o-mini)
- Entity embeddings: ~$0.0001 per entity
- Entity dedup LLM calls: ~$0.001 per candidate pair
- **Total: ~$0.02/document**

### 7.4 Postgres Configuration

```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

-- AGE configuration
ALTER DATABASE events SET search_path = ag_catalog, "$user", public;
```

---

## 8. Acceptance Criteria

### 8.1 Mapping to E2E Tests

Each test from v4.md is mapped to specific acceptance criteria:

#### Test 1: Entity Extraction Returns Rich Context
**Test ID:** `V4-E2E-001`
**Preconditions:** Empty database
**Steps:**
1. Ingest artifact containing: "Alice Chen, Engineering Manager at Acme, discussed the roadmap"
2. Wait for extract_events job to complete

**Acceptance Criteria:**
- [ ] Entity created with `canonical_name = "Alice Chen"`
- [ ] Entity has `role = "Engineering Manager"`
- [ ] Entity has `organization = "Acme"`
- [ ] `entity_mention` record exists with correct `surface_form`
- [ ] `entity_mention` has `start_char` and `end_char` values

#### Test 2: Entity Deduplication (Same Person)
**Test ID:** `V4-E2E-002`
**Preconditions:** Empty database
**Steps:**
1. Ingest doc A: "Alice Chen, Engineering Manager, reviewed the code"
2. Wait for extraction
3. Ingest doc B: "A. Chen from Acme approved the changes"
4. Wait for extraction

**Acceptance Criteria:**
- [ ] Only ONE entity exists with `canonical_name = "Alice Chen"`
- [ ] `entity_mention` table has 2 records (one per document)
- [ ] `entity_alias` table contains "A. Chen" as alias
- [ ] Both surface forms preserved in mentions

#### Test 3: Entity Deduplication (Different People)
**Test ID:** `V4-E2E-003`
**Preconditions:** Empty database
**Steps:**
1. Ingest doc: "Alice Chen (Engineer at Acme) met with Alice Chen (Designer at OtherCorp)"
2. Wait for extraction

**Acceptance Criteria:**
- [ ] TWO separate entities created
- [ ] Entity 1: `organization = "Acme"`, `role = "Engineer"`
- [ ] Entity 2: `organization = "OtherCorp"`, `role = "Designer"`
- [ ] No alias linking between them

#### Test 4: Uncertain Merge Creates POSSIBLY_SAME Edge
**Test ID:** `V4-E2E-004`
**Preconditions:** Empty database
**Steps:**
1. Ingest doc A: "A. Chen mentioned the deadline" (minimal context)
2. Ingest doc B: "Alice C. updated the status" (minimal context)
3. Wait for extraction

**Acceptance Criteria:**
- [ ] Two entities created (different due to uncertainty)
- [ ] `POSSIBLY_SAME` edge exists in graph between them
- [ ] At least one entity has `needs_review = true`
- [ ] Edge has `reason` explaining the uncertainty

#### Test 5: Graph Upsert Materializes Nodes/Edges
**Test ID:** `V4-E2E-005`
**Preconditions:** Empty database
**Steps:**
1. Ingest artifact with actor and subject entities
2. Wait for extract_events DONE
3. Wait for graph_upsert DONE

**Acceptance Criteria:**
- [ ] `Entity` nodes exist in AGE graph
- [ ] `Event` nodes exist in AGE graph
- [ ] `ACTED_IN` edges connect entities to events
- [ ] `ABOUT` edges connect events to subjects
- [ ] `hybrid_search(query, graph_expand=true)` returns non-empty `related_context`

#### Test 6: Hybrid Search Returns Expand Options
**Test ID:** `V4-E2E-006`
**Preconditions:** At least one artifact ingested
**Steps:**
1. Call `hybrid_search(query="test")`

**Acceptance Criteria:**
- [ ] Response includes `expand_options` array
- [ ] `expand_options` contains `graph_expand`
- [ ] `expand_options` contains `include_memory`
- [ ] `expand_options` contains `expand_neighbors`
- [ ] `expand_options` contains `graph_budget`
- [ ] `expand_options` contains `graph_filters`

#### Test 7: Related Context is Connected and Bounded
**Test ID:** `V4-E2E-007`
**Preconditions:** Empty database
**Steps:**
1. Create doc A with Alice Chen making a decision
2. Create doc B with Alice Chen making a different decision
3. Ensure same entity (dedup succeeded)
4. Call `hybrid_search(query about doc A, graph_expand=true, graph_budget=5)`

**Acceptance Criteria:**
- [ ] `related_context` includes events from doc B
- [ ] `related_context.length <= graph_budget`
- [ ] Each `related_context` item has `reason` field
- [ ] `reason` matches pattern `same_actor:{name}` or `same_subject:{name}`

#### Test 8: Graph Seed Limit Respected
**Test ID:** `V4-E2E-008`
**Preconditions:** 10+ artifacts with events
**Steps:**
1. Call `hybrid_search(query, graph_expand=true, graph_seed_limit=3)`

**Acceptance Criteria:**
- [ ] Only top 3 primary results used as expansion seeds
- [ ] Verify via logging or debug output
- [ ] `related_context` excludes events from results 4-10

#### Test 9: Backward Compatibility
**Test ID:** `V4-E2E-009`
**Preconditions:** At least one artifact ingested
**Steps:**
1. Call `hybrid_search(query, graph_expand=false)`
2. Compare output to V3 output shape

**Acceptance Criteria:**
- [ ] Response does NOT contain `related_context` key
- [ ] Response does NOT contain `entities` key
- [ ] `primary_results` format identical to V3
- [ ] `expand_options` IS included (only new field)

#### Test 10: Chunk-to-Revision Mapping
**Test ID:** `V4-E2E-010`
**Preconditions:** Empty database
**Steps:**
1. Ingest large artifact (triggers chunking)
2. Wait for extraction
3. Search returns a chunk as primary result
4. Call with `graph_expand=true`

**Acceptance Criteria:**
- [ ] Chunk correctly maps to `artifact_revision` record
- [ ] Revision maps to `semantic_event` records
- [ ] Events used as seeds for graph expansion
- [ ] `related_context` populated based on chunk's events

### 8.2 Definition of Done Checklist

#### Entity Resolution
- [ ] Extraction prompt returns `entities_mentioned` with context clues (role, org, email)
- [ ] Entity table includes `context_embedding` vector column
- [ ] Entity deduplication uses embedding similarity (>0.85) + LLM confirmation
- [ ] `entity_mention` table tracks every surface form with character offsets
- [ ] `entity_alias` table stores known aliases per entity
- [ ] `POSSIBLY_SAME` edges created for uncertain merges
- [ ] `needs_review` flag set on entities requiring manual disambiguation

#### Graph
- [ ] AGE extension enabled in Postgres
- [ ] Graph `nur` created with Entity and Event nodes
- [ ] ACTED_IN, ABOUT, POSSIBLY_SAME edges materialized
- [ ] graph_upsert job type works with idempotent MERGE
- [ ] No Revision nodes (simplified model)

#### hybrid_search
- [ ] Supports all new parameters: graph_expand, graph_depth, graph_budget, graph_seed_limit, graph_filters, include_entities
- [ ] `graph_filters` defaults to null (all categories)
- [ ] Returns primary_results (unchanged from V3)
- [ ] Returns related_context with standardized reason format
- [ ] Returns entities list with aliases and mention counts
- [ ] Returns expand_options for progressive disclosure
- [ ] Chunk-to-revision mapping works via artifact_revision.artifact_id join

#### Quality & Performance
- [ ] E2E tests pass (all 10 tests)
- [ ] Same person across documents correctly deduplicated
- [ ] Different people with similar names stay separate
- [ ] Backward compatibility: graph_expand=false returns V3 shape
- [ ] Latency: graph_expand adds < 300ms for typical queries

---

## 9. Risks & Mitigations

### 9.1 Entity Deduplication Accuracy

**Risk:** LLM makes incorrect merge decisions (false positives or false negatives)

**Impact:** High - Corrupted entity graph, incorrect related context

**Mitigations:**
1. **Conservative defaults** - When uncertain, create separate entities with `POSSIBLY_SAME` edge
2. **Review queue** - `needs_review=true` flag surfaces questionable merges
3. **Context richness** - Extract more context clues (role, org, email) for better decisions
4. **Human override** - Future: UI for manual entity merge/split

**Monitoring:**
- Track `POSSIBLY_SAME` edge count (should decrease over time)
- Sample random entity pairs for accuracy audit
- Alert if `needs_review=true` count exceeds threshold

### 9.2 Graph Query Performance

**Risk:** Cypher expansion queries slow down hybrid_search

**Impact:** Medium - Degraded user experience, timeouts

**Mitigations:**
1. **Budget limits** - Hard cap on `graph_budget` (max 50)
2. **Seed limits** - Hard cap on `graph_seed_limit` (max 20)
3. **Index strategy** - Ensure indexes on `entity_id` and `event_id`
4. **Query timeout** - 500ms timeout on graph expansion query
5. **Fallback** - If graph expansion times out, return primary results only

**Monitoring:**
- Track P50/P95/P99 latency for graph expansion
- Alert if P95 > 300ms
- Dashboard for graph size (nodes, edges)

### 9.3 Migration from V3

**Risk:** Breaking changes to existing V3 data or APIs

**Impact:** High - Service disruption, data loss

**Mitigations:**
1. **Additive schema** - V4 tables are new, no V3 modifications
2. **Dual write** - Write both `actors_json` AND `event_actor` during extraction
3. **Feature flag** - `graph_expand` is opt-in, off by default
4. **Backfill strategy** - Separate job to resolve entities for existing events
5. **Rollback plan** - Can disable graph features without data loss

**Testing:**
- V3 test suite must pass unchanged
- Specific backward compatibility test (V4-E2E-009)

### 9.4 Apache AGE Stability

**Risk:** AGE extension has bugs or performance issues

**Impact:** Medium - Graph features unavailable

**Mitigations:**
1. **Isolation** - Graph is a derived index, not source of truth
2. **Graceful degradation** - If AGE fails, hybrid_search works without expansion
3. **Version pinning** - Use tested AGE version (1.5+)
4. **Fallback queries** - Can implement expansion via SQL if AGE problematic

### 9.5 Cost Overruns

**Risk:** Entity deduplication LLM calls exceed budget

**Impact:** Low - Higher than expected API costs

**Mitigations:**
1. **Embedding pre-filter** - Reduces LLM calls to O(candidates), not O(n^2)
2. **Batch processing** - Group candidate confirmations
3. **Cost tracking** - Log cost per document
4. **Budget alerts** - Alert if daily cost exceeds threshold
5. **gpt-4o-mini** - Use cheapest capable model ($0.001/call)

---

## 10. Implementation Sequence

### Phase 1: Foundation (Week 1)

1. **Database migrations**
   - Add entity, entity_alias, entity_mention tables
   - Add event_actor, event_subject tables
   - Enable AGE extension, create graph

2. **Entity model layer**
   - Entity dataclass/model
   - EntityAlias dataclass/model
   - EntityMention dataclass/model
   - Postgres CRUD operations

3. **Basic entity extraction**
   - Update extraction prompt for `entities_mentioned`
   - Parse entity response
   - Create entities (without dedup)

### Phase 2: Entity Resolution (Week 2)

1. **Embedding-based candidate search**
   - Generate context embeddings
   - Vector similarity query in Postgres

2. **LLM confirmation service**
   - Prompt template for merge decision
   - Parse same/different/uncertain response
   - Execute merge/create/uncertain actions

3. **Alias and mention tracking**
   - Insert entity_alias on merge
   - Insert entity_mention for all occurrences
   - Preserve evidence trail

### Phase 3: Graph Materialization (Week 3)

1. **Graph upsert job**
   - Enqueue after extract_events
   - MERGE entity nodes
   - MERGE event nodes
   - MERGE edges

2. **AGE Cypher integration**
   - Connection management
   - Parameterized queries
   - Error handling

3. **Graph expansion query**
   - 1-hop expansion Cypher
   - Result parsing
   - Category filtering

### Phase 4: Hybrid Search Enhancement (Week 4)

1. **New parameters**
   - Add graph_expand, graph_depth, graph_budget, etc.
   - Input validation
   - Default values

2. **Expansion logic**
   - Seed event collection from primary results
   - Chunk-to-revision mapping
   - Call graph expansion
   - Format related_context

3. **Output formatting**
   - Add related_context section
   - Add entities section
   - Add expand_options (always)

### Phase 5: Testing & Quality (Week 5)

1. **Unit tests**
   - Entity resolution service
   - Graph service
   - Hybrid search expansion

2. **Integration tests**
   - Full pipeline: ingest → extract → graph → search
   - Deduplication scenarios
   - Backward compatibility

3. **E2E tests**
   - All 10 defined tests
   - Performance benchmarks

### Phase 6: Documentation & Deployment (Week 6)

1. **Documentation**
   - API changes
   - New parameters
   - Migration guide

2. **Deployment**
   - Migration scripts
   - Feature flag configuration
   - Monitoring setup

3. **Backfill**
   - Entity resolution for existing events
   - Graph population from existing data

---

## Appendix A: LLM Prompts

### A.1 Extended Extraction Prompt (Prompt A)

```
You are extracting structured information from a document chunk.

INPUT:
- Document title: {title}
- Document type: {artifact_type}
- Chunk {chunk_index} of {total_chunks}
- Content: {chunk_content}

Extract the following:

1. EVENTS: Key decisions, commitments, quality risks, changes, and collaborations.
   For each event:
   - category: One of [Commitment, Execution, Decision, Collaboration, QualityRisk, Feedback, Change, Stakeholder]
   - narrative: 1-2 sentence summary
   - event_time: ISO timestamp if mentioned
   - subject: What the event is about (type + reference)
   - actors: Who was involved (references + roles)
   - evidence: Exact quote (max 25 words) with character offsets
   - confidence: 0.0-1.0

2. ENTITIES: People, organizations, projects, or other named entities mentioned.
   For each entity:
   - surface_form: Exact text as it appeared
   - canonical_suggestion: Your best guess at the full/formal name
   - type: One of [person, org, project, object, place, other]
   - context_clues: Any disambiguating information found:
     - role: Job title or role if mentioned
     - org: Organization affiliation if mentioned
     - email: Email address if mentioned
   - aliases_in_doc: Other ways this entity is referred to in this chunk
   - confidence: 0.0-1.0
   - start_char: Starting character offset in chunk
   - end_char: Ending character offset in chunk

Return JSON:
{
  "events": [...],
  "entities_mentioned": [...]
}
```

### A.2 Entity Deduplication Prompt

```
You are determining if two entity mentions refer to the same real-world entity.

ENTITY A (from document "{title_a}"):
- Name: "{name_a}"
- Type: {type_a}
- Context: {context_a}

ENTITY B (from document "{title_b}"):
- Name: "{name_b}"
- Type: {type_b}
- Context: {context_b}

Rules:
- "same" = High confidence these refer to the same real-world entity
- "different" = High confidence these are different entities
- "uncertain" = Not enough information to decide confidently

If "same", provide the best canonical name to use.

Return JSON:
{
  "decision": "same|different|uncertain",
  "canonical_name": "...",
  "reason": "Brief explanation"
}
```

---

## Appendix B: SQL Migrations

### B.1 Migration 008: V4 Entity Tables

```sql
-- migrations/008_v4_entity_tables.sql

-- Enable vector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. entity table
CREATE TABLE IF NOT EXISTS entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person', 'org', 'project', 'object', 'place', 'other'
    )),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    role TEXT,
    organization TEXT,
    email TEXT,
    context_embedding vector(3072),
    first_seen_artifact_uid TEXT NOT NULL,
    first_seen_revision_id TEXT NOT NULL,
    needs_review BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX entity_type_name_idx ON entity(entity_type, normalized_name);
CREATE INDEX entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX entity_needs_review_idx ON entity(needs_review) WHERE needs_review = true;

-- 2. entity_alias table
CREATE TABLE IF NOT EXISTS entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(entity_id, normalized_alias)
);

CREATE INDEX entity_alias_lookup_idx ON entity_alias(normalized_alias);

-- 3. entity_mention table
CREATE TABLE IF NOT EXISTS entity_mention (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    surface_form TEXT NOT NULL,
    start_char INT,
    end_char INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX entity_mention_entity_idx ON entity_mention(entity_id);
CREATE INDEX entity_mention_revision_idx ON entity_mention(artifact_uid, revision_id);

-- 4. event_actor table
CREATE TABLE IF NOT EXISTS event_actor (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN (
        'owner', 'contributor', 'reviewer', 'stakeholder', 'other'
    )),
    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX event_actor_entity_idx ON event_actor(entity_id);

-- 5. event_subject table
CREATE TABLE IF NOT EXISTS event_subject (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX event_subject_entity_idx ON event_subject(entity_id);

SELECT 'V4 entity tables created successfully' AS status;
```

### B.2 Migration 009: Apache AGE Graph

```sql
-- migrations/009_v4_age_graph.sql

-- Enable AGE extension
CREATE EXTENSION IF NOT EXISTS age;

-- Load AGE and set search path
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the graph
SELECT create_graph('nur');

-- Grant permissions
GRANT USAGE ON SCHEMA ag_catalog TO events;

SELECT 'AGE graph "nur" created successfully' AS status;
```

---

## Appendix C: Cost Estimates

### C.1 Per-Document Costs

| Operation | Model | Input Tokens | Output Tokens | Cost |
|-----------|-------|--------------|---------------|------|
| Event + Entity Extraction | gpt-4o-mini | ~2000 | ~500 | $0.015 |
| Entity Context Embedding | text-embedding-3-large | ~50 | - | $0.00001 |
| Entity Dedup (per pair) | gpt-4o-mini | ~200 | ~50 | $0.001 |

**Typical Document (5 entities, 2 dedup candidates):**
- Extraction: $0.015
- Embeddings (5x): $0.00005
- Dedup calls (2x): $0.002
- **Total: ~$0.017/document**

### C.2 Monthly Cost Projections

| Volume | Cost/Month |
|--------|------------|
| 1,000 documents | $17 |
| 10,000 documents | $170 |
| 100,000 documents | $1,700 |

---

*End of V4 Technical Specification*
