# V5 Completion Plan: End-to-End Consistency

**Status**: Planning
**Created**: 2026-01-01
**Goal**: Make V5 actually work end-to-end (Option A: legacy can break)

## Problem Summary

V5 is internally split:
- `remember()` writes to V5 Chroma (`content`/`chunks`)
- The worker + semantic search + graph expansion still read/assume legacy Chroma (`artifacts`/`artifact_chunks`) and AGE `graph_upsert`

This document details the minimal, concrete fixes needed for consistency.

---

## Phase 1: Fix V5 Chunk Storage (Evidence Pipeline Prerequisite)

**File**: `src/server.py` - `remember()` function
**Priority**: Critical
**Blocks**: Event extraction, evidence linking

### Current Problem

`ChunkingService.chunk_text()` already computes:
- `chunk.chunk_id` (stable, includes hash)
- `chunk.start_char`, `chunk.end_char`

But V5 `remember()` currently:
- Uses a different `chunk_id` format (invents its own)
- Does NOT store `start_char`/`end_char` in metadata

This breaks the worker and `event_evidence` alignment.

### Required Changes

**Location**: `src/server.py` lines ~1760-1810 (chunk storage loop)

```python
# BEFORE (broken):
for i, chunk in enumerate(chunks):
    chunk_id = f"{artifact_id}_chunk_{i}"  # Wrong format!
    chunks_col.add(
        ids=[chunk_id],
        documents=[chunk.content],
        metadatas=[{
            "content_id": artifact_id,
            "chunk_index": i,
            # Missing: start_char, end_char, token_count
        }],
        embeddings=[chunk_embedding]
    )

# AFTER (correct):
for i, chunk in enumerate(chunks):
    chunk_id = chunk.chunk_id  # Use stable hash-based ID from ChunkingService
    chunks_col.add(
        ids=[chunk_id],
        documents=[chunk.content],
        metadatas=[{
            "content_id": artifact_id,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "token_count": chunk.token_count,
        }],
        embeddings=[chunk_embedding]
    )
```

### Threshold Alignment

Current mismatch:
- Comment says "chunk if >= 900 tokens"
- `ChunkingService.should_chunk()` uses `single_piece_max` (defaults to 1200)

**Fix**: Use `chunking_service.should_chunk(content)` result instead of hardcoded check.

```python
# BEFORE:
if token_count >= 900:
    chunks = chunking_service.chunk_text(content, artifact_id)

# AFTER:
if chunking_service.should_chunk(content):
    chunks = chunking_service.chunk_text(content, artifact_id)
```

---

## Phase 2: Worker V5 Collection Support

**File**: `src/worker/event_worker.py`
**Priority**: Critical
**Blocks**: Event extraction from V5 content

### Current Problem

Worker fetches text from legacy collections:
```python
from storage.collections import get_artifacts_collection
collection = get_artifacts_collection(client)
results = collection.get(ids=[artifact_id])
```

### Required Changes

**Location**: `src/worker/event_worker.py` lines ~506-526

#### 2.1 Update `fetch_artifact_text()`

```python
# BEFORE:
def fetch_artifact_text(self, artifact_id: str) -> Optional[str]:
    collection = get_artifacts_collection(self.chroma_client)
    results = collection.get(ids=[artifact_id])
    ...

# AFTER:
def fetch_artifact_text(self, artifact_id: str) -> Optional[str]:
    from storage.collections import get_content_by_id
    result = get_content_by_id(self.chroma_client, artifact_id)
    if result:
        return result.get("content")
    return None
```

#### 2.2 Update `fetch_chunk_texts()`

```python
# BEFORE:
def fetch_chunk_texts(self, artifact_id: str, chunk_count: int) -> List[str]:
    collection = get_artifact_chunks_collection(self.chroma_client)
    ...

# AFTER:
def fetch_chunk_texts(self, artifact_id: str, chunk_count: int) -> List[Tuple[str, int, str, int]]:
    """
    Returns list of (chunk_text, chunk_index, chunk_id, start_char) tuples.
    """
    from storage.collections import get_v5_chunks_by_content
    chunks = get_v5_chunks_by_content(self.chroma_client, artifact_id)
    return [
        (chunk["content"], chunk["metadata"]["chunk_index"],
         chunk["id"], chunk["metadata"]["start_char"])
        for chunk in chunks
    ]
```

#### 2.3 Add Helper Function to collections.py

**File**: `src/storage/collections.py`

```python
def get_v5_chunks_by_content(client, content_id: str) -> List[Dict]:
    """
    Get all chunks for a V5 content item.

    Returns list of dicts with: id, content, metadata
    """
    chunks_col = get_chunks_collection(client)
    results = chunks_col.get(
        where={"content_id": content_id},
        include=["documents", "metadatas"]
    )

    chunks = []
    for i, chunk_id in enumerate(results.get("ids", [])):
        chunks.append({
            "id": chunk_id,
            "content": results["documents"][i],
            "metadata": results["metadatas"][i]
        })

    # Sort by chunk_index
    chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))
    return chunks
```

---

## Phase 3: Remove graph_upsert and AGE Dependency

**Files**:
- `src/services/job_queue_service.py`
- `src/worker/event_worker.py`

**Priority**: High
**Goal**: Stop accumulating useless `graph_upsert` jobs

### 3.1 JobQueueService Changes

**Location**: `src/services/job_queue_service.py` lines ~429-571

```python
# BEFORE:
async def write_events_atomic_v4(
    self,
    ...,
    enqueue_graph_upsert: bool = True  # Default True
):
    ...
    if enqueue_graph_upsert:
        # INSERT INTO event_jobs ... job_type 'graph_upsert'

# AFTER:
async def write_events_atomic_v4(
    self,
    ...,
    enqueue_graph_upsert: bool = False  # Default False - AGE removed
):
    ...
    # Remove the entire graph_upsert job insertion block
```

### 3.2 EventWorker Changes

**Location**: `src/worker/event_worker.py` lines ~400-413

Remove/disable:
- Don't claim `graph_upsert` jobs
- Remove `_process_graph_upsert_job()` method
- Remove `GraphService` initialization
- Remove `check_age_available()` usage

```python
# REMOVE these sections:
async def _process_graph_upsert_job(self, job: Dict) -> bool:
    """Process graph upsert job."""
    if not await self.graph_service.check_age_available():
        ...

# REMOVE from claim query:
# WHERE job_type IN ('extraction', 'graph_upsert')
# Change to:
# WHERE job_type = 'extraction'
```

### 3.3 What to KEEP

Keep V4 entity resolution - it writes to Postgres tables:
- `entity`
- `entity_alias`
- `entity_mention`
- `event_actor`
- `event_subject`

We're only cutting the AGE graph materialization, not the relational entity data.

---

## Phase 4: Postgres-Based Graph Expansion

**File**: `src/services/retrieval_service.py`
**Priority**: High
**Goal**: `expand=True` works without AGE

### Current Problem

```python
# Lines 647-665
if not self.pg_client or not self.graph_service:
    return [], []
related_events = await self.graph_service.expand_from_events(...)
```

Expansion requires AGE, which we're removing.

### Required Changes

#### 4.1 Remove graph_service Requirement

```python
# BEFORE:
if not self.pg_client or not self.graph_service:
    return [], []

# AFTER:
if not self.pg_client:
    return [], []
```

#### 4.2 New SQL-Based Expansion Method

Add to `retrieval_service.py`:

```python
async def expand_from_events_sql(
    self,
    seed_artifact_uids: List[str],
    graph_budget: int = 10,
    category_filters: Optional[List[str]] = None
) -> Tuple[List[RelatedContextItem], List[Dict]]:
    """
    Find related events via shared actors/subjects using Postgres joins.

    Algorithm:
    1. Get events for seed artifacts
    2. Find actors/subjects of those events
    3. Find other events with same actors/subjects
    4. Apply budget and category filters
    5. Return related events with evidence
    """

    # Step 1: Get seed event IDs
    seed_events_query = """
        SELECT event_id FROM semantic_event
        WHERE artifact_uid = ANY($1)
    """
    seed_events = await self.pg_client.fetch_all(seed_events_query, seed_artifact_uids)
    seed_event_ids = [e["event_id"] for e in seed_events]

    if not seed_event_ids:
        return [], []

    # Step 2-3: Find connected events via shared entities
    related_query = """
        WITH seed_entities AS (
            -- Get entities from seed events (actors + subjects)
            SELECT DISTINCT entity_id FROM (
                SELECT entity_id FROM event_actor WHERE event_id = ANY($1)
                UNION
                SELECT entity_id FROM event_subject WHERE event_id = ANY($1)
            ) combined
        ),
        connected_events AS (
            -- Find events that share these entities
            SELECT DISTINCT se.event_id, se.artifact_uid, se.category,
                   se.narrative, se.event_time, se.confidence
            FROM semantic_event se
            WHERE se.event_id != ALL($1)  -- Exclude seed events
            AND (
                EXISTS (
                    SELECT 1 FROM event_actor ea
                    WHERE ea.event_id = se.event_id
                    AND ea.entity_id IN (SELECT entity_id FROM seed_entities)
                )
                OR EXISTS (
                    SELECT 1 FROM event_subject es
                    WHERE es.event_id = se.event_id
                    AND es.entity_id IN (SELECT entity_id FROM seed_entities)
                )
            )
    """

    # Apply category filter if provided
    if category_filters:
        related_query += " AND se.category = ANY($2)"
        related_query += f" LIMIT {graph_budget}"
        related_query += ")"
        related_events = await self.pg_client.fetch_all(
            related_query + " SELECT * FROM connected_events",
            seed_event_ids, category_filters
        )
    else:
        related_query += f" LIMIT {graph_budget}"
        related_query += ")"
        related_events = await self.pg_client.fetch_all(
            related_query + " SELECT * FROM connected_events",
            seed_event_ids
        )

    # Build RelatedContextItem list
    related_items = []
    for event in related_events:
        related_items.append(RelatedContextItem(
            type="event",
            id=f"evt_{event['event_id']}",
            source_artifact_id=event["artifact_uid"],
            category=event["category"],
            narrative=event["narrative"],
            connection_type="shared_entity"
        ))

    # Fetch entities for response
    entities = await self._fetch_entities_for_events(
        [e["event_id"] for e in related_events]
    )

    return related_items, entities
```

#### 4.3 Update hybrid_search Calls

Replace `graph_service.expand_from_events()` with `expand_from_events_sql()`.

---

## Phase 5: V5 Collection Search in recall()

**File**: `src/server.py`
**Priority**: High
**Goal**: `recall(query=...)` searches V5 collections

### Current Problem

```python
# Lines 2069-2085
v4_result = await retrieval_service.hybrid_search_v4(...)
```

`hybrid_search_v4` searches `memory`/`artifacts`/`artifact_chunks`, not `content`/`chunks`.

### Required Changes

#### 5.1 Add V5 Search Method to RetrievalService

**File**: `src/services/retrieval_service.py`

```python
async def hybrid_search_v5(
    self,
    query: str,
    limit: int = 10,
    expand: bool = True,
    graph_budget: int = 10,
    graph_filters: Optional[Dict] = None,
    include_entities: bool = False,
    context_filter: Optional[str] = None,
    min_importance: Optional[float] = None,
) -> SearchResult:
    """
    V5 hybrid search over content and chunks collections.
    """
    # Generate query embedding
    query_embedding = self.embedding_service.generate_embedding(query)

    # Search V5 content collection
    content_col = get_content_collection(self.chroma_client)

    # Build where filter
    where_filter = {}
    if context_filter:
        where_filter["context"] = context_filter
    if min_importance is not None:
        where_filter["importance"] = {"$gte": min_importance}

    results = content_col.query(
        query_embeddings=[query_embedding],
        n_results=limit,
        where=where_filter if where_filter else None,
        include=["documents", "metadatas", "distances"]
    )

    # Build primary results
    primary_results = []
    for i, content_id in enumerate(results["ids"][0]):
        primary_results.append({
            "type": "artifact",
            "id": content_id,
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i]
        })

    # Graph expansion (if enabled)
    related = []
    entities = []
    if expand and primary_results:
        seed_uids = [f"uid_{r['id'].replace('art_', '')}" for r in primary_results[:1]]
        category_filters = graph_filters.get("categories") if graph_filters else None
        related, entities = await self.expand_from_events_sql(
            seed_uids, graph_budget, category_filters
        )

    return SearchResult(
        primary_results=primary_results,
        related_context=related if expand else [],
        entities=entities if include_entities else []
    )
```

#### 5.2 Update server.py recall()

```python
# BEFORE:
v4_result = await retrieval_service.hybrid_search_v4(...)

# AFTER:
v5_result = await retrieval_service.hybrid_search_v5(
    query=query,
    limit=limit,
    expand=expand,
    graph_budget=graph_budget,
    graph_filters={"categories": graph_filters} if graph_filters else None,
    include_entities=include_entities,
    context_filter=context,
    min_importance=min_importance,
)
```

---

## Phase 6: Deployment Config Cleanup

**Files**:
- `.claude-workspace/deployment/docker-compose.yml`
- `.claude-workspace/deployment/.env.example`

**Priority**: Low (cleanup)

### Changes

Remove or comment out misleading V4 graph/AGE environment variables:

```yaml
# REMOVE these from docker-compose.yml:
# V4_GRAPH_ENABLED: "true"
# AGE_DATABASE: "..."
# GRAPH_WORKER_ENABLED: "true"

# ADD V5 clarity:
# V5_MODE: "true"
# Note: Graph expansion uses Postgres joins, no AGE required
```

---

## Definition of Done

- [ ] `remember()` writes content + chunks with offsets (`start_char`, `end_char`, stable `chunk_id`)
- [ ] Worker extracts events/entities successfully from V5 collections
- [ ] `recall(query=...)` returns results from V5 collections
- [ ] `expand=True` returns non-empty related via Postgres joins, with no AGE
- [ ] No `graph_upsert` jobs accumulate in `event_jobs`
- [ ] All V5 tests pass (80/80)
- [ ] E2E test confirms full pipeline works

---

## Implementation Order

1. **Phase 1** - Fix chunk storage (blocks everything else)
2. **Phase 2** - Worker V5 support (enables extraction)
3. **Phase 3** - Remove graph_upsert (stops useless jobs)
4. **Phase 4** - Postgres expansion (enables graph features)
5. **Phase 5** - V5 search in recall (completes user-facing API)
6. **Phase 6** - Config cleanup (polish)

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/server.py` | Phase 1 (chunks), Phase 5 (recall) |
| `src/storage/collections.py` | Phase 2 (add `get_v5_chunks_by_content`) |
| `src/worker/event_worker.py` | Phase 2 (V5 fetch), Phase 3 (remove graph_upsert) |
| `src/services/job_queue_service.py` | Phase 3 (disable graph_upsert default) |
| `src/services/retrieval_service.py` | Phase 4 (SQL expansion), Phase 5 (V5 search) |
| `deployment/docker-compose.yml` | Phase 6 (cleanup) |
| `deployment/.env.example` | Phase 6 (cleanup) |

---

## Test Updates Required

After implementation, update tests to:
1. Verify chunk metadata includes offsets
2. Mock V5 collections in worker tests
3. Test SQL-based graph expansion
4. Test `hybrid_search_v5` method
5. Add E2E test for full pipeline

---

*Plan created: 2026-01-01*
*Ready for implementation: awaiting approval*
