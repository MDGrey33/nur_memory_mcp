# MCP Memory Server V4: Architecture Overview

**Version:** 4.0
**Date:** 2025-12-28
**Author:** Senior Architect
**Status:** Approved for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [Key Architectural Decisions](#3-key-architectural-decisions)
4. [System Architecture](#4-system-architecture)
5. [New Components](#5-new-components)
6. [Data Model Changes](#6-data-model-changes)
7. [Processing Pipeline](#7-processing-pipeline)
8. [API Changes](#8-api-changes)
9. [Quality Attributes](#9-quality-attributes)
10. [Migration Strategy](#10-migration-strategy)
11. [Related Documents](#11-related-documents)

---

## 1. Executive Summary

### What is V4?

V4 transforms `hybrid_search` into **"portable memory"** by adding:

1. **Graph-backed context expansion** - When searching for "Alice's decisions", automatically surface related events involving Alice from other documents

2. **Quality-first entity resolution** - Correctly identify that "Alice Chen", "A. Chen", and "Alice" are the same person, while distinguishing "Alice Chen at Acme" from "Alice Chen at OtherCorp"

3. **Progressive disclosure** - Return `expand_options` so assistants can offer users "I can also show related context from other documents"

### Key Constraint

**No new user-facing MCP tools.** All enhancements are behind the existing `hybrid_search` API with optional parameters. When `graph_expand=false` (the default), the output is identical to V3.

### What Changed from V3?

| Aspect | V3 | V4 |
|--------|----|----|
| **Entity Model** | String refs in JSONB | Canonical entities with deduplication |
| **Relationships** | None (silos) | Graph-backed 1-hop traversal |
| **hybrid_search** | 5 params | 11 params (+6 graph params) |
| **Postgres** | 4 tables | 9 tables (+5 entity tables) |
| **Extensions** | pgvector | pgvector + Apache AGE |
| **Job Types** | extract_events | extract_events + graph_upsert |

---

## 2. Goals and Non-Goals

### Goals

1. **Cross-document context**: Find events related via shared actors/subjects
2. **Entity deduplication**: >95% accuracy on same-person merges
3. **< 2% false merge rate**: Different people with same name stay separate
4. **< 300ms latency impact**: Graph expansion should not significantly slow search
5. **100% backward compatibility**: `graph_expand=false` returns V3 output

### Non-Goals (Out of Scope)

1. New user-facing MCP tools (use existing `hybrid_search`)
2. Multi-hop graph traversal (V4 limited to 1-hop)
3. Real-time graph updates (batch via job queue)
4. Entity merge UI (manual review stays in database)
5. Privacy enforcement (V5 roadmap)

---

## 3. Key Architectural Decisions

V4 architecture is shaped by four key decisions documented in ADRs:

### ADR-001: Entity Resolution Strategy

**Decision:** Two-phase approach (Embedding + LLM Confirmation)

- Phase A: Generate embedding for entity context, find candidates with similarity > 0.85
- Phase B: Call LLM to confirm merge decision for each candidate pair
- Outputs: `same` (merge), `different` (new entity), `uncertain` (POSSIBLY_SAME edge)

**Rationale:** Quality is critical. Entity resolution errors compound across the graph. LLM confirmation with context prevents false merges.

### ADR-002: Graph Database Choice

**Decision:** Apache AGE (Postgres extension), not Neo4j

- Runs inside existing Postgres container (no new infrastructure)
- Same connection pool and transaction model
- Cypher query language for graph traversals
- Graph is a materialized index, not source of truth

**Rationale:** Operational simplicity. For our scale (10K-100K nodes), AGE is sufficient and avoids complexity of a separate graph database.

### ADR-003: Entity Resolution Timing

**Decision:** Resolve entities during `extract_events` job, not in a separate job

- Keeps pipeline atomic (no race conditions)
- Entity context is freshest during extraction
- Single job handles both extraction and resolution
- `graph_upsert` becomes a pure materialization step

**Rationale:** Atomicity eliminates duplicate entity creation when concurrent jobs process documents mentioning the same person.

### ADR-004: Graph Model Simplification

**Decision:** No Revision nodes in graph (Event-Entity graph only)

- Only Entity and Event nodes
- Edges: ACTED_IN, ABOUT, POSSIBLY_SAME
- "Events in same revision" queryable via Event properties

**Rationale:** YAGNI. The V4 use case is entity-centric traversal. Document-centric queries are efficiently done via SQL.

---

## 4. System Architecture

### Container Architecture (Unchanged from V3)

```
+------------------------------------------------------------------------+
|                          Docker Compose                                  |
|                                                                          |
|  +------------------+    +------------------+    +------------------+    |
|  |   mcp-server     |    |     chroma       |    |    postgres      |    |
|  |   Port: 3000     |    |   Port: 8001     |    |   Port: 5432     |    |
|  +------------------+    +------------------+    +------------------+    |
|           |                       |                      ^              |
|           |                       |                      |              |
|  +------------------+             |                      |              |
|  |   event-worker   |-------------+----------------------+              |
|  +------------------+                                                   |
|                                                                          |
+------------------------------------------------------------------------+
```

**Key Point:** No new containers. V4 adds functionality within existing architecture.

### Postgres Extensions

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- UUID generation (V3)
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector for embeddings (V3)
CREATE EXTENSION IF NOT EXISTS age;        -- Apache AGE for graph (V4 NEW)
```

### Service Layer (V4)

```
+------------------------------------------------------------------+
|                       SERVICE LAYER                                |
|                                                                    |
|  V2 Services:               V3 Services:        V4 Services (NEW): |
|  +------------------+       +----------------+   +----------------+|
|  | EmbeddingService |       | PostgresClient |   | EntityRes.Svc  ||
|  | ChunkingService  |       | JobQueueService|   | GraphService   ||
|  | RetrievalService*|       | EventExtraction|   +----------------+|
|  | PrivacyService   |       +----------------+                     |
|  +------------------+                                              |
|                                                                    |
|  * RetrievalService enhanced with graph expansion in V4            |
+------------------------------------------------------------------+
```

---

## 5. New Components

### 5.1 EntityResolutionService

**Purpose:** Resolve entity mentions to canonical entities using two-phase deduplication.

**Key Methods:**
- `resolve_entity()` - Main entry point for resolution
- `generate_context_embedding()` - Create embedding for dedup
- `find_dedup_candidates()` - Query similar entities
- `confirm_merge_with_llm()` - LLM confirmation call

**Dependencies:** OpenAI API (embeddings + chat), Postgres (pgvector)

### 5.2 GraphService

**Purpose:** Manage Apache AGE graph operations.

**Key Methods:**
- `upsert_entity_node()` / `upsert_event_node()` - MERGE nodes
- `upsert_acted_in_edge()` / `upsert_about_edge()` - MERGE edges
- `expand_from_events()` - 1-hop traversal for context expansion
- `get_health()` - Graph health statistics

**Dependencies:** Postgres with AGE extension

### 5.3 Enhanced RetrievalService

**V4 Additions:**
- New parameters: `graph_expand`, `graph_depth`, `graph_budget`, `graph_seed_limit`, `graph_filters`, `include_entities`
- New method: `expand_via_graph()` - Graph expansion logic
- New method: `map_chunk_to_revision()` - Chunk-to-event mapping
- `expand_options` always returned for progressive disclosure

---

## 6. Data Model Changes

### New Tables (5)

| Table | Purpose |
|-------|---------|
| `entity` | Canonical entity registry with embeddings |
| `entity_alias` | Known aliases per entity |
| `entity_mention` | Every surface form occurrence |
| `event_actor` | Normalized actor relationships |
| `event_subject` | Normalized subject relationships |

### Graph Schema

```cypher
-- Nodes
(:Entity {entity_id, canonical_name, type, role, organization})
(:Event {event_id, category, narrative, artifact_uid, revision_id, event_time, confidence})

-- Edges
(:Entity)-[:ACTED_IN {role}]->(:Event)
(:Event)-[:ABOUT]->(:Entity)
(:Entity)-[:POSSIBLY_SAME {confidence, reason}]->(:Entity)
```

### Backward Compatibility

- V3's `semantic_event.actors_json` and `subject_json` are retained
- V4's `event_actor` and `event_subject` are the normalized versions
- Both populated during extraction (dual-write)
- V3 queries continue to work unchanged

---

## 7. Processing Pipeline

### V4 Pipeline Overview

```
artifact_ingest
    |
    v
event_jobs.enqueue(job_type='extract_events')
    |
    v
Worker: extract_events (EXTENDED)
    |-- Prompt A Extended: Extract events + entities_mentioned
    |-- Prompt B: Canonicalize events across chunks
    |-- Entity Resolution Loop:
    |     |-- Generate context embedding
    |     |-- Find candidates (embedding similarity)
    |     |-- LLM confirmation (if candidates)
    |     |-- Write entity + alias + mention
    |-- Write semantic_event + event_evidence
    |-- Write event_actor + event_subject
    |-- Enqueue graph_upsert (SAME TRANSACTION)
    |
    v
Worker: graph_upsert (NEW)
    |-- MERGE Entity nodes
    |-- MERGE Event nodes
    |-- MERGE ACTED_IN edges
    |-- MERGE ABOUT edges
    |-- MERGE POSSIBLY_SAME edges
```

### Why Same Transaction?

Enqueueing `graph_upsert` in the same transaction as event writes ensures:
1. No race conditions between entity creation and graph materialization
2. Graph upsert only runs if extraction succeeds
3. Atomic rollback if anything fails

---

## 8. API Changes

### hybrid_search New Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `graph_expand` | bool | false | Enable graph expansion |
| `graph_depth` | int | 1 | Expansion depth (only 1 in V4) |
| `graph_budget` | int | 10 | Max related items |
| `graph_seed_limit` | int | 5 | Seeds from primary results |
| `graph_filters` | list[str] | null | Category filter |
| `include_entities` | bool | true | Include entities list |

### Response Format

```json
{
  "primary_results": [...],          // Unchanged from V3
  "related_context": [...],          // NEW: Graph-derived items
  "entities": [...],                 // NEW: Canonical entities
  "expand_options": [...]            // NEW: Available expansions
}
```

### Backward Compatibility

When `graph_expand=false` (default):
- `related_context` is omitted
- `entities` is omitted
- `expand_options` is always included (for progressive disclosure)
- `primary_results` format identical to V3

---

## 9. Quality Attributes

### Performance Targets

| Metric | Target |
|--------|--------|
| Entity resolution latency | < 500ms per entity |
| Graph expansion latency | < 300ms additional |
| Total hybrid_search (with expansion) | < 1s |

### Reliability

- **Graceful degradation**: If AGE unavailable, return V3 results
- **Partial success**: Entity resolution errors don't block extraction
- **Idempotent**: `graph_upsert` can be safely re-run

### Cost

| Operation | Model | Cost |
|-----------|-------|------|
| Extraction (with entities) | gpt-4o-mini | ~$0.015/doc |
| Entity embeddings | text-embedding-3-large | ~$0.0001/entity |
| Entity dedup LLM | gpt-4o-mini | ~$0.001/pair |
| **Total** | | **~$0.02/document** |

---

## 10. Migration Strategy

### Database Migrations

1. **Migration 008: V4 Entity Tables**
   - Creates entity, entity_alias, entity_mention, event_actor, event_subject
   - Non-breaking (additive)

2. **Migration 009: Apache AGE Graph**
   - Enables AGE extension
   - Creates graph 'nur'
   - Non-breaking

### Deployment Steps

1. Deploy new code with feature flags off
2. Run migrations 008 and 009
3. Verify AGE extension and graph creation
4. Enable `graph_expand` parameter
5. Backfill existing events (optional batch job)

### Rollback Plan

If issues arise:
1. Disable `graph_expand` parameter (immediate)
2. Graph queries fail gracefully, V3 results returned
3. Entity tables can be dropped without affecting V3 functionality

---

## 11. Related Documents

### Architecture Decision Records

| ADR | Title | File |
|-----|-------|------|
| ADR-001 | Entity Resolution Strategy | `adr/ADR-001-entity-resolution-strategy.md` |
| ADR-002 | Graph Database Choice | `adr/ADR-002-graph-database-choice.md` |
| ADR-003 | Entity Resolution Timing | `adr/ADR-003-entity-resolution-timing.md` |
| ADR-004 | Graph Model Simplification | `adr/ADR-004-graph-model-simplification.md` |

### Diagrams

| Diagram | Description | File |
|---------|-------------|------|
| Component Diagram | Service architecture | `diagrams/component-diagram.md` |
| Data Flow Diagrams | Processing pipelines | `diagrams/data-flow-diagrams.md` |
| Database Architecture | Tables and graph schema | `diagrams/database-architecture.md` |
| Service Interfaces | API definitions | `diagrams/service-interfaces.md` |
| Error Handling | Resilience patterns | `diagrams/error-handling-resilience.md` |

### Specifications

| Document | Description | File |
|----------|-------------|------|
| V4 Brief | Original requirements | `/v4.md` |
| V4 Specification | Detailed technical spec | `/.claude-workspace/specs/v4-specification.md` |
| V3 Architecture | Previous version | `/.claude-workspace/architecture/v3-architecture.md` |

---

## Appendix: Quick Reference

### New Files to Create

```
src/services/
  entity_resolution_service.py   # NEW
  graph_service.py               # NEW

src/storage/
  postgres_models.py             # EXTEND with entity models

migrations/
  008_v4_entity_tables.sql       # NEW
  009_v4_age_graph.sql           # NEW
```

### Key Cypher Queries

**1-Hop Expansion:**
```cypher
MATCH (seed:Event) WHERE seed.event_id IN $seed_ids
OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)
WITH seed, collect(DISTINCT actor) + collect(DISTINCT subject) AS entities
UNWIND entities AS entity
MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)
WHERE NOT related.event_id IN $seed_ids
RETURN DISTINCT related, entity,
       CASE WHEN (entity)-[:ACTED_IN]->(related)
            THEN 'same_actor:' + entity.canonical_name
            ELSE 'same_subject:' + entity.canonical_name
       END AS reason
ORDER BY related.event_time DESC NULLS LAST
LIMIT $budget
```

### Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Entity dedup accuracy | > 95% | Manual review of 100 pairs |
| False merge rate | < 2% | Different people merged incorrectly |
| Graph expansion latency | < 300ms | P95 timing |
| Backward compatibility | 100% | V3 test suite passes |
| E2E test pass rate | 100% | All 10 defined tests |

---

**End of V4 Architecture Overview**
