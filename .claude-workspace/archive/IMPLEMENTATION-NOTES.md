# V4 Implementation Notes

This document captures key decisions and technical details for the V4 implementation of the MCP Memory server.

## Overview

V4 adds entity resolution and graph-based context expansion to the MCP Memory server. The implementation maintains full backward compatibility with V3 while introducing new capabilities.

## Key Components

### 1. Database Migrations

#### 008_v4_entity_tables.sql
Creates the relational tables for entity management:

- **entity**: Canonical entity registry with embedding support
  - Uses `vector(3072)` for text-embedding-3-large embeddings
  - IVFFlat index with lists=100 for ~100K entity capacity
  - Partial index on `needs_review` for review queue queries

- **entity_alias**: Known aliases for each entity (deduplicated)

- **entity_mention**: Every surface form occurrence with character offsets (preserves evidence trail)

- **event_actor**: Normalized actor relationships (supplements V3's actors_json)

- **event_subject**: Normalized subject relationships (supplements V3's subject_json)

All foreign keys use `ON DELETE CASCADE` to maintain referential integrity.

#### 009_v4_age_setup.sql
Sets up Apache AGE for graph operations:

- Creates the `nur` graph for entity-event relationships
- Provides `execute_cypher()` helper function
- Documents the AGE session setup requirements (`LOAD 'age'`, `SET search_path`)
- Non-fatal if AGE is not installed (V3 functionality continues to work)

### 2. Entity Resolution Service

Located in: `src/services/entity_resolution_service.py`

**Two-phase approach:**
1. **Candidate generation**: Embedding similarity search (cosine > 0.85)
2. **LLM confirmation**: GPT-4o-mini confirms merge decisions

**Key design decisions:**

- **Quality over speed**: Conservative merges, uncertain cases flagged for review
- **O(candidates)** LLM calls, not O(n^2) - embeddings do the heavy lifting
- **Evidence preservation**: Every mention recorded, even for merged entities
- **Alias tracking**: Surface forms different from canonical name become aliases

**Data flow:**
```
LLM extraction -> ExtractedEntity -> resolve_entity() -> EntityResolutionResult
                                          |
                                          v
                      +-------------------+-------------------+
                      |                   |                   |
                 Exact Match         Candidate Search     No Match
                      |                   |                   |
                      v                   v                   v
                 Return ID          LLM Confirm          Create Entity
                                          |
                                +----+----+----+
                                |    |    |    |
                              Same Diff Uncertain
                                |    |    |
                                v    v    v
                             Merge  New  Flag+POSSIBLY_SAME
```

### 3. Graph Service

Located in: `src/services/graph_service.py`

**Key operations:**
- `upsert_entity_node()`: MERGE Entity node into AGE
- `upsert_event_node()`: MERGE Event node into AGE
- `upsert_acted_in_edge()`: Entity -[ACTED_IN]-> Event
- `upsert_about_edge()`: Event -[ABOUT]-> Entity
- `upsert_possibly_same_edge()`: Entity -[POSSIBLY_SAME]-> Entity
- `expand_from_events()`: 1-hop graph traversal for context expansion

**Query timeout**: 500ms default to prevent blocking search requests.

**Graceful degradation**: If AGE is not available, graph operations are skipped and V3 functionality continues.

### 4. Event Extraction Service Updates

Located in: `src/services/event_extraction_service.py`

**V4 changes:**
- Extended prompt to extract `entities_mentioned` with context clues
- New `extract_from_chunk_v4()` returns tuple of (events, entities)
- Added `validate_entity()` and `deduplicate_entities()` methods
- V3 `extract_from_chunk()` delegates to V4 version, returning only events

**Entity extraction output:**
```json
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
```

### 5. Job Queue Service Updates

Located in: `src/services/job_queue_service.py`

**V4 changes:**
- Added `write_events_atomic_v4()` with entity relationships and graph_upsert enqueueing
- Added `claim_job_by_type()` for job type-specific claiming
- Added `get_entities_for_revision()` and `get_events_for_revision()` for graph worker

**Job types:**
- `extract_events` (V3): Event extraction from artifacts
- `graph_upsert` (V4): Materialize entities/events into AGE graph

### 6. Event Worker Updates

Located in: `src/worker/event_worker.py`

**V4 changes:**
- Supports both `extract_events` and `graph_upsert` job types
- `_process_extraction_v4()`: Full V4 pipeline with entity resolution
- `_process_graph_upsert_job()`: Graph materialization
- Graceful fallback to V3 if entity resolution service unavailable

**Processing flow:**
```
claim extract_events job
        |
        v
    fetch artifact text
        |
        v
    extract events + entities (Prompt A)
        |
        v
    canonicalize events (Prompt B)
        |
        v
    resolve entities -> entity_id mappings
        |
        v
    write_events_atomic_v4() -> enqueue graph_upsert
        |
        v
    mark job done

--- separate job ---

claim graph_upsert job
        |
        v
    get entities for revision
        |
        v
    upsert Entity nodes
        |
        v
    get events for revision
        |
        v
    upsert Event nodes + ACTED_IN/ABOUT edges
        |
        v
    upsert POSSIBLY_SAME edges for uncertain pairs
        |
        v
    mark job done
```

### 7. Retrieval Service Updates

Located in: `src/services/retrieval_service.py`

**V4 changes:**
- New `hybrid_search_v4()` with graph expansion parameters
- Added `_perform_graph_expansion()` for 1-hop traversal
- New output shape with `primary_results`, `related_context`, `entities`

**V4 search parameters:**
- `graph_expand: bool` - Enable graph expansion (default: false)
- `graph_depth: int` - Traversal depth, 1-2 hops
- `graph_budget: int` - Max related items (default: 10)
- `graph_seed_limit: int` - Max seeds for expansion (default: 5)
- `graph_filters: dict` - Category filter for expansion
- `include_entities: bool` - Include entity info in response

**Backward compatibility**: When `graph_expand=false`, returns V3-compatible shape.

### 8. New V4 Tools

Located in: `src/tools/event_tools.py`

- **graph_health**: Get AGE graph statistics
- **entity_search**: Search entities with filters
- **entity_review_queue**: Get entities needing manual review

### 9. Postgres Models Updates

Located in: `src/storage/postgres_models.py`

**New models:**
- `Entity`, `EntityAlias`, `EntityMention`
- `EventActor`, `EventSubject`
- `EntityWithMentions`, `EntityResolutionResult`

**New helpers:**
- `entity_to_dict()`
- `event_with_entities_to_dict()`

## Performance Considerations

### Entity Resolution
- Embedding generation: ~100ms per entity (batched)
- Candidate search: ~10ms (IVFFlat index)
- LLM confirmation: ~500ms per candidate (only when candidates found)

### Graph Operations
- Node upsert: ~5ms each
- Edge upsert: ~5ms each
- Graph expansion: 500ms timeout, typically <100ms

### Search with Graph Expansion
- V3 search: ~50ms
- V4 search with expansion: ~100-200ms (depends on seed count)

## Error Handling

All V4 components follow the graceful degradation pattern:

1. **AGE not available**: Graph operations are skipped, V3 features continue
2. **Entity resolution fails**: Entity is skipped, events still extracted
3. **Graph expansion times out**: Returns empty related_context, primary results still returned
4. **LLM confirmation fails**: Defaults to "uncertain", creates separate entity

## Testing Recommendations

1. **Entity resolution quality**: Test with documents containing multiple name variations
2. **Graph expansion accuracy**: Verify related events share actors/subjects
3. **Backward compatibility**: Ensure V3 clients work without changes
4. **Performance**: Monitor P99 latency for search with expansion

## Configuration

New config options to consider:

```python
# Entity resolution
OPENAI_ENTITY_MODEL = "gpt-4o-mini"
ENTITY_SIMILARITY_THRESHOLD = 0.85
ENTITY_MAX_CANDIDATES = 5

# Graph
GRAPH_QUERY_TIMEOUT_MS = 500
GRAPH_EXPANSION_BUDGET = 10
GRAPH_SEED_LIMIT = 5

# Worker
ENABLE_V4_FEATURES = True
```

## Migration Path

1. Run migrations 008, 009
2. Deploy worker with `enable_v4=True`
3. Re-extract documents to populate entities
4. Monitor entity review queue
5. Enable graph expansion in search tool

## Known Limitations

1. **AGE dependency**: Graph features require Apache AGE extension
2. **LLM latency**: Entity resolution adds latency to extraction
3. **Entity types**: Fixed taxonomy (person, org, project, object, place, other)
4. **Graph depth**: Currently limited to 1 hop (2 hops planned)

## Future Enhancements

1. Batch entity resolution for efficiency
2. 2-hop graph expansion
3. Entity merge/split API for manual corrections
4. Temporal graph queries
5. Entity type inference from context
