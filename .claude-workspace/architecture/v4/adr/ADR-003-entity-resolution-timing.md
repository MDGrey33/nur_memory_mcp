# ADR-003: Entity Resolution Timing

**Status:** Accepted
**Date:** 2025-12-28
**Deciders:** Senior Architect, Technical PM
**Context Level:** V4 Graph-backed Context Expansion

---

## Context

V4 introduces entity resolution (determining when two entity mentions refer to the same real-world entity). A key architectural question is: **when** should entity resolution occur in the processing pipeline?

### Current V3 Pipeline

```
artifact_ingest
    |
    v
event_jobs.enqueue(job_type='extract_events')
    |
    v
Worker: extract_events
    |-- Prompt A: Extract events per chunk
    |-- Prompt B: Canonicalize across chunks
    |-- Write semantic_event + event_evidence
    |-- Mark job DONE
```

V3 does not resolve entities - it stores actor/subject references as strings.

### V4 Entity Resolution Requirements

1. Extract entities with context clues (role, org, email)
2. Generate context embeddings for entities
3. Find deduplication candidates via embedding similarity
4. Confirm merges via LLM
5. Write entity records (entity, entity_alias, entity_mention)
6. Link events to resolved entities (event_actor, event_subject)
7. Materialize graph nodes and edges

### Options Considered

#### Option A: Separate Entity Resolution Job

Add a new job type `resolve_entities` that runs after `extract_events`.

```
artifact_ingest
    |
    v
event_jobs.enqueue(job_type='extract_events')
    |
    v
Worker: extract_events (unchanged from V3)
    |-- Write semantic_event (with string refs)
    |-- Enqueue resolve_entities job
    |
    v
Worker: resolve_entities (NEW)
    |-- Read events from semantic_event
    |-- Extract entities from actors_json, subject_json
    |-- Resolve entities (embedding + LLM)
    |-- Write entity tables
    |-- Update event_actor, event_subject
    |-- Enqueue graph_upsert
```

**Pros:**
- Clean separation of concerns
- `extract_events` unchanged (backward compatible)
- Easier to retry entity resolution independently

**Cons:**
- **Race condition risk**: If two documents with "Alice Chen" are processed concurrently, both might create separate entities before either finishes resolution
- **Lost context**: By the time `resolve_entities` runs, we've lost the LLM context from extraction
- **Two-phase entity writes**: Events written first with string refs, then updated with entity_ids
- **Additional latency**: Sequential jobs add time before graph is ready

#### Option B: Entity Resolution During Extraction

Extend `extract_events` to perform entity resolution inline.

```
artifact_ingest
    |
    v
event_jobs.enqueue(job_type='extract_events')
    |
    v
Worker: extract_events (EXTENDED)
    |-- Prompt A Extended: Extract events + entities_mentioned per chunk
    |-- Prompt B: Canonicalize events across chunks
    |-- Entity Resolution Loop:
    |    |-- Generate context embedding
    |    |-- Find candidates (embedding similarity)
    |    |-- LLM confirmation (if candidates)
    |    |-- Write entity + entity_alias + entity_mention
    |-- Write semantic_event + event_evidence
    |-- Write event_actor + event_subject (with resolved entity_ids)
    |-- Enqueue graph_upsert (SAME TRANSACTION)
```

**Pros:**
- **Atomic**: All entity writes happen in one transaction
- **No race conditions**: Each document processes entities sequentially
- **Context freshness**: Entity context clues extracted in same LLM call
- **Simpler pipeline**: One job type does extraction + resolution
- **Consistent state**: Events and entities always written together

**Cons:**
- `extract_events` job becomes more complex
- Longer job execution time
- Entity resolution errors could fail entire extraction

#### Option C: Pre-Extraction Entity Index

Build a global entity index first, then extract events using known entities.

```
New entity discovered anywhere
    |
    v
Entity index service (background)
    |-- Maintain global entity embeddings
    |-- Real-time deduplication

artifact_ingest
    |
    v
extract_events
    |-- Query entity index for known matches
    |-- Extract events with entity_ids
```

**Pros:**
- Global view of all entities
- Consistent entity resolution across all documents

**Cons:**
- **Complexity**: Adds a new long-running service
- **Latency**: Must wait for entity index to be updated
- **Circular dependency**: Entities discovered during extraction feed back to index
- **Overengineering**: Premature for our scale

---

## Decision

**We will implement Option B: Entity Resolution During Extraction**

### Rationale

1. **Atomicity Eliminates Race Conditions**: By resolving entities within the same job, we ensure that entity deduplication decisions are made sequentially. There's no window where two concurrent jobs could create duplicate entities for the same person.

2. **Context is Freshest During Extraction**: The extraction prompt has access to the full document context. By extracting entity context clues (role, org, email) in the same LLM call that extracts events, we get richer deduplication signals.

3. **Simpler Transaction Model**: With Option A, we'd need to update events after entity resolution (changing string refs to entity_ids). With Option B, we write events with entity_ids from the start.

4. **Operational Simplicity**: One job type is easier to monitor, retry, and debug than two interdependent job types.

5. **graph_upsert Becomes Pure Materialization**: If entity resolution happens during extraction, the `graph_upsert` job simply reads the authoritative entity and event data and materializes it to the graph. No business logic, just data transformation.

### Trade-off Accepted

The `extract_events` job becomes more complex and takes longer to execute. We accept this because:
- Job execution time increases from ~30s to ~45s (acceptable for async processing)
- The complexity is contained within one service (EntityResolutionService)
- Errors can be retried at the job level

---

## Implementation Details

### Extended Extraction Prompt

The extraction prompt (Prompt A) is extended to return `entities_mentioned`:

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

### Entity Resolution Flow (Within extract_events)

```python
async def process_extraction_job(job: EventJob):
    # 1. Extract events and entities from chunks
    chunk_results = await extract_from_chunks(artifact_text)

    # 2. Canonicalize events across chunks (existing Prompt B)
    canonical_events = await canonicalize_events(chunk_results)

    # 3. Entity resolution (NEW)
    entity_map = {}  # surface_form -> entity_id
    for entity_mention in all_entities_mentioned:
        entity_id = await entity_resolution_service.resolve_entity(
            surface_form=entity_mention.surface_form,
            canonical_suggestion=entity_mention.canonical_suggestion,
            entity_type=entity_mention.type,
            context_clues=entity_mention.context_clues,
            artifact_uid=job.artifact_uid,
            revision_id=job.revision_id
        )
        entity_map[entity_mention.surface_form] = entity_id

    # 4. Write events with resolved entity_ids
    async with db.transaction():
        for event in canonical_events:
            event_id = await write_semantic_event(event)
            await write_event_evidence(event_id, event.evidence)

            # Link to resolved entities
            for actor in event.actors:
                entity_id = entity_map.get(actor.ref)
                if entity_id:
                    await write_event_actor(event_id, entity_id, actor.role)

            for subject in event.subjects:
                entity_id = entity_map.get(subject.ref)
                if entity_id:
                    await write_event_subject(event_id, entity_id)

        # 5. Enqueue graph_upsert in same transaction
        await enqueue_graph_upsert(job.artifact_uid, job.revision_id)

    # 6. Mark job done
    await mark_job_done(job.job_id)
```

### Handling Entity Resolution Failures

If entity resolution fails for a specific entity:
1. Log the error with context
2. Create entity with `needs_review=true`
3. Continue processing (don't fail the entire job)

This ensures extraction proceeds even if individual entity resolutions fail.

---

## Consequences

### Positive

1. **No Race Conditions**: Sequential processing eliminates duplicate entity creation
2. **Atomic Writes**: Events and entities always consistent
3. **Simpler Pipeline**: One job type, one retry scope
4. **Better Context**: Entity clues extracted with full document context
5. **graph_upsert Simplicity**: Pure materialization, no business logic

### Negative

1. **Longer Job Time**: 15-30 seconds additional per document
2. **Complex Job**: `extract_events` now does extraction + resolution
3. **Partial Failure Risk**: Entity resolution error could affect event writes
4. **Test Complexity**: Need to test entity resolution within extraction flow

### Mitigations

| Risk | Mitigation |
|------|------------|
| Job timeout | Increase job timeout from 60s to 120s |
| Entity resolution failure | Catch, log, create with `needs_review=true` |
| Complex testing | Unit tests for EntityResolutionService, integration tests for full flow |

---

## Related ADRs

- **ADR-001**: Entity Resolution Strategy
- **ADR-002**: Graph Database Choice (Apache AGE)
- **ADR-004**: Graph Model Simplification

---

## References

- V4 Brief: `/v4.md`
- V4 Specification: `/.claude-workspace/specs/v4-specification.md`
- V3 Architecture: `/.claude-workspace/architecture/v3-architecture.md`
