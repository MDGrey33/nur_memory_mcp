# ADR-003: Hybrid Retrieval with RRF Merging

**Status:** Accepted
**Date:** 2025-12-25
**Author:** Senior Architect
**Relates to:** v2.0 Search Architecture

---

## Context

### Problem Statement

v2.0 introduces multiple collections with different semantic characteristics:

| Collection | Purpose | Size Profile | Search Frequency |
|------------|---------|--------------|------------------|
| `memory` | Durable facts, preferences | Small (100s) | High |
| `history` | Conversation turns | Medium (1000s) | Medium |
| `artifacts` | Unchunked documents | Medium (100s) | High |
| `artifact_chunks` | Document fragments | Large (10,000s+) | High |

**Challenges:**

1. **Multi-collection search**: User query may be relevant across collections
2. **Result merging**: How to combine results from different sources?
3. **Deduplication**: Artifact may appear in both `artifacts` and `artifact_chunks`
4. **Rank consistency**: Need consistent scoring across collections
5. **Query flexibility**: Sometimes want artifacts only, sometimes all collections

### Requirements

1. **Hybrid search tool**: Single API to search across multiple collections
2. **RRF merging**: Reciprocal Rank Fusion for combining ranked lists
3. **Deduplication**: One result per artifact (prefer chunks over full doc)
4. **Filtering**: Optional filters (artifact_type, sensitivity, time range)
5. **Neighbor expansion**: Option to include ±1 chunks for context
6. **Privacy filtering**: Hook for future privacy enforcement (v2: placeholder)

### Key Constraints

- **Query latency**: Target <500ms for hybrid search
- **Collection independence**: Each collection searched with same query embedding
- **Rank preservation**: RRF must respect original ranking quality
- **Backward compatibility**: Existing `memory_search` remains unchanged

---

## Decision

We will implement a **hybrid retrieval architecture** with:

1. **Parallel collection searches** using shared query embedding
2. **RRF (Reciprocal Rank Fusion)** for merging ranked results
3. **Artifact-based deduplication** preferring chunk hits over full docs
4. **Optional neighbor expansion** for chunk results
5. **Privacy filter hook** (placeholder in v2, enforced in v3)

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  hybrid_search Tool                                     │
└───────────────────┬─────────────────────────────────────┘
                    │ calls
                    ▼
┌─────────────────────────────────────────────────────────┐
│  RetrievalService                                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  1. Generate query embedding (EmbeddingService)  │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  2. Parallel searches (overfetch: limit * 3)    │  │
│  │     - artifacts collection                        │  │
│  │     - artifact_chunks collection                  │  │
│  │     - [optional] memory collection                │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  3. RRF merging (k=60)                           │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  4. Deduplication (artifact_id, prefer chunks)   │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  5. Privacy filtering (placeholder)              │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  6. [optional] Neighbor expansion                │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### RRF Algorithm

**Reciprocal Rank Fusion** is a proven method for combining ranked lists without requiring normalized scores:

```
For each document d:
  RRF_score(d) = Σ_collections (1 / (k + rank_in_collection))

Where:
  k = 60 (standard constant, balances top vs middle ranks)
  rank_in_collection = position in that collection's results (0-indexed)
```

**Example:**

Document "art_abc123" appears:
- Rank 2 in `artifacts` collection
- Rank 5 in `artifact_chunks` collection

RRF score = (1 / (60 + 2)) + (1 / (60 + 5))
         = (1 / 62) + (1 / 65)
         = 0.0161 + 0.0154
         = 0.0315

**Why RRF?**
- No score normalization needed (collections may use different distance metrics)
- Emphasizes top-ranked results (1/(60+0) = 0.0167, 1/(60+10) = 0.0143)
- Simple to implement and understand
- Well-studied in information retrieval literature

### Service Interface

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class SearchResult:
    """Single search result from a collection."""
    id: str                      # Record ID
    content: str                 # Document content
    metadata: dict               # Metadata
    collection: str              # Source collection
    rank: int                    # Position in collection results (0-indexed)
    distance: float              # Original distance/similarity score
    is_chunk: bool               # True if from artifact_chunks
    artifact_id: Optional[str]   # Parent artifact ID (if chunk)


@dataclass
class MergedResult:
    """Result after RRF merging."""
    result: SearchResult         # Original result
    rrf_score: float             # Computed RRF score
    collections: list[str]       # Collections where this appeared


class RetrievalService:
    """Hybrid retrieval with RRF merging."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chroma_client: chromadb.HttpClient,
        k: int = 60
    ):
        """
        Initialize retrieval service.

        Args:
            embedding_service: For generating query embeddings
            chroma_client: ChromaDB client
            k: RRF constant (standard: 60)
        """
        self.embedding_service = embedding_service
        self.chroma_client = chroma_client
        self.k = k
        self.logger = logging.getLogger("RetrievalService")

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        include_memory: bool = False,
        expand_neighbors: bool = False,
        filters: Optional[dict] = None
    ) -> list[MergedResult]:
        """
        Search across multiple collections with RRF merging.

        Args:
            query: Search query
            limit: Max results to return
            include_memory: Include memory collection
            expand_neighbors: Include ±1 chunks for chunk results
            filters: Optional metadata filters

        Returns:
            Ranked list of MergedResult
        """
        # 1. Generate query embedding
        query_embedding = self.embedding_service.generate_embedding(query)

        # 2. Parallel searches
        collections_to_search = ["artifacts", "artifact_chunks"]
        if include_memory:
            collections_to_search.append("memory")

        results_by_collection = {}
        for collection_name in collections_to_search:
            results = self._search_collection(
                collection_name=collection_name,
                query_embedding=query_embedding,
                filters=filters,
                limit=limit * 3  # Overfetch for RRF
            )
            results_by_collection[collection_name] = results

        # 3. RRF merging
        merged = self._merge_results_rrf(results_by_collection)

        # 4. Deduplication
        deduplicated = self._deduplicate_by_artifact(merged)

        # 5. Privacy filtering (placeholder in v2)
        filtered = self._apply_privacy_filter(deduplicated)

        # 6. Limit
        final_results = filtered[:limit]

        # 7. Neighbor expansion (if requested)
        if expand_neighbors:
            for result in final_results:
                if result.result.is_chunk:
                    result.result.content = self._expand_neighbors(result.result)

        return final_results

    def _search_collection(
        self,
        collection_name: str,
        query_embedding: list[float],
        filters: Optional[dict],
        limit: int
    ) -> list[SearchResult]:
        """Search single collection."""
        collection = self.chroma_client.get_or_create_collection(collection_name)

        # Build where clause
        where = {}
        if filters:
            if "artifact_type" in filters:
                where["artifact_type"] = filters["artifact_type"]
            if "sensitivity" in filters:
                where["sensitivity"] = filters["sensitivity"]
            # ... other filters

        # Query collection
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where if where else None
        )

        # Convert to SearchResult
        search_results = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for rank, (id, doc, meta, dist) in enumerate(
            zip(ids, documents, metadatas, distances)
        ):
            is_chunk = collection_name == "artifact_chunks"
            artifact_id = meta.get("artifact_id") if is_chunk else id

            search_results.append(SearchResult(
                id=id,
                content=doc,
                metadata=meta,
                collection=collection_name,
                rank=rank,
                distance=dist,
                is_chunk=is_chunk,
                artifact_id=artifact_id
            ))

        return search_results

    def _merge_results_rrf(
        self,
        results_by_collection: dict[str, list[SearchResult]]
    ) -> list[MergedResult]:
        """
        Merge results using RRF algorithm.

        Args:
            results_by_collection: {collection_name: [SearchResult, ...]}

        Returns:
            Sorted list of MergedResult by RRF score (descending)
        """
        merged_scores = {}

        for collection, results in results_by_collection.items():
            for result in results:
                result_id = result.id
                rrf_score = 1.0 / (self.k + result.rank)

                if result_id not in merged_scores:
                    merged_scores[result_id] = {
                        "score": 0.0,
                        "result": result,
                        "collections": []
                    }

                merged_scores[result_id]["score"] += rrf_score
                merged_scores[result_id]["collections"].append(collection)

        # Convert to MergedResult and sort
        merged_list = [
            MergedResult(
                result=item["result"],
                rrf_score=item["score"],
                collections=item["collections"]
            )
            for item in merged_scores.values()
        ]

        merged_list.sort(key=lambda x: x.rrf_score, reverse=True)

        self.logger.info(
            "rrf_merge_completed",
            extra={
                "collections_searched": list(results_by_collection.keys()),
                "results_before_merge": sum(len(r) for r in results_by_collection.values()),
                "results_after_merge": len(merged_list)
            }
        )

        return merged_list

    def _deduplicate_by_artifact(
        self,
        results: list[MergedResult]
    ) -> list[MergedResult]:
        """
        Deduplicate results by artifact_id.

        Rules:
        1. If same artifact appears multiple times, keep highest RRF score
        2. Prefer chunk over full artifact (chunks are more specific)

        Args:
            results: Merged results (sorted by RRF score)

        Returns:
            Deduplicated list
        """
        seen_artifacts = {}
        deduplicated = []

        for result in results:
            artifact_id = result.result.artifact_id or result.result.id

            if artifact_id not in seen_artifacts:
                # First time seeing this artifact
                seen_artifacts[artifact_id] = result
                deduplicated.append(result)
            else:
                # Already seen - check if current is better
                existing = seen_artifacts[artifact_id]

                # Prefer chunks over full artifacts (more specific)
                if result.result.is_chunk and not existing.result.is_chunk:
                    # Replace full artifact with chunk
                    deduplicated.remove(existing)
                    deduplicated.append(result)
                    seen_artifacts[artifact_id] = result
                elif (result.result.is_chunk and existing.result.is_chunk and
                      result.rrf_score > existing.rrf_score):
                    # Both chunks - keep higher score
                    deduplicated.remove(existing)
                    deduplicated.append(result)
                    seen_artifacts[artifact_id] = result
                # else: keep existing

        # Re-sort after deduplication
        deduplicated.sort(key=lambda x: x.rrf_score, reverse=True)

        self.logger.info(
            "deduplication_completed",
            extra={
                "results_before": len(results),
                "results_after": len(deduplicated),
                "duplicates_removed": len(results) - len(deduplicated)
            }
        )

        return deduplicated

    def _apply_privacy_filter(
        self,
        results: list[MergedResult]
    ) -> list[MergedResult]:
        """
        Apply privacy filtering (placeholder in v2).

        v2: Always returns all results (no filtering)
        v3: Will check sensitivity/visibility_scope

        Args:
            results: Results to filter

        Returns:
            Filtered results
        """
        # TODO v3: Implement privacy filtering
        # For now, return all results
        self.logger.debug("privacy_filter_placeholder_noop")
        return results

    def _expand_neighbors(self, result: SearchResult) -> str:
        """
        Expand chunk result to include ±1 neighbors.

        Args:
            result: Chunk search result

        Returns:
            Combined content with [CHUNK BOUNDARY] markers
        """
        if not result.is_chunk:
            return result.content

        artifact_id = result.metadata.get("artifact_id")
        chunk_index = result.metadata.get("chunk_index")

        # Fetch all chunks for artifact
        chunks_collection = self.chroma_client.get_or_create_collection("artifact_chunks")
        all_chunks_results = chunks_collection.get(
            where={"artifact_id": artifact_id}
        )

        # Sort by chunk_index
        chunks_data = list(zip(
            all_chunks_results["ids"],
            all_chunks_results["documents"],
            all_chunks_results["metadatas"]
        ))
        chunks_data.sort(key=lambda x: x[2].get("chunk_index", 0))

        # Find target and neighbors
        parts = []
        for i, (_, doc, meta) in enumerate(chunks_data):
            idx = meta.get("chunk_index")

            if idx == chunk_index - 1:
                # Previous chunk
                parts.append(doc)
                parts.append("[CHUNK BOUNDARY]")
            elif idx == chunk_index:
                # Target chunk
                parts.append(doc)
            elif idx == chunk_index + 1:
                # Next chunk
                parts.append("[CHUNK BOUNDARY]")
                parts.append(doc)

        return "\n".join(parts)
```

### Tool Integration

```python
@mcp.tool()
def hybrid_search(
    query: str,
    limit: int = 5,
    include_memory: bool = False,
    expand_neighbors: bool = False,
    filters: dict | None = None
) -> str:
    """
    Search across all collections with RRF merging.

    Args:
        query: Search query
        limit: Max results (1-50)
        include_memory: Include memory collection
        expand_neighbors: Include ±1 chunks for chunk results
        filters: Optional filters (artifact_type, sensitivity, etc.)

    Returns:
        Formatted search results with RRF scores
    """
    try:
        results = retrieval_service.hybrid_search(
            query=query,
            limit=limit,
            include_memory=include_memory,
            expand_neighbors=expand_neighbors,
            filters=filters
        )

        if not results:
            return "No results found."

        # Format output
        collections_searched = set()
        for result in results:
            collections_searched.update(result.collections)

        output = [
            f"Found {len(results)} results (searched: {', '.join(sorted(collections_searched))}):",
            ""
        ]

        for i, merged_result in enumerate(results, 1):
            result = merged_result.result
            meta = result.metadata

            output.append(f"[{i}] RRF score: {merged_result.rrf_score:.3f} "
                         f"(from: {', '.join(merged_result.collections)})")
            output.append(f"Type: {'chunk' if result.is_chunk else 'artifact'} | ID: {result.id}")

            if "title" in meta:
                output.append(f"Title: {meta['title']}")
            if "artifact_type" in meta:
                output.append(f"Source: {meta.get('source_system', '?')} | "
                            f"Sensitivity: {meta.get('sensitivity', 'normal')}")

            # Snippet
            snippet = result.content[:200] + "..." if len(result.content) > 200 else result.content
            output.append(f"Snippet: \"{snippet}\"")

            if "source_url" in meta:
                output.append(f"Evidence: {meta['source_url']}")

            output.append("")

        return "\n".join(output)

    except Exception as e:
        logger.error(f"hybrid_search error: {e}")
        return f"Search failed: {str(e)}"
```

---

## Consequences

### Positive

1. **Single API**: Users don't need to know which collection to search
2. **Better Recall**: Searches multiple sources, finds more relevant results
3. **Consistent Ranking**: RRF provides reliable cross-collection scoring
4. **Deduplication**: Prevents showing same artifact multiple times
5. **Context Expansion**: Neighbor chunks provide broader context
6. **Extensible**: Easy to add new collections (history, events, etc.)

### Negative

1. **Latency**: Multiple collection searches increase query time (3x vs single)
2. **Complexity**: More code than single-collection search
3. **Overfetching**: Need to fetch limit*3 from each collection for RRF
4. **Memory Overhead**: Merging large result sets requires memory
5. **Score Interpretation**: RRF scores less intuitive than cosine similarity

### Trade-offs

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **Single query to each collection** | Simple, parallel | Overfetches, merge complexity | Chosen |
| **Unified collection** | Single query, fast | Lose collection semantics, harder to filter | Rejected |
| **Sequential searches** | Simple merge | High latency, no parallelism | Rejected |
| **Learned ranking** | Optimal ranking | Requires training data, ML infrastructure | Future v3+ |

---

## Implementation Notes

### Configuration

```bash
RRF_CONSTANT=60
OVERFETCH_MULTIPLIER=3
MAX_HYBRID_SEARCH_RESULTS=50
```

### Parallel Search Optimization

For low latency, fetch collections in parallel:

```python
import asyncio

async def _search_collection_async(collection_name: str, ...) -> list[SearchResult]:
    # Async version of _search_collection
    pass

async def hybrid_search_async(self, query: str, ...) -> list[MergedResult]:
    # Generate query embedding (synchronous)
    query_embedding = self.embedding_service.generate_embedding(query)

    # Parallel searches
    collections = ["artifacts", "artifact_chunks"]
    if include_memory:
        collections.append("memory")

    tasks = [
        self._search_collection_async(col, query_embedding, filters, limit * 3)
        for col in collections
    ]

    search_results = await asyncio.gather(*tasks)

    results_by_collection = dict(zip(collections, search_results))

    # Continue with RRF merging...
    # ...
```

### Testing Strategy

1. **RRF Calculation Test**:
   - Mock results at known ranks
   - Verify RRF scores match formula

2. **Deduplication Test**:
   - Artifact in both `artifacts` and `artifact_chunks`
   - Verify chunk preferred over full artifact

3. **Multi-collection Test**:
   - Store same query-relevant content in multiple collections
   - Verify hybrid search finds all, merges correctly

4. **Neighbor Expansion Test**:
   - Store 6-chunk artifact
   - Search finds chunk 3
   - Verify expansion includes chunks 2, 3, 4

5. **Privacy Filter Test** (v2: no-op):
   - Verify all results returned
   - Add TODO for v3 enforcement

---

## Alternatives Considered

### Alternative 1: Cosine Similarity Score Normalization

**Description:** Normalize each collection's cosine similarity scores to [0, 1], then sum

**Pros:**
- Intuitive score interpretation
- No overfetching needed

**Cons:**
- ChromaDB uses L2 distance (not cosine), conversion complex
- Score distribution varies by collection
- Sensitive to outliers

**Decision:** Rejected - RRF is proven, distance-metric agnostic

### Alternative 2: Unified Collection

**Description:** Store all content in single collection with `type` metadata

**Pros:**
- Single query, fast
- No merging complexity

**Cons:**
- Lose semantic separation (memories vs artifacts)
- Harder to filter by collection type
- Cannot tune indexing per collection

**Decision:** Rejected - semantic separation is valuable

### Alternative 3: Sequential Search (Stop Early)

**Description:** Search collections sequentially, stop when enough results found

**Pros:**
- Lower latency if first collection sufficient
- Less overfetching

**Cons:**
- Unpredictable latency (depends on result distribution)
- Biases toward first collection searched
- Poor recall if results distributed across collections

**Decision:** Rejected - parallel is more consistent

### Alternative 4: Weighted RRF (Different k per Collection)

**Description:** Use different k values for different collections (e.g., k=60 for artifacts, k=100 for chunks)

**Pros:**
- Can bias toward certain collections
- More control over ranking

**Cons:**
- Complex to tune
- Risk of overfitting to current corpus
- Standard k=60 works well in practice

**Decision:** Rejected - keep it simple, standard k=60

---

## References

- Technical Specification: Section 2.3.2 (Hybrid Search Flow)
- Technical Specification: Section 5.3 (RetrievalService)
- [Reciprocal Rank Fusion Paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Elasticsearch RRF Implementation](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)

---

## Future Enhancements

### v3: Learned Ranking

Instead of RRF, train a ranking model:

```python
class LearnedRankingService:
    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        # Extract features: position, collection, distance, length, etc.
        features = self._extract_features(query, results)

        # Rank using trained model (LambdaMART, RankNet, etc.)
        scores = self.model.predict(features)

        # Re-sort by learned scores
        return sorted(zip(results, scores), key=lambda x: x[1], reverse=True)
```

Requires:
- Labeled training data (queries + relevance judgments)
- ML infrastructure (model training, serving)
- A/B testing framework

---

## Approval

**Approved by:** Senior Architect
**Date:** 2025-12-25
**Next ADR:** ADR-004 (Module Structure)
