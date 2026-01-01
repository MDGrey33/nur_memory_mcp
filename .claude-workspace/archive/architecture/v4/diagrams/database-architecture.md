# V4 Database Architecture

## Overview

V4 extends the V3 Postgres schema with 5 new tables for entity management and integrates Apache AGE for graph queries. The relational tables remain the source of truth; the graph is a materialized index.

---

## Schema Overview

```
+------------------------------------------------------------------------+
|                       V4 DATABASE SCHEMA                                 |
+------------------------------------------------------------------------+

POSTGRES (Primary Storage)
|
+-- Extensions
|   +-- pgcrypto (UUID generation)
|   +-- vector (pgvector for embeddings)
|   +-- age (Apache AGE for graph) [NEW]
|
+-- V3 Tables (unchanged)
|   +-- artifact_revision
|   +-- event_jobs (extended with 'graph_upsert' job type)
|   +-- semantic_event
|   +-- event_evidence
|
+-- V4 Tables (new)
|   +-- entity
|   +-- entity_alias
|   +-- entity_mention
|   +-- event_actor
|   +-- event_subject
|
+-- Graph (Apache AGE)
    +-- Graph: 'nur'
        +-- Node: Entity
        +-- Node: Event
        +-- Edge: ACTED_IN
        +-- Edge: ABOUT
        +-- Edge: POSSIBLY_SAME
```

---

## Entity-Relationship Diagram

```
                                   ARTIFACT_REVISION
                              +------------------------+
                              | artifact_uid (PK)      |
                              | revision_id (PK)       |
                              | artifact_id            |
                              | content_hash           |
                              | is_latest              |
                              | ...                    |
                              +------------------------+
                                          |
                                          | (artifact_uid, revision_id)
                                          |
                    +---------------------+---------------------+
                    |                                           |
                    v                                           v
            SEMANTIC_EVENT                               EVENT_JOBS
       +------------------------+                   +------------------------+
       | event_id (PK)          |                   | job_id (PK)            |
       | artifact_uid (FK)      |                   | artifact_uid           |
       | revision_id (FK)       |                   | revision_id            |
       | category               |                   | job_type               |
       | narrative              |                   | status                 |
       | subject_json           |                   | attempts               |
       | actors_json            |                   | ...                    |
       | event_time             |                   +------------------------+
       | confidence             |
       | ...                    |
       +------------------------+
                    |
          +---------+----------+
          |                    |
          v                    v
   EVENT_EVIDENCE         EVENT_ACTOR (NEW)
+------------------+    +------------------+
| evidence_id (PK) |    | event_id (PK,FK) |
| event_id (FK)    |    | entity_id (PK,FK)|
| quote            |    | role             |
| start_char       |    +------------------+
| end_char         |              |
| chunk_id         |              |
+------------------+              v
                           +------------------+
                           |     ENTITY       |
                           |                  |
                           | entity_id (PK)   |
                           | entity_type      |
                           | canonical_name   |
                           | normalized_name  |
                           | role             |
                           | organization     |
                           | email            |
                           | context_embedding|<-- vector(3072)
                           | first_seen_*     |
                           | needs_review     |
                           | created_at       |
                           +------------------+
                                    |
                    +---------------+---------------+
                    |               |               |
                    v               v               v
           ENTITY_ALIAS    ENTITY_MENTION    EVENT_SUBJECT (NEW)
         +--------------+ +--------------+ +------------------+
         | alias_id (PK)| | mention_id(PK)| | event_id (PK,FK) |
         | entity_id(FK)| | entity_id (FK)| | entity_id (PK,FK)|
         | alias        | | artifact_uid  | +------------------+
         | normalized   | | revision_id   |
         | created_at   | | surface_form  |
         +--------------+ | start_char    |
                          | end_char      |
                          | created_at    |
                          +--------------+
```

---

## V4 Table Definitions

### 1. entity - Canonical Entity Registry

```sql
CREATE TABLE entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Classification
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person', 'org', 'project', 'object', 'place', 'other'
    )),

    -- Names
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,  -- lowercase, stripped for matching

    -- Rich context for deduplication
    role TEXT,           -- Job title, e.g., "Engineering Manager"
    organization TEXT,   -- Company, e.g., "Acme Corp"
    email TEXT,          -- Email address for unique identification

    -- Embedding for similarity-based dedup candidate search
    context_embedding vector(3072),  -- text-embedding-3-large

    -- Provenance
    first_seen_artifact_uid TEXT NOT NULL,
    first_seen_revision_id TEXT NOT NULL,

    -- For manual review queue (uncertain merges)
    needs_review BOOLEAN DEFAULT false,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX entity_type_name_idx ON entity(entity_type, normalized_name);
CREATE INDEX entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX entity_needs_review_idx ON entity(needs_review) WHERE needs_review = true;
```

**Key Design Decisions:**

| Column | Purpose |
|--------|---------|
| `normalized_name` | Lowercase, whitespace-stripped for exact match lookups |
| `context_embedding` | vector(3072) for similarity search during deduplication |
| `role`, `organization`, `email` | Context clues for disambiguation |
| `first_seen_*` | Provenance tracking for audit |
| `needs_review` | Flags entities requiring manual disambiguation |

**Embedding Index Notes:**
- IVFFlat with 100 lists is optimal for ~10K-100K vectors
- `vector_cosine_ops` for cosine similarity search
- Query: `context_embedding <=> $query_embedding < 0.15` (similarity > 0.85)

---

### 2. entity_alias - Known Aliases Per Entity

```sql
CREATE TABLE entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,  -- lowercase for lookup

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(entity_id, normalized_alias)
);

CREATE INDEX entity_alias_lookup_idx ON entity_alias(normalized_alias);
```

**Purpose:** When "A. Chen" is merged with "Alice Chen", "A. Chen" becomes an alias. This enables lookup by any known name variant.

**Query Pattern:**
```sql
-- Find entity by any alias
SELECT e.* FROM entity e
JOIN entity_alias ea ON e.entity_id = ea.entity_id
WHERE ea.normalized_alias = lower(trim($name))
```

---

### 3. entity_mention - Every Surface Form Occurrence

```sql
CREATE TABLE entity_mention (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    -- Document location
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,

    -- Exact text as appeared
    surface_form TEXT NOT NULL,

    -- Character offsets for evidence linking
    start_char INT,
    end_char INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX entity_mention_entity_idx ON entity_mention(entity_id);
CREATE INDEX entity_mention_revision_idx ON entity_mention(artifact_uid, revision_id);
```

**Purpose:** Preserve evidence trail. Every time an entity is mentioned, we record exactly how and where. This enables:
- Mention count per entity
- Evidence linking back to source documents
- Audit trail for entity resolution decisions

---

### 4. event_actor - Structured Actor Relationships

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

**Purpose:** Normalized version of `semantic_event.actors_json`. Enables efficient joins for graph expansion.

**Backward Compatibility:** V3's `actors_json` is retained for backward compatibility. Both are populated during extraction (dual-write).

---

### 5. event_subject - Structured Subject Relationships

```sql
CREATE TABLE event_subject (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,

    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX event_subject_entity_idx ON event_subject(entity_id);
```

**Purpose:** Normalized version of `semantic_event.subject_json`. Enables efficient joins for graph expansion.

---

## Apache AGE Graph Schema

### Setup

```sql
-- Enable extension
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create graph
SELECT create_graph('nur');
```

### Node: Entity

```cypher
(:Entity {
    entity_id: UUID,         -- Links to entity table
    canonical_name: STRING,
    type: STRING,            -- person|org|project|object|place|other
    role: STRING,            -- Nullable
    organization: STRING     -- Nullable
})
```

### Node: Event

```cypher
(:Event {
    event_id: UUID,          -- Links to semantic_event table
    category: STRING,        -- Commitment|Decision|etc.
    narrative: STRING,
    artifact_uid: STRING,    -- For document filtering
    revision_id: STRING,     -- For version filtering
    event_time: TIMESTAMP,   -- Nullable
    confidence: FLOAT
})
```

### Edge: ACTED_IN

```cypher
(:Entity)-[:ACTED_IN {role: STRING}]->(:Event)
```

Represents: Entity performed an action in the event.

### Edge: ABOUT

```cypher
(:Event)-[:ABOUT]->(:Entity)
```

Represents: Event is about this entity (subject).

### Edge: POSSIBLY_SAME

```cypher
(:Entity)-[:POSSIBLY_SAME {
    confidence: FLOAT,
    reason: STRING
}]->(:Entity)
```

Represents: These entities might be the same (uncertain merge).

---

## Migration Strategy

### Migration 008: V4 Entity Tables

```sql
-- migrations/008_v4_entity_tables.sql

-- Enable vector if not already
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. entity
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

CREATE INDEX IF NOT EXISTS entity_type_name_idx
    ON entity(entity_type, normalized_name);
CREATE INDEX IF NOT EXISTS entity_embedding_idx ON entity
    USING ivfflat (context_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS entity_needs_review_idx
    ON entity(needs_review) WHERE needs_review = true;

-- 2. entity_alias
CREATE TABLE IF NOT EXISTS entity_alias (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS entity_alias_lookup_idx
    ON entity_alias(normalized_alias);

-- 3. entity_mention
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

CREATE INDEX IF NOT EXISTS entity_mention_entity_idx
    ON entity_mention(entity_id);
CREATE INDEX IF NOT EXISTS entity_mention_revision_idx
    ON entity_mention(artifact_uid, revision_id);

-- 4. event_actor
CREATE TABLE IF NOT EXISTS event_actor (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN (
        'owner', 'contributor', 'reviewer', 'stakeholder', 'other'
    )),
    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX IF NOT EXISTS event_actor_entity_idx
    ON event_actor(entity_id);

-- 5. event_subject
CREATE TABLE IF NOT EXISTS event_subject (
    event_id UUID NOT NULL REFERENCES semantic_event(event_id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX IF NOT EXISTS event_subject_entity_idx
    ON event_subject(entity_id);

SELECT 'V4 entity tables created successfully' AS status;
```

### Migration 009: Apache AGE Graph

```sql
-- migrations/009_v4_age_graph.sql

-- Enable AGE extension
CREATE EXTENSION IF NOT EXISTS age;

-- Load and configure AGE
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the graph
SELECT create_graph('nur');

-- Note: AGE nodes and edges are created dynamically via Cypher MERGE
-- No explicit schema definition required

SELECT 'AGE graph "nur" created successfully' AS status;
```

---

## Query Patterns

### Find Entity by Name (any variant)

```sql
SELECT e.*
FROM entity e
WHERE e.normalized_name = lower(trim($name))
   OR EXISTS (
       SELECT 1 FROM entity_alias ea
       WHERE ea.entity_id = e.entity_id
         AND ea.normalized_alias = lower(trim($name))
   );
```

### Find Dedup Candidates

```sql
SELECT *
FROM entity
WHERE entity_type = $type
  AND context_embedding <=> $embedding < 0.15  -- cosine distance < 0.15 = similarity > 0.85
ORDER BY context_embedding <=> $embedding
LIMIT 5;
```

### Get Entities for Events

```sql
SELECT e.*, 'actor' as relation_type, ea.role
FROM entity e
JOIN event_actor ea ON e.entity_id = ea.entity_id
WHERE ea.event_id = ANY($event_ids)

UNION ALL

SELECT e.*, 'subject' as relation_type, NULL as role
FROM entity e
JOIN event_subject es ON e.entity_id = es.entity_id
WHERE es.event_id = ANY($event_ids);
```

### Graph: 1-Hop Expansion

```cypher
SELECT * FROM cypher('nur', $$
    MATCH (seed:Event) WHERE seed.event_id IN $seed_ids
    OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
    OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)
    WITH seed, collect(DISTINCT actor) + collect(DISTINCT subject) AS entities
    UNWIND entities AS entity
    MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)
    WHERE NOT related.event_id IN $seed_ids
    RETURN DISTINCT related, entity,
           CASE
             WHEN (entity)-[:ACTED_IN]->(related) THEN 'same_actor:' + entity.canonical_name
             ELSE 'same_subject:' + entity.canonical_name
           END AS reason
    ORDER BY related.event_time DESC NULLS LAST
    LIMIT $budget
$$, $params) AS (related agtype, entity agtype, reason agtype);
```

---

## Storage Projections

### Entity Table Growth

| Scenario | Entities/Year | Storage/Year |
|----------|---------------|--------------|
| 1K docs/day | ~100K entities | ~1.5 GB (with embeddings) |
| 10K docs/day | ~1M entities | ~15 GB |

### Graph Size

| Scenario | Nodes | Edges | AGE Storage |
|----------|-------|-------|-------------|
| 1K docs/day | ~500K | ~750K | ~500 MB |
| 10K docs/day | ~5M | ~7.5M | ~5 GB |

---

## Index Summary

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| entity | entity_type_name_idx | B-tree | Type + name lookup |
| entity | entity_embedding_idx | IVFFlat | Similarity search |
| entity | entity_needs_review_idx | Partial | Review queue |
| entity_alias | entity_alias_lookup_idx | B-tree | Alias lookup |
| entity_mention | entity_mention_entity_idx | B-tree | Mentions by entity |
| entity_mention | entity_mention_revision_idx | B-tree | Mentions by document |
| event_actor | event_actor_entity_idx | B-tree | Events by entity |
| event_subject | event_subject_entity_idx | B-tree | Events by entity |
