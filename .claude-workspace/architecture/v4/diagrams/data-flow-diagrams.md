# V4 Data Flow Diagrams

## Overview

This document describes the data flows in the V4 MCP Memory system, focusing on the new entity resolution and graph expansion features.

---

## 1. Artifact Ingestion Flow (V4 Extended)

The ingestion flow is enhanced to trigger entity resolution during event extraction.

```
+------------------------------------------------------------------+
|                     ARTIFACT INGESTION (V4)                        |
+------------------------------------------------------------------+

User: artifact_ingest(text, artifact_type, source_id, ...)
                            |
                            v
+------------------------------------------------------------------+
| PHASE 1: Validation & Hashing                                      |
|                                                                    |
|  1. Validate inputs                                                |
|  2. Generate artifact_uid (stable):                                |
|     - If source_id: sha256(source_system:source_id)               |
|     - Else: random UUID                                           |
|  3. Generate revision_id: sha256(content)                         |
|  4. Check for duplicate revision in Postgres                       |
|     - Same uid + same revision_id = NO-OP                         |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 2: Chunking & Embedding                                      |
|                                                                    |
|  5. Count tokens via tiktoken                                      |
|  6. If > 1200 tokens: chunk (900 tok, 100 overlap)                |
|  7. Generate embeddings (OpenAI batch API)                        |
|  8. Write to ChromaDB:                                            |
|     - artifacts collection (full text or summary)                  |
|     - artifact_chunks collection (if chunked)                      |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 3: Revision Tracking & Job Enqueue                           |
|                                                                    |
|  9.  BEGIN TRANSACTION                                             |
|  10. Mark old revisions as not latest                              |
|  11. INSERT INTO artifact_revision                                 |
|  12. INSERT INTO event_jobs (job_type='extract_events')           |
|  13. COMMIT                                                        |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
Return to user (< 1s):
{
  "artifact_id": "art_abc123",
  "artifact_uid": "uid_stable",
  "revision_id": "rev_unique",
  "job_id": "job_xyz789",
  "job_status": "PENDING"
}
```

---

## 2. Event Extraction Flow (V4 Extended)

The extraction flow is extended to include entity resolution and graph job enqueueing.

```
+------------------------------------------------------------------+
|               EVENT EXTRACTION (V4 EXTENDED)                        |
+------------------------------------------------------------------+

Event Worker polls event_jobs table
                            |
                            v
+------------------------------------------------------------------+
| PHASE 1: Job Claiming (Atomic)                                     |
|                                                                    |
|  BEGIN TRANSACTION                                                 |
|    SELECT job_id, artifact_uid, revision_id                       |
|    FROM event_jobs                                                |
|    WHERE status = 'PENDING'                                       |
|      AND next_run_at <= now()                                     |
|    FOR UPDATE SKIP LOCKED LIMIT 1;                                |
|                                                                    |
|    UPDATE event_jobs SET                                          |
|      status = 'PROCESSING',                                       |
|      locked_at = now(),                                           |
|      attempts = attempts + 1;                                     |
|  COMMIT                                                           |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 2: Fetch Artifact Text                                       |
|                                                                    |
|  - Load artifact_revision metadata from Postgres                  |
|  - If unchunked: Fetch from artifacts collection                  |
|  - If chunked: Fetch all chunks, sort by index                    |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 3: Extract Events + Entities (Prompt A Extended)             |
|                                                                    |
|  For each chunk:                                                  |
|    Call OpenAI with extended Prompt A:                            |
|    - Extract events (same as V3)                                  |
|    - Extract entities_mentioned (NEW V4):                         |
|      {                                                            |
|        "surface_form": "Alice Chen",                              |
|        "canonical_suggestion": "Alice Chen",                      |
|        "type": "person",                                          |
|        "context_clues": {                                         |
|          "role": "Engineering Manager",                           |
|          "org": "Acme Corp",                                      |
|          "email": "achen@acme.com"                                |
|        },                                                         |
|        "aliases_in_doc": ["Alice", "A. Chen"],                    |
|        "confidence": 0.95,                                        |
|        "start_char": 150,                                         |
|        "end_char": 160                                            |
|      }                                                            |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 4: Canonicalize Events (Prompt B - unchanged from V3)        |
|                                                                    |
|  - Merge duplicate events across chunks                           |
|  - Combine evidence spans                                         |
|  - Resolve entity aliases within document                         |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 5: Entity Resolution (NEW V4)                                |
|                                                                    |
|  For each entity_mentioned:                                       |
|    +------------------------------------------------------+       |
|    | 5a. Generate Context Embedding                        |       |
|    |     Text: "{name}, {type}, {role}, {org}"            |       |
|    |     Model: text-embedding-3-large                    |       |
|    +------------------------------------------------------+       |
|                            |                                       |
|                            v                                       |
|    +------------------------------------------------------+       |
|    | 5b. Find Dedup Candidates                             |       |
|    |     SQL: SELECT * FROM entity                        |       |
|    |          WHERE entity_type = $type                   |       |
|    |            AND context_embedding <=> $emb < 0.15     |       |
|    |          ORDER BY similarity LIMIT 5                 |       |
|    +------------------------------------------------------+       |
|                            |                                       |
|              +-----------+-+-----------+                           |
|              |             |           |                           |
|              v             v           v                           |
|    No candidates    1+ candidates   Many candidates                |
|              |             |           |                           |
|              v             v           v                           |
|    +------------------------------------------------------+       |
|    | 5c. Decision Logic                                    |       |
|    |                                                       |       |
|    |  No candidates:                                      |       |
|    |    -> CREATE new entity                              |       |
|    |                                                       |       |
|    |  Candidates found:                                   |       |
|    |    -> Call LLM confirmation for each pair           |       |
|    |    -> LLM returns: same | different | uncertain      |       |
|    |                                                       |       |
|    |  Decision actions:                                   |       |
|    |    same     -> MERGE: add alias, link mention       |       |
|    |    different -> CREATE: new entity                  |       |
|    |    uncertain -> CREATE: needs_review=true,          |       |
|    |                 add POSSIBLY_SAME edge              |       |
|    +------------------------------------------------------+       |
|                            |                                       |
|                            v                                       |
|    +------------------------------------------------------+       |
|    | 5d. Write Entity Records                              |       |
|    |     - INSERT INTO entity (if new)                    |       |
|    |     - INSERT INTO entity_alias (if merged)           |       |
|    |     - INSERT INTO entity_mention (always)            |       |
|    +------------------------------------------------------+       |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 6: Write Events with Entity Links (Atomic Transaction)       |
|                                                                    |
|  BEGIN TRANSACTION                                                 |
|                                                                    |
|    -- Delete old events (replace-on-success)                      |
|    DELETE FROM semantic_event                                      |
|    WHERE artifact_uid = $uid AND revision_id = $rev;              |
|                                                                    |
|    For each canonical event:                                       |
|      INSERT INTO semantic_event (...) RETURNING event_id;         |
|                                                                    |
|      For each evidence span:                                       |
|        INSERT INTO event_evidence (...);                          |
|                                                                    |
|      -- V4: Link to resolved entities                             |
|      For each actor:                                               |
|        entity_id = entity_map[actor.ref]                          |
|        INSERT INTO event_actor (event_id, entity_id, role);       |
|                                                                    |
|      For each subject:                                             |
|        entity_id = entity_map[subject.ref]                        |
|        INSERT INTO event_subject (event_id, entity_id);           |
|                                                                    |
|    -- V4: Enqueue graph upsert in same transaction                |
|    INSERT INTO event_jobs (                                        |
|      job_type = 'graph_upsert',                                   |
|      artifact_uid = $uid,                                         |
|      revision_id = $rev,                                          |
|      status = 'PENDING'                                           |
|    );                                                              |
|                                                                    |
|  COMMIT                                                            |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 7: Mark Job Done                                             |
|                                                                    |
|  UPDATE event_jobs SET status = 'DONE' WHERE job_id = $job_id;    |
|                                                                    |
+------------------------------------------------------------------+
```

---

## 3. Graph Upsert Flow (NEW V4)

A new job type that materializes entity and event data into the Apache AGE graph.

```
+------------------------------------------------------------------+
|                     GRAPH UPSERT (V4 NEW)                          |
+------------------------------------------------------------------+

Event Worker claims job_type='graph_upsert'
                            |
                            v
+------------------------------------------------------------------+
| PHASE 1: Load Data from Postgres                                   |
|                                                                    |
|  - SELECT events from semantic_event                              |
|    WHERE artifact_uid = $uid AND revision_id = $rev               |
|                                                                    |
|  - SELECT entities via event_actor and event_subject JOINs        |
|                                                                    |
|  - SELECT uncertain entity pairs (needs_review = true)            |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 2: Upsert Entity Nodes                                       |
|                                                                    |
|  For each entity:                                                 |
|    MERGE (e:Entity {entity_id: $id})                              |
|    ON CREATE SET                                                  |
|      e.canonical_name = $name,                                    |
|      e.type = $type,                                              |
|      e.role = $role,                                              |
|      e.organization = $org                                        |
|    ON MATCH SET                                                   |
|      e.canonical_name = $name,                                    |
|      e.role = COALESCE($role, e.role),                           |
|      e.organization = COALESCE($org, e.organization)              |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 3: Upsert Event Nodes                                        |
|                                                                    |
|  For each event:                                                  |
|    MERGE (ev:Event {event_id: $id})                               |
|    ON CREATE SET                                                  |
|      ev.category = $category,                                     |
|      ev.narrative = $narrative,                                   |
|      ev.artifact_uid = $uid,                                      |
|      ev.revision_id = $rev,                                       |
|      ev.event_time = $time,                                       |
|      ev.confidence = $conf                                        |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 4: Upsert ACTED_IN Edges                                     |
|                                                                    |
|  For each (entity_id, event_id, role) in event_actor:             |
|    MATCH (e:Entity {entity_id: $entity_id})                       |
|    MATCH (ev:Event {event_id: $event_id})                         |
|    MERGE (e)-[r:ACTED_IN]->(ev)                                   |
|    ON CREATE SET r.role = $role                                   |
|    ON MATCH SET r.role = $role                                    |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 5: Upsert ABOUT Edges                                        |
|                                                                    |
|  For each (event_id, entity_id) in event_subject:                 |
|    MATCH (ev:Event {event_id: $event_id})                         |
|    MATCH (e:Entity {entity_id: $entity_id})                       |
|    MERGE (ev)-[r:ABOUT]->(e)                                      |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 6: Upsert POSSIBLY_SAME Edges                                |
|                                                                    |
|  For each uncertain entity pair:                                  |
|    MATCH (e1:Entity {entity_id: $id_a})                           |
|    MATCH (e2:Entity {entity_id: $id_b})                           |
|    MERGE (e1)-[r:POSSIBLY_SAME]->(e2)                             |
|    ON CREATE SET                                                  |
|      r.confidence = $conf,                                        |
|      r.reason = $reason                                           |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| PHASE 7: Mark Job Done                                             |
|                                                                    |
|  UPDATE event_jobs SET status = 'DONE' WHERE job_id = $job_id;    |
|                                                                    |
+------------------------------------------------------------------+
```

---

## 4. Graph Expansion Flow (hybrid_search)

How `hybrid_search` uses the graph when `graph_expand=true`.

```
+------------------------------------------------------------------+
|               GRAPH EXPANSION IN HYBRID_SEARCH                      |
+------------------------------------------------------------------+

hybrid_search(query="Alice's decisions", graph_expand=true, graph_budget=10)
                            |
                            v
+------------------------------------------------------------------+
| STEP 1: Standard V3 Search                                         |
|                                                                    |
|  1. Generate query embedding                                       |
|  2. Search collections (artifacts, chunks, memory)                |
|  3. RRF merge + deduplication                                     |
|  4. Get primary_results (limit=5)                                 |
|                                                                    |
|  Result: [Event A, Chunk B, Event C, Artifact D, Event E]         |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 2: Collect Seed Event IDs (up to graph_seed_limit)            |
|                                                                    |
|  For each primary result:                                         |
|                                                                    |
|    If result.type == "event":                                     |
|      seed_ids.append(result.event_id)                             |
|                                                                    |
|    If result.type == "chunk":                                     |
|      (artifact_uid, revision_id) = map_chunk_to_revision(chunk_id)|
|      events = get_events_for_revision(uid, rev)                   |
|      seed_ids.extend([e.event_id for e in events])                |
|                                                                    |
|    If result.type == "artifact":                                  |
|      (artifact_uid, revision_id) = get_latest_revision(artifact_id)|
|      events = get_events_for_revision(uid, rev)                   |
|      seed_ids.extend([e.event_id for e in events])                |
|                                                                    |
|  Limit to graph_seed_limit (default: 5)                           |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 3: Graph 1-Hop Expansion via Cypher                           |
|                                                                    |
|  SELECT * FROM cypher('nur', $$                                   |
|                                                                    |
|    -- Start from seed events                                      |
|    MATCH (seed:Event) WHERE seed.event_id IN $seed_ids            |
|                                                                    |
|    -- Find connected entities (actors and subjects)               |
|    OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)              |
|    OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)               |
|                                                                    |
|    -- Collect all connected entities                              |
|    WITH seed,                                                     |
|         collect(DISTINCT actor) + collect(DISTINCT subject)       |
|         AS entities                                               |
|    UNWIND entities AS entity                                      |
|                                                                    |
|    -- Find other events connected to those entities               |
|    MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)               |
|    WHERE NOT related.event_id IN $seed_ids                        |
|      AND ($category_filter IS NULL                                |
|           OR related.category IN $category_filter)                |
|                                                                    |
|    -- Return related events with connection reason                |
|    RETURN DISTINCT related, entity,                               |
|           CASE                                                    |
|             WHEN (entity)-[:ACTED_IN]->(related)                  |
|               THEN 'same_actor:' + entity.canonical_name          |
|             ELSE 'same_subject:' + entity.canonical_name          |
|           END AS reason                                           |
|    ORDER BY related.event_time DESC NULLS LAST,                   |
|             related.confidence DESC                               |
|    LIMIT $budget                                                  |
|                                                                    |
|  $$, $params) AS (related agtype, entity agtype, reason agtype);  |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 4: Fetch Full Event Data from Postgres                        |
|                                                                    |
|  For each related event from graph:                               |
|    SELECT e.*, array_agg(ev.*) as evidence                        |
|    FROM semantic_event e                                          |
|    LEFT JOIN event_evidence ev ON e.event_id = ev.event_id        |
|    WHERE e.event_id = $related_event_id                           |
|    GROUP BY e.event_id;                                           |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 5: Format Related Context                                     |
|                                                                    |
|  related_context = []                                             |
|  for row in graph_results:                                        |
|    event = fetch_event_with_evidence(row.related.event_id)        |
|    related_context.append({                                       |
|      "type": "event",                                             |
|      "id": str(event.event_id),                                   |
|      "category": event.category,                                  |
|      "reason": row.reason,  # e.g., "same_actor:Alice Chen"       |
|      "summary": event.narrative,                                  |
|      "event_time": event.event_time.isoformat(),                  |
|      "evidence": [format_evidence(e) for e in event.evidence]     |
|    })                                                             |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 6: Fetch Entities (if include_entities=true)                  |
|                                                                    |
|  all_event_ids = seed_ids + [r.id for r in related_context]       |
|                                                                    |
|  SELECT e.*,                                                      |
|         array_agg(DISTINCT ea.alias) as aliases,                  |
|         count(em.mention_id) as mention_count                     |
|  FROM entity e                                                    |
|  LEFT JOIN entity_alias ea ON e.entity_id = ea.entity_id          |
|  LEFT JOIN entity_mention em ON e.entity_id = em.entity_id        |
|  WHERE e.entity_id IN (                                           |
|    SELECT entity_id FROM event_actor WHERE event_id = ANY($ids)   |
|    UNION                                                          |
|    SELECT entity_id FROM event_subject WHERE event_id = ANY($ids) |
|  )                                                                |
|  GROUP BY e.entity_id;                                            |
|                                                                    |
|  entities = [{                                                    |
|    "entity_id": str(e.entity_id),                                 |
|    "name": e.canonical_name,                                      |
|    "type": e.entity_type,                                         |
|    "role": e.role,                                                |
|    "organization": e.organization,                                |
|    "aliases": e.aliases,                                          |
|    "mention_count": e.mention_count                               |
|  } for e in result]                                               |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 7: Build Response                                             |
|                                                                    |
|  return {                                                         |
|    "primary_results": [                                           |
|      # Standard V3 format                                         |
|    ],                                                             |
|    "related_context": [                                           |
|      {                                                            |
|        "type": "event",                                           |
|        "id": "uuid",                                              |
|        "category": "Decision",                                    |
|        "reason": "same_actor:Alice Chen",                         |
|        "summary": "Team decided to use Postgres...",              |
|        "event_time": "2024-03-15T14:30:00Z",                      |
|        "evidence": [...]                                          |
|      }                                                            |
|    ],                                                             |
|    "entities": [                                                  |
|      {                                                            |
|        "entity_id": "uuid",                                       |
|        "name": "Alice Chen",                                      |
|        "type": "person",                                          |
|        "role": "Engineering Manager",                             |
|        "organization": "Acme Corp",                               |
|        "aliases": ["Alice", "A. Chen"],                           |
|        "mention_count": 5                                         |
|      }                                                            |
|    ],                                                             |
|    "expand_options": [                                            |
|      {"name": "graph_expand", "description": "..."},              |
|      {"name": "include_memory", "description": "..."},            |
|      {"name": "expand_neighbors", "description": "..."},          |
|      {"name": "graph_budget", "description": "..."},              |
|      {"name": "graph_filters", "description": "..."}              |
|    ]                                                              |
|  }                                                                |
|                                                                    |
+------------------------------------------------------------------+
```

---

## 5. Chunk-to-Revision Mapping

Critical for connecting vector search results to semantic events.

```
+------------------------------------------------------------------+
|                CHUNK-TO-REVISION MAPPING                            |
+------------------------------------------------------------------+

Input: chunk_id = "art_abc123::chunk::002::xyz789"
                            |
                            v
+------------------------------------------------------------------+
| STEP 1: Parse Chunk ID                                             |
|                                                                    |
|  Format: {artifact_id}::chunk::{chunk_index}::{hash}              |
|  artifact_id = "art_abc123"                                       |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 2: Get Latest Revision                                        |
|                                                                    |
|  SELECT artifact_uid, revision_id                                 |
|  FROM artifact_revision                                            |
|  WHERE artifact_id = $artifact_id                                 |
|    AND is_latest = true;                                          |
|                                                                    |
|  Result: (artifact_uid="uid_stable", revision_id="rev_unique")    |
|                                                                    |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
| STEP 3: Get Events for Revision                                    |
|                                                                    |
|  SELECT event_id                                                  |
|  FROM semantic_event                                               |
|  WHERE artifact_uid = $artifact_uid                               |
|    AND revision_id = $revision_id;                                |
|                                                                    |
|  Result: [event_id_1, event_id_2, event_id_3]                     |
|                                                                    |
+------------------------------------------------------------------+
```

---

## Summary: Job Types

| Job Type | Trigger | Output | V3/V4 |
|----------|---------|--------|-------|
| `extract_events` | artifact_ingest | events + entities + graph_upsert job | V3 (extended in V4) |
| `graph_upsert` | extract_events completion | graph nodes/edges | V4 NEW |
