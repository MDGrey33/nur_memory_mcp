# V4 Component Diagram

## System Context

```
+------------------------------------------------------------------+
|                         MCP CLIENTS                                |
|  +-------------+  +---------------+  +----------+  +----------+   |
|  | Claude Code |  | Claude Desktop |  | Cursor   |  | Other    |   |
|  +-------------+  +---------------+  +----------+  +----------+   |
+------------------------------------------------------------------+
         |                    |               |              |
         +--------------------+---------------+--------------+
                              |
                   MCP Protocol (Streamable HTTP)
                              |
                              v
+------------------------------------------------------------------+
|                        MCP SERVER                                  |
|                     (mcp-server:3000)                              |
+------------------------------------------------------------------+
         |                    |               |              |
         v                    v               v              v
+----------------+  +------------------+  +----------+  +-----------+
|    ChromaDB    |  |     Postgres     |  | OpenAI   |  | Event     |
|   (Vectors)    |  |  (Events/Graph)  |  |   API    |  | Worker    |
|   :8001        |  |     :5432        |  |          |  |           |
+----------------+  +------------------+  +----------+  +-----------+
```

## V4 MCP Server Components

```
+------------------------------------------------------------------------+
|                           MCP SERVER                                     |
|                                                                          |
|  +------------------------------------------------------------------+  |
|  |                        TOOL LAYER (18 tools)                       |  |
|  |                                                                    |  |
|  |  V2 Tools (12):              V3 Tools (5):        V4 Tools (1):   |  |
|  |  +------------------+        +-----------------+   +--------------+|  |
|  |  | memory_store     |        | event_search    |   | graph_health ||  |
|  |  | memory_search    |        | event_get       |   | (internal)   ||  |
|  |  | memory_list      |        | event_list_rev  |   +--------------+|  |
|  |  | memory_delete    |        | event_reextract |                   |  |
|  |  | history_append   |        | job_status      |                   |  |
|  |  | history_get      |        +-----------------+                   |  |
|  |  | artifact_ingest  |                                              |  |
|  |  | artifact_search  |        V4 Enhanced:                          |  |
|  |  | artifact_get     |        +--------------------------+          |  |
|  |  | artifact_delete  |        | hybrid_search            |          |  |
|  |  | hybrid_search    |------->| + graph_expand           |          |  |
|  |  | embedding_health |        | + graph_depth            |          |  |
|  |  +------------------+        | + graph_budget           |          |  |
|  |                              | + graph_seed_limit       |          |  |
|  |                              | + graph_filters          |          |  |
|  |                              | + include_entities       |          |  |
|  |                              +--------------------------+          |  |
|  +------------------------------------------------------------------+  |
|                                    |                                    |
|  +------------------------------------------------------------------+  |
|  |                       SERVICE LAYER                                |  |
|  |                                                                    |  |
|  |  V2 Services:               V3 Services:        V4 Services (NEW): |  |
|  |  +------------------+       +----------------+   +----------------+|  |
|  |  | EmbeddingService |       | PostgresClient |   | EntityRes.Svc  ||  |
|  |  | ChunkingService  |       | JobQueueService|   | GraphService   ||  |
|  |  | RetrievalService |       | EventExtraction|   +----------------+|  |
|  |  | PrivacyService   |       +----------------+                     |  |
|  |  +------------------+                                              |  |
|  |                                                                    |  |
|  |  Enhanced V4:                                                      |  |
|  |  +--------------------------------------------------------------+|  |
|  |  | RetrievalService (EXTENDED)                                   ||  |
|  |  |  + hybrid_search() now supports graph_expand                  ||  |
|  |  |  + expand_via_graph() for 1-hop traversal                     ||  |
|  |  |  + chunk_to_revision_mapping()                                ||  |
|  |  +--------------------------------------------------------------+|  |
|  +------------------------------------------------------------------+  |
|                                    |                                    |
|  +------------------------------------------------------------------+  |
|  |                       STORAGE LAYER                                |  |
|  |                                                                    |  |
|  |  +------------------+  +---------------------+  +----------------+ |  |
|  |  | ChromaDB Client  |  | PostgresClient      |  | AGE Client     | |  |
|  |  |                  |  |                     |  | (NEW)          | |  |
|  |  | - artifacts      |  | - artifact_revision |  | - graph 'nur'  | |  |
|  |  | - artifact_chunks|  | - semantic_event    |  | - Entity nodes | |  |
|  |  | - memory         |  | - event_evidence    |  | - Event nodes  | |  |
|  |  +------------------+  | - event_jobs        |  | - Edges        | |  |
|  |                        | - entity (NEW)      |  +----------------+ |  |
|  |                        | - entity_alias (NEW)|                     |  |
|  |                        | - entity_mention(NEW)                     |  |
|  |                        | - event_actor (NEW) |                     |  |
|  |                        | - event_subject(NEW)|                     |  |
|  |                        +---------------------+                     |  |
|  +------------------------------------------------------------------+  |
+------------------------------------------------------------------------+
```

## V4 Service Dependencies

```
+-------------------+         +-------------------+
|  hybrid_search    |         | artifact_ingest   |
|  (tool)           |         | (tool)            |
+--------+----------+         +--------+----------+
         |                             |
         v                             v
+-------------------+         +-------------------+
| RetrievalService  |         | PostgresClient    |
| (enhanced)        |         |                   |
+--------+----------+         +--------+----------+
         |                             |
         |   +---------------+         |
         +-->| GraphService  |<--------+
             | (NEW)         |         |
             +-------+-------+         |
                     |                 |
                     v                 v
         +--------------------+   +-------------------+
         | Apache AGE         |   | event_jobs queue  |
         | (Postgres ext)     |   |                   |
         +--------------------+   +--------+----------+
                                          |
                                          v
                                  +-------------------+
                                  | Event Worker      |
                                  | (extended)        |
                                  +--------+----------+
                                           |
                     +---------------------+---------------------+
                     |                     |                     |
                     v                     v                     v
          +-------------------+  +------------------+  +-------------------+
          | EventExtraction   |  | EntityResolution |  | GraphService      |
          | Service           |  | Service (NEW)    |  | (materialize)     |
          +-------------------+  +------------------+  +-------------------+
```

## New V4 Services

### EntityResolutionService

```
+-----------------------------------------------------------------------+
|                     EntityResolutionService                            |
+-----------------------------------------------------------------------+
|                                                                       |
|  Public Methods:                                                      |
|  +-------------------------------------------------------------------+|
|  | resolve_entity(                                                   ||
|  |   surface_form: str,                                              ||
|  |   canonical_suggestion: str,                                      ||
|  |   entity_type: str,                                               ||
|  |   context_clues: dict,                                            ||
|  |   artifact_uid: str,                                              ||
|  |   revision_id: str                                                ||
|  | ) -> EntityResolutionResult                                       ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  Internal Methods:                                                    |
|  +-------------------------------------------------------------------+|
|  | generate_context_embedding(name, type, role, org) -> vector       ||
|  | find_dedup_candidates(type, embedding, threshold) -> list[Entity] ||
|  | confirm_merge_with_llm(entity_a, entity_b, ctx_a, ctx_b) -> Decision|
|  +-------------------------------------------------------------------+|
|                                                                       |
|  Dependencies:                                                        |
|  +-------------+  +-------------+  +-------------+                    |
|  | OpenAI API  |  | PostgresDB  |  | pgvector    |                    |
|  | (embeddings)|  | (entity tbl)|  | (similarity)|                    |
|  +-------------+  +-------------+  +-------------+                    |
+-----------------------------------------------------------------------+
```

### GraphService

```
+-----------------------------------------------------------------------+
|                          GraphService                                  |
+-----------------------------------------------------------------------+
|                                                                       |
|  Public Methods:                                                      |
|  +-------------------------------------------------------------------+|
|  | upsert_entity_node(entity: Entity) -> None                        ||
|  | upsert_event_node(event: SemanticEvent) -> None                   ||
|  | upsert_acted_in_edge(entity_id, event_id, role) -> None           ||
|  | upsert_about_edge(event_id, entity_id) -> None                    ||
|  | upsert_possibly_same_edge(entity_a, entity_b, conf, reason) -> None|
|  | expand_from_events(seed_ids, budget, filters) -> list[RelatedCtx]||
|  | get_graph_health() -> GraphHealthStats                            ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  Internal Methods:                                                    |
|  +-------------------------------------------------------------------+|
|  | execute_cypher(query: str, params: dict) -> list                  ||
|  | parse_agtype_result(result) -> dict                               ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  Dependencies:                                                        |
|  +-------------+  +-------------+                                     |
|  | PostgresDB  |  | Apache AGE  |                                     |
|  | (asyncpg)   |  | (extension) |                                     |
|  +-------------+  +-------------+                                     |
+-----------------------------------------------------------------------+
```

### Enhanced RetrievalService

```
+-----------------------------------------------------------------------+
|                   RetrievalService (V4 Enhanced)                       |
+-----------------------------------------------------------------------+
|                                                                       |
|  V3 Methods (unchanged):                                              |
|  +-------------------------------------------------------------------+|
|  | merge_results_rrf(results_by_collection, limit) -> MergedResult[] ||
|  | deduplicate_by_artifact(results) -> MergedResult[]                ||
|  | _search_collection(name, embedding, limit, filters) -> SearchResult[]|
|  | _expand_neighbors(results) -> None                                ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  V4 Methods (NEW):                                                    |
|  +-------------------------------------------------------------------+|
|  | hybrid_search(                                                    ||
|  |   query: str,                                                     ||
|  |   limit: int = 5,                                                 ||
|  |   include_memory: bool = False,                                   ||
|  |   expand_neighbors: bool = False,                                 ||
|  |   filters: dict = None,                                           ||
|  |   # V4 new parameters:                                            ||
|  |   graph_expand: bool = False,                                     ||
|  |   graph_depth: int = 1,                                           ||
|  |   graph_budget: int = 10,                                         ||
|  |   graph_seed_limit: int = 5,                                      ||
|  |   graph_filters: list[str] = None,                                ||
|  |   include_entities: bool = True                                   ||
|  | ) -> HybridSearchResult                                           ||
|  +-------------------------------------------------------------------+|
|  |                                                                   ||
|  | expand_via_graph(                                                 ||
|  |   primary_results: list[MergedResult],                            ||
|  |   params: GraphExpandParams                                       ||
|  | ) -> GraphExpansionResult                                         ||
|  +-------------------------------------------------------------------+|
|  |                                                                   ||
|  | map_chunk_to_revision(artifact_id: str) -> (artifact_uid, rev_id) ||
|  | collect_seed_event_ids(results, seed_limit) -> list[UUID]         ||
|  | fetch_entities_for_events(event_ids) -> list[EntityInfo]          ||
|  +-------------------------------------------------------------------+|
|                                                                       |
|  Dependencies:                                                        |
|  +-----------------+  +-----------------+  +-----------------+        |
|  | EmbeddingService|  | ChromaDB Client |  | GraphService    |        |
|  +-----------------+  +-----------------+  | (NEW)           |        |
|                                            +-----------------+        |
+-----------------------------------------------------------------------+
```

## Data Flow: hybrid_search with graph_expand=true

```
                    hybrid_search(query, graph_expand=true)
                                     |
                                     v
                    +--------------------------------+
                    | 1. Generate query embedding    |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 2. Search collections:         |
                    |    - artifacts                 |
                    |    - artifact_chunks           |
                    |    - memory (if requested)     |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 3. RRF merge + deduplication   |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 4. Get primary_results         |
                    +--------------------------------+
                                     |
        +----------------------------+----------------------------+
        |                            |                            |
        v                            v                            v
+----------------+      +------------------------+     +-------------------+
| If chunk result|      | If artifact result     |     | If event result   |
| Map to revision|      | Get latest revision    |     | Use event_id      |
+----------------+      +------------------------+     +-------------------+
        |                            |                            |
        +----------------------------+----------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 5. Collect seed_event_ids      |
                    |    (up to graph_seed_limit)    |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 6. GraphService.expand_from_   |
                    |    events(seed_ids, budget,    |
                    |    category_filter)            |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 7. Cypher 1-hop traversal:     |
                    |    seed -> entities -> related |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 8. Fetch full event data +     |
                    |    evidence from Postgres      |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 9. Format related_context      |
                    |    with reason labels          |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 10. Fetch entities for events  |
                    |     (if include_entities=true) |
                    +--------------------------------+
                                     |
                                     v
                    +--------------------------------+
                    | 11. Return HybridSearchResult: |
                    |     - primary_results          |
                    |     - related_context          |
                    |     - entities                 |
                    |     - expand_options           |
                    +--------------------------------+
```

## Container Architecture (V4)

```
+------------------------------------------------------------------------+
|                          Docker Compose                                  |
+------------------------------------------------------------------------+
|                                                                          |
|  +------------------+    +------------------+    +------------------+    |
|  |   mcp-server     |    |     chroma       |    |    postgres      |    |
|  |                  |    |                  |    |                  |    |
|  |  Port: 3000      |    |  Port: 8001:8000 |    |  Port: 5432:5432 |    |
|  |                  |    |                  |    |                  |    |
|  |  - FastMCP       |    |  - Vector store  |    |  - artifact_rev  |    |
|  |  - 18 MCP tools  |    |  - artifacts     |    |  - semantic_event|    |
|  |  - Service layer |    |  - chunks        |    |  - event_jobs    |    |
|  |                  |    |  - memory        |    |  - entity (NEW)  |    |
|  |  Depends on:     |    |                  |    |  - entity_alias  |    |
|  |  - chroma        |    |                  |    |  - event_actor   |    |
|  |  - postgres      |    |                  |    |                  |    |
|  +------------------+    +------------------+    |  Extensions:     |    |
|           |                       |             |  - pgvector      |    |
|           |                       |             |  - age (NEW)     |    |
|           v                       v             +------------------+    |
|  +------------------+                                    ^              |
|  |   event-worker   |                                    |              |
|  |                  |                                    |              |
|  |  - Job processor |------------------------------------|              |
|  |  - Event extract |                                                   |
|  |  - Entity resol. |                                                   |
|  |  - Graph upsert  |                                                   |
|  |                  |                                                   |
|  |  Depends on:     |                                                   |
|  |  - chroma        |                                                   |
|  |  - postgres      |                                                   |
|  +------------------+                                                   |
|                                                                          |
+------------------------------------------------------------------------+
```

## Key Changes from V3

| Component | V3 | V4 |
|-----------|----|----|
| MCP Tools | 17 | 18 (+ graph_health internal) |
| Services | 6 | 8 (+ EntityResolutionService, GraphService) |
| Postgres Tables | 4 | 9 (+ 5 entity tables) |
| Postgres Extensions | pgvector | pgvector + AGE |
| hybrid_search params | 5 | 11 (+ 6 graph params) |
| Event Worker | extract only | extract + resolve + graph |
