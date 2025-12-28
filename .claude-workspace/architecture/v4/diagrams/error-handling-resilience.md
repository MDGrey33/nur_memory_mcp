# V4 Error Handling & Resilience

## Overview

V4 introduces new failure modes related to entity resolution, graph operations, and LLM calls. This document defines error handling strategies and resilience patterns for each component.

---

## Design Principles

1. **Graceful Degradation**: If a new V4 feature fails, fall back to V3 behavior
2. **No Data Corruption**: Entity resolution errors should not corrupt existing data
3. **Partial Success**: Process as much as possible, log failures for retry
4. **Timeout Budgets**: All external calls have timeouts
5. **Idempotent Operations**: Re-runs should be safe

---

## Error Categories

### 1. Entity Resolution Errors

| Error | Cause | Impact | Handling |
|-------|-------|--------|----------|
| Embedding generation failure | OpenAI API error | Cannot find dedup candidates | Create entity without embedding, flag for retry |
| Dedup candidate query timeout | Postgres slow | Cannot check for duplicates | Create new entity (may duplicate) |
| LLM confirmation failure | OpenAI API error | Cannot confirm merge | Create entity with `needs_review=true` |
| LLM returns invalid JSON | Model error | Cannot parse decision | Treat as "uncertain", create separate entity |

### 2. Graph Operation Errors

| Error | Cause | Impact | Handling |
|-------|-------|--------|----------|
| AGE extension not loaded | Postgres config | Graph queries fail | Skip graph operations, log warning |
| Graph not created | Missing migration | Graph queries fail | Auto-create graph, or skip |
| Cypher syntax error | Code bug | Node/edge not created | Log error, continue with other operations |
| Graph query timeout | Large graph | Expansion incomplete | Return partial results |

### 3. Hybrid Search Errors

| Error | Cause | Impact | Handling |
|-------|-------|--------|----------|
| Graph expansion timeout | Slow query | No related context | Return primary_results only |
| AGE unavailable | Extension missing | Cannot expand | Return V3 response (no expansion) |
| Chunk-to-revision mapping fails | Missing data | Cannot find events | Skip affected chunk, continue |

---

## Entity Resolution Resilience

### Strategy: Create with Flag, Never Block

Entity resolution errors should never block event extraction. The strategy is:

1. **Try** to resolve entity properly
2. **On failure**, create entity anyway with appropriate flags
3. **Log** the failure for later analysis
4. **Continue** processing remaining entities

### Error Handling Flow

```python
async def resolve_entity_with_fallback(
    self,
    entity_mention: EntityMention,
    artifact_uid: str,
    revision_id: str
) -> EntityResolutionResult:
    """
    Resolve entity with graceful fallback on errors.
    """
    try:
        # Try full resolution (embedding + LLM)
        return await self.resolve_entity(
            surface_form=entity_mention.surface_form,
            canonical_suggestion=entity_mention.canonical_suggestion,
            entity_type=entity_mention.type,
            context_clues=entity_mention.context_clues,
            artifact_uid=artifact_uid,
            revision_id=revision_id
        )

    except EmbeddingGenerationError as e:
        # Fallback: Create without embedding
        logger.warning(f"Embedding failed for {entity_mention.surface_form}: {e}")
        return await self._create_entity_without_embedding(
            entity_mention, artifact_uid, revision_id
        )

    except LLMConfirmationError as e:
        # Fallback: Create with needs_review=true
        logger.warning(f"LLM confirmation failed for {entity_mention.surface_form}: {e}")
        return await self._create_uncertain_entity(
            entity_mention, artifact_uid, revision_id
        )

    except Exception as e:
        # Last resort: Create basic entity
        logger.error(f"Entity resolution failed for {entity_mention.surface_form}: {e}")
        return await self._create_basic_entity(
            entity_mention, artifact_uid, revision_id,
            needs_review=True
        )

async def _create_entity_without_embedding(
    self,
    entity_mention: EntityMention,
    artifact_uid: str,
    revision_id: str
) -> EntityResolutionResult:
    """
    Create entity without embedding (will be populated on retry).
    """
    entity_id = await self.create_entity(
        canonical_name=entity_mention.canonical_suggestion,
        normalized_name=normalize(entity_mention.canonical_suggestion),
        entity_type=entity_mention.type,
        context_clues=entity_mention.context_clues,
        context_embedding=None,  # Will be populated on retry
        artifact_uid=artifact_uid,
        revision_id=revision_id,
        needs_review=True  # Flag for retry
    )

    return EntityResolutionResult(
        entity_id=entity_id,
        is_new=True,
        merged_from=None,
        uncertain_match=None,
        canonical_name=entity_mention.canonical_suggestion
    )
```

### Retry Queue

Entities with `needs_review=true` or missing embeddings can be retried:

```sql
-- Find entities needing retry
SELECT entity_id, canonical_name, entity_type
FROM entity
WHERE needs_review = true
   OR context_embedding IS NULL;
```

---

## Graph Operation Resilience

### Strategy: Check Before Use, Graceful Skip

Graph operations are optional - the system must work without them.

### AGE Availability Check

```python
class GraphService:
    def __init__(self, postgres_pool: asyncpg.Pool):
        self.pool = postgres_pool
        self._age_available = None

    async def is_available(self) -> bool:
        """
        Check if AGE extension is available and graph exists.
        Caches result for performance.
        """
        if self._age_available is not None:
            return self._age_available

        try:
            async with self.pool.acquire() as conn:
                # Check extension
                result = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_extension WHERE extname = 'age'
                    )
                """)
                if not result:
                    self._age_available = False
                    return False

                # Check graph
                await conn.execute("LOAD 'age';")
                await conn.execute("SET search_path = ag_catalog, public;")
                result = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM ag_graph WHERE name = 'nur'
                    )
                """)
                self._age_available = result
                return result

        except Exception as e:
            logger.warning(f"AGE availability check failed: {e}")
            self._age_available = False
            return False

    async def upsert_entity_node(self, entity: Entity) -> None:
        """Upsert with availability check."""
        if not await self.is_available():
            logger.debug("AGE not available, skipping entity node upsert")
            return

        try:
            await self._execute_cypher(UPSERT_ENTITY_QUERY, entity.to_params())
        except Exception as e:
            logger.error(f"Failed to upsert entity node {entity.entity_id}: {e}")
            # Continue - graph is supplemental
```

### Graph Query Timeout

```python
async def expand_from_events(
    self,
    seed_event_ids: List[UUID],
    budget: int = 10,
    category_filter: Optional[List[str]] = None,
    timeout_ms: int = 500
) -> List[RelatedContext]:
    """
    Graph expansion with timeout.
    """
    if not await self.is_available():
        return []

    try:
        async with asyncio.timeout(timeout_ms / 1000):
            return await self._execute_expansion_query(
                seed_event_ids, budget, category_filter
            )

    except asyncio.TimeoutError:
        logger.warning(
            f"Graph expansion timed out after {timeout_ms}ms for {len(seed_event_ids)} seeds"
        )
        return []  # Return empty - caller gets primary_results only

    except Exception as e:
        logger.error(f"Graph expansion failed: {e}")
        return []
```

---

## Hybrid Search Resilience

### Strategy: V3 Fallback, Progressive Enhancement

If graph expansion fails, return V3-style results plus error indication.

```python
async def hybrid_search(
    self,
    query: str,
    limit: int = 5,
    graph_expand: bool = False,
    graph_budget: int = 10,
    # ... other params
) -> HybridSearchResult:
    """
    Hybrid search with graceful graph expansion fallback.
    """

    # 1. Always perform V3 search (core functionality)
    primary_results = await self._v3_hybrid_search(query, limit, filters)

    # 2. Attempt graph expansion if requested
    related_context = []
    entities = []
    expansion_error = None

    if graph_expand:
        try:
            related_context, entities = await self.expand_via_graph(
                primary_results=primary_results,
                graph_seed_limit=graph_seed_limit,
                graph_budget=graph_budget,
                graph_filters=graph_filters
            )
        except GraphServiceError as e:
            logger.warning(f"Graph expansion failed, returning primary only: {e}")
            expansion_error = str(e)
        except asyncio.TimeoutError:
            logger.warning("Graph expansion timed out")
            expansion_error = "Graph expansion timed out"

    # 3. Always return expand_options (progressive disclosure)
    expand_options = self.get_expand_options()

    # 4. Build response
    result = HybridSearchResult(
        primary_results=primary_results,
        related_context=related_context if graph_expand else None,
        entities=entities if (graph_expand and include_entities) else None,
        expand_options=expand_options
    )

    # 5. Add warning if expansion failed
    if expansion_error and graph_expand:
        result.warning = f"Graph expansion unavailable: {expansion_error}"

    return result
```

### Response with Warning

```json
{
  "primary_results": [...],
  "related_context": [],
  "entities": [],
  "expand_options": [...],
  "warning": "Graph expansion unavailable: AGE extension not loaded"
}
```

---

## LLM Call Resilience

### Retry Strategy

LLM calls use exponential backoff with jitter:

```python
import asyncio
import random

async def call_llm_with_retry(
    self,
    messages: list,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0
) -> str:
    """
    Call LLM with exponential backoff retry.
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                ),
                timeout=30.0  # 30 second timeout
            )
            return response.choices[0].message.content

        except asyncio.TimeoutError:
            last_error = TimeoutError("LLM call timed out")

        except openai.RateLimitError as e:
            last_error = e
            # Longer backoff for rate limits
            delay = min(base_delay * (4 ** attempt), max_delay)

        except openai.APIError as e:
            last_error = e
            delay = min(base_delay * (2 ** attempt), max_delay)

        except Exception as e:
            last_error = e
            delay = base_delay

        # Add jitter
        delay = delay * (0.5 + random.random())
        logger.warning(f"LLM call failed (attempt {attempt + 1}): {last_error}, retrying in {delay:.1f}s")
        await asyncio.sleep(delay)

    raise LLMConfirmationError(f"LLM call failed after {max_retries} attempts: {last_error}")
```

### Response Validation

```python
def parse_merge_decision(self, response: str) -> MergeDecision:
    """
    Parse LLM merge decision with validation.
    """
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {response}")
        # Fallback to uncertain
        return MergeDecision(
            decision="uncertain",
            canonical_name="",
            reason=f"Failed to parse LLM response: {e}"
        )

    # Validate decision value
    decision = data.get("decision", "").lower()
    if decision not in ("same", "different", "uncertain"):
        logger.warning(f"Invalid decision value: {decision}, treating as uncertain")
        decision = "uncertain"

    return MergeDecision(
        decision=decision,
        canonical_name=data.get("canonical_name", ""),
        reason=data.get("reason", "No reason provided")
    )
```

---

## Job Queue Resilience

### graph_upsert Job Handling

The `graph_upsert` job should be resilient to graph unavailability:

```python
async def process_graph_upsert_job(self, job: EventJob) -> None:
    """
    Process graph upsert job with resilience.
    """

    # Check if graph is available
    if not await self.graph_service.is_available():
        logger.warning(
            f"Graph not available for job {job.job_id}, marking as SKIPPED"
        )
        await self.mark_job_status(job.job_id, "SKIPPED")
        return

    try:
        # Load data
        events = await self.load_events(job.artifact_uid, job.revision_id)
        entities = await self.load_entities_for_events(events)

        # Upsert nodes (continue on individual failures)
        for entity in entities:
            try:
                await self.graph_service.upsert_entity_node(entity)
            except Exception as e:
                logger.error(f"Failed to upsert entity {entity.entity_id}: {e}")

        for event in events:
            try:
                await self.graph_service.upsert_event_node(event)
            except Exception as e:
                logger.error(f"Failed to upsert event {event.event_id}: {e}")

        # Upsert edges
        for actor in event_actors:
            try:
                await self.graph_service.upsert_acted_in_edge(
                    actor.entity_id, actor.event_id, actor.role
                )
            except Exception as e:
                logger.error(f"Failed to upsert ACTED_IN edge: {e}")

        await self.mark_job_status(job.job_id, "DONE")

    except Exception as e:
        logger.error(f"Graph upsert job {job.job_id} failed: {e}")
        await self.mark_job_failed(job.job_id, str(e))
```

---

## Timeout Budget Summary

| Operation | Timeout | Fallback |
|-----------|---------|----------|
| Embedding generation | 10s | Create without embedding |
| Dedup candidate query | 5s | Create new entity |
| LLM confirmation | 30s | Create with needs_review |
| Graph node upsert | 5s | Skip, continue |
| Graph edge upsert | 5s | Skip, continue |
| Graph expansion query | 500ms | Return empty |
| Chunk-to-revision lookup | 2s | Skip affected chunk |

---

## Monitoring & Alerting

### Key Metrics

| Metric | Threshold | Alert |
|--------|-----------|-------|
| Entity resolution error rate | > 5% | Warning |
| LLM confirmation failure rate | > 10% | Warning |
| Graph availability | false | Critical |
| Graph expansion timeout rate | > 20% | Warning |
| needs_review entity count | > 100 | Info |

### Logging

All error paths should log with structured context:

```python
logger.error(
    "Entity resolution failed",
    extra={
        "surface_form": entity_mention.surface_form,
        "entity_type": entity_mention.type,
        "artifact_uid": artifact_uid,
        "error_type": type(e).__name__,
        "error_message": str(e)
    }
)
```

---

## Recovery Procedures

### 1. Retry Failed Entity Embeddings

```python
async def retry_missing_embeddings():
    """Batch retry entities missing embeddings."""
    entities = await fetch_entities_without_embeddings()

    for entity in entities:
        try:
            embedding = await generate_context_embedding(entity)
            await update_entity_embedding(entity.entity_id, embedding)
            await clear_needs_review(entity.entity_id)
        except Exception as e:
            logger.error(f"Retry failed for {entity.entity_id}: {e}")
```

### 2. Rebuild Graph from Relational Data

```python
async def rebuild_graph():
    """Rebuild entire graph from relational tables."""

    # Clear existing graph
    await execute_cypher("MATCH (n) DETACH DELETE n")

    # Rebuild from entity table
    entities = await fetch_all_entities()
    for entity in entities:
        await graph_service.upsert_entity_node(entity)

    # Rebuild from semantic_event
    events = await fetch_all_events()
    for event in events:
        await graph_service.upsert_event_node(event)

    # Rebuild edges from event_actor and event_subject
    actors = await fetch_all_event_actors()
    for actor in actors:
        await graph_service.upsert_acted_in_edge(...)

    subjects = await fetch_all_event_subjects()
    for subject in subjects:
        await graph_service.upsert_about_edge(...)
```

### 3. Manual Entity Merge

```sql
-- Merge entity_b into entity_a
BEGIN;

-- Move mentions
UPDATE entity_mention SET entity_id = $entity_a_id
WHERE entity_id = $entity_b_id;

-- Move aliases
INSERT INTO entity_alias (entity_id, alias, normalized_alias)
SELECT $entity_a_id, alias, normalized_alias
FROM entity_alias WHERE entity_id = $entity_b_id
ON CONFLICT DO NOTHING;

-- Move actor relationships
UPDATE event_actor SET entity_id = $entity_a_id
WHERE entity_id = $entity_b_id;

-- Move subject relationships
UPDATE event_subject SET entity_id = $entity_a_id
WHERE entity_id = $entity_b_id;

-- Delete merged entity
DELETE FROM entity WHERE entity_id = $entity_b_id;

COMMIT;

-- Update graph (separate call)
-- Delete entity_b node, update edges to point to entity_a
```
