"""
RRF-based hybrid retrieval service.

V3 features:
- Multi-collection search (artifacts, chunks, memory)
- RRF merging for rank fusion
- Neighbor expansion for chunk context

V4 features (added):
- Graph expansion for related context
- Entity resolution and linking
- New output shape with related_context and entities
"""

import logging
import os
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from uuid import UUID

from chromadb import HttpClient

from storage.models import SearchResult, MergedResult
from storage.collections import (
    get_memory_collection,
    get_artifacts_collection,
    get_artifact_chunks_collection,
    get_chunks_by_artifact,
    # V5 collections
    get_content_collection,
    get_chunks_collection,
    get_content_by_id,
    get_v5_chunks_by_content
)
from services.embedding_service import EmbeddingService
from services.chunking_service import ChunkingService
from utils.errors import RetrievalError


logger = logging.getLogger("mcp-memory.retrieval")

# Default distance cutoff for Chroma results (smaller is more similar).
# Set RETRIEVAL_MAX_DISTANCE to tune; if unset, we use a conservative default to
# reduce noisy / irrelevant chunk hits.
DEFAULT_MAX_DISTANCE = float(os.getenv("RETRIEVAL_MAX_DISTANCE", "0.35"))
# For chunk hits, require a minimum number of query "anchor tokens" to appear in
# the chunk content (reduces generic matches like "code quality" when querying for
# specific incidents). Set to 0 to disable.
CHUNK_MIN_ANCHOR_MATCHES = int(os.getenv("RETRIEVAL_CHUNK_MIN_ANCHOR_MATCHES", "1"))


# ============================================================================
# V4 Data Structures
# ============================================================================

@dataclass
class RelatedContextItem:
    """A related context item from graph expansion."""
    type: str  # "event" | "artifact"
    id: str
    category: Optional[str] = None
    reason: str = ""  # e.g., "same_actor:Alice Chen"
    summary: str = ""
    artifact_uid: Optional[str] = None
    revision_id: Optional[str] = None
    event_time: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "category": self.category,
            "reason": self.reason,
            "summary": self.summary,
            "evidence": self.evidence,
            "artifact_uid": self.artifact_uid,
            "revision_id": self.revision_id,
            "event_time": self.event_time
        }


@dataclass
class EntityInfo:
    """Entity information for V4 responses."""
    entity_id: str
    name: str
    type: str
    role: Optional[str] = None
    organization: Optional[str] = None
    mention_count: int = 1
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "type": self.type,
            "role": self.role,
            "organization": self.organization,
            "aliases": self.aliases,
            "mention_count": self.mention_count
        }


@dataclass
class V4SearchResult:
    """V4 search result with graph expansion."""
    primary_results: List[MergedResult]
    related_context: List[RelatedContextItem] = field(default_factory=list)
    entities: List[EntityInfo] = field(default_factory=list)
    expand_options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_results": [
                {
                    "id": r.result.id,
                    "content": r.result.content,
                    "metadata": r.result.metadata,
                    "collection": r.result.collection,
                    "rrf_score": r.rrf_score,
                    "artifact_uid": self._get_artifact_uid(r)
                }
                for r in self.primary_results
            ],
            "related_context": [rc.to_dict() for rc in self.related_context],
            "entities": [e.to_dict() for e in self.entities],
            "expand_options": self.expand_options
        }

    def _get_artifact_uid(self, result: MergedResult) -> Optional[str]:
        """Extract artifact_uid from result metadata or revision lookup."""
        # Try metadata first
        if result.result.metadata.get("artifact_uid"):
            return result.result.metadata["artifact_uid"]
        # Fallback to artifact_id
        return result.result.artifact_id


class RetrievalService:
    """RRF merging and hybrid retrieval service with V4 graph expansion."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunking_service: ChunkingService,
        chroma_client: HttpClient,
        k: int = 60,
        pg_client=None,
        graph_service=None
    ):
        """
        Initialize retrieval service.

        Args:
            embedding_service: Embedding service for query embeddings
            chunking_service: Chunking service for neighbor expansion
            chroma_client: ChromaDB client
            k: RRF constant (standard value: 60)
            pg_client: Postgres client for V4 features (optional)
            graph_service: GraphService for V4 graph expansion (optional)
        """
        self.embedding_service = embedding_service
        self.chunking_service = chunking_service
        self.chroma_client = chroma_client
        self.k = k

        # V4 services
        self.pg_client = pg_client
        self.graph_service = graph_service

    def merge_results_rrf(
        self,
        results_by_collection: Dict[str, List[SearchResult]],
        limit: int
    ) -> List[MergedResult]:
        """
        Merge multi-collection results using Reciprocal Rank Fusion.

        Args:
            results_by_collection: Search results keyed by collection name
            limit: Maximum results to return

        Returns:
            List of merged results sorted by RRF score
        """
        merged_scores: Dict[str, Dict] = {}

        # Calculate RRF scores
        for collection, results in results_by_collection.items():
            for rank, result in enumerate(results):
                result_id = result.id
                rrf_score = 1.0 / (self.k + rank + 1)

                if result_id not in merged_scores:
                    merged_scores[result_id] = {
                        "score": 0,
                        "result": result,
                        "collections": []
                    }

                merged_scores[result_id]["score"] += rrf_score
                merged_scores[result_id]["collections"].append(collection)

        # Sort by aggregated RRF score
        ranked = sorted(
            merged_scores.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        # Convert to MergedResult objects
        merged_results = [
            MergedResult(
                result=item["result"],
                rrf_score=item["score"],
                collections=item["collections"]
            )
            for item in ranked[:limit]
        ]

        return merged_results

    def deduplicate_by_artifact(
        self,
        results: List[MergedResult]
    ) -> List[MergedResult]:
        """
        Deduplicate results by artifact_id, preferring chunk hits over artifact hits.

        Args:
            results: List of merged results

        Returns:
            Deduplicated list of results
        """
        seen_artifacts: Dict[str, MergedResult] = {}
        deduplicated = []

        for result in results:
            artifact_id = result.result.artifact_id or result.result.id

            # Extract artifact_id from chunk ID if needed
            if "::" in artifact_id:
                artifact_id = artifact_id.split("::")[0]

            if artifact_id not in seen_artifacts:
                # First time seeing this artifact
                seen_artifacts[artifact_id] = result
                deduplicated.append(result)
            else:
                # Already seen - prefer chunk over full artifact
                existing = seen_artifacts[artifact_id]

                if result.result.is_chunk and not existing.result.is_chunk:
                    # Replace full artifact with chunk
                    deduplicated.remove(existing)
                    deduplicated.append(result)
                    seen_artifacts[artifact_id] = result
                elif result.result.is_chunk and existing.result.is_chunk:
                    # Both are chunks - keep higher RRF score
                    if result.rrf_score > existing.rrf_score:
                        deduplicated.remove(existing)
                        deduplicated.append(result)
                        seen_artifacts[artifact_id] = result

        return deduplicated

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        include_memory: bool = False,
        expand_neighbors: bool = False,
        filters: Optional[Dict] = None
    ) -> List[MergedResult]:
        """
        Search across multiple collections with RRF merging.

        Args:
            query: Search query text
            limit: Maximum results to return
            include_memory: Include memory collection in search
            expand_neighbors: Include ±1 chunks for context
            filters: Optional metadata filters

        Returns:
            List of merged and deduplicated results

        Raises:
            RetrievalError: If search fails
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding_service.generate_embedding(query)

            # Determine collections to search
            collections_to_search = ["artifacts", "artifact_chunks"]
            if include_memory:
                collections_to_search.append("memory")

            # Parallel searches
            results_by_collection: Dict[str, List[SearchResult]] = {}

            for collection_name in collections_to_search:
                results = self._search_collection(
                    collection_name=collection_name,
                    query_embedding=query_embedding,
                    limit=limit * 3,  # Overfetch for RRF
                    filters=filters
                )
                results_by_collection[collection_name] = results

            # Quality: drop very weak semantic matches before RRF so noisy chunks
            # don't win by rank-fusion alone.
            raw_total = sum(len(v) for v in results_by_collection.values())
            if DEFAULT_MAX_DISTANCE is not None and raw_total > 0:
                filtered_by_collection: Dict[str, List[SearchResult]] = {}
                for cname, results in results_by_collection.items():
                    filtered_by_collection[cname] = [
                        r for r in results
                        if r.distance is None or r.distance <= DEFAULT_MAX_DISTANCE
                    ]

                filtered_total = sum(len(v) for v in filtered_by_collection.values())
                if filtered_total > 0:
                    results_by_collection = filtered_by_collection

            # Apply RRF merging
            merged_results = self.merge_results_rrf(results_by_collection, limit * 2)

            # Deduplicate by artifact_id
            deduplicated = self.deduplicate_by_artifact(merged_results)

            def _extract_anchor_tokens(q: str) -> List[str]:
                import re
                tokens = re.findall(r"[a-z0-9]+", (q or "").lower())
                stop = {
                    "the","a","an","and","or","of","to","in","on","for","by","with","at","from",
                    "is","are","was","were","be","been","it","this","that","as"
                }
                anchors = []
                for t in tokens:
                    if t in stop:
                        continue
                    if t.isdigit() or len(t) >= 4:
                        anchors.append(t)
                # keep unique in order
                seen=set(); out=[]
                for t in anchors:
                    if t not in seen:
                        out.append(t); seen.add(t)
                return out

            def _chunk_anchor_match_count(anchors: List[str], content: str) -> int:
                if not anchors or not content:
                    return 0
                lc = content.lower()
                return sum(1 for t in anchors if t in lc)

            anchors = _extract_anchor_tokens(query)

            # Limit to requested count, but skip low-quality chunks when the query is specific.
            final_results: List[MergedResult] = []
            for r in deduplicated:
                if len(final_results) >= limit:
                    break

                if (
                    CHUNK_MIN_ANCHOR_MATCHES > 0
                    and r.result.is_chunk
                    and len(anchors) >= 3  # only apply for sufficiently specific queries
                ):
                    if _chunk_anchor_match_count(anchors, r.result.content) < CHUNK_MIN_ANCHOR_MATCHES:
                        continue

                final_results.append(r)

            # Expand neighbors if requested
            if expand_neighbors:
                self._expand_neighbors(final_results)

            logger.info(
                f"Hybrid search completed: query_length={len(query)}, "
                f"collections={collections_to_search}, results={len(final_results)}"
            )

            return final_results

        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            raise RetrievalError(f"Failed to perform hybrid search: {e}")

    def _search_collection(
        self,
        collection_name: str,
        query_embedding: List[float],
        limit: int,
        filters: Optional[Dict] = None
    ) -> List[SearchResult]:
        """
        Search a single collection.

        Args:
            collection_name: Name of collection to search
            query_embedding: Query embedding vector
            limit: Maximum results
            filters: Optional metadata filters

        Returns:
            List of search results
        """
        # Get collection
        if collection_name == "memory":
            collection = get_memory_collection(self.chroma_client)
        elif collection_name == "artifacts":
            collection = get_artifacts_collection(self.chroma_client)
        elif collection_name == "artifact_chunks":
            collection = get_artifact_chunks_collection(self.chroma_client)
        else:
            return []

        # Build query parameters
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": limit
        }

        if filters:
            query_params["where"] = filters

        # Execute search
        try:
            results = collection.query(**query_params)

            # Parse results
            search_results = []
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for rank, (id, doc, metadata, distance) in enumerate(
                zip(ids, documents, metadatas, distances)
            ):
                is_chunk = "::" in id
                artifact_id = id.split("::")[0] if is_chunk else None

                search_results.append(SearchResult(
                    id=id,
                    content=doc,
                    metadata=metadata or {},
                    collection=collection_name,
                    rank=rank,
                    distance=distance,
                    is_chunk=is_chunk,
                    artifact_id=artifact_id
                ))

            return search_results

        except Exception as e:
            logger.error(f"Failed to search collection {collection_name}: {e}")
            return []

    def _expand_neighbors(self, results: List[MergedResult]):
        """
        Expand chunk results to include ±1 neighbors.

        Args:
            results: List of merged results to expand (modified in place)
        """
        for result in results:
            if not result.result.is_chunk:
                continue

            # Get artifact_id and chunk_index
            artifact_id = result.result.artifact_id
            chunk_index = result.result.metadata.get("chunk_index")

            if artifact_id is None or chunk_index is None:
                continue

            # Fetch all chunks for artifact
            try:
                chunks_data = get_chunks_by_artifact(
                    self.chroma_client,
                    artifact_id
                )

                if not chunks_data:
                    continue

                # Convert to Chunk objects
                from storage.models import Chunk
                chunks = [
                    Chunk(
                        chunk_id=c["chunk_id"],
                        artifact_id=c["metadata"]["artifact_id"],
                        chunk_index=c["metadata"]["chunk_index"],
                        content=c["content"],
                        start_char=c["metadata"]["start_char"],
                        end_char=c["metadata"]["end_char"],
                        token_count=c["metadata"]["token_count"],
                        content_hash=c["metadata"]["content_hash"]
                    )
                    for c in chunks_data
                ]

                # Expand with neighbors
                expanded_content = self.chunking_service.expand_chunk_neighbors(
                    artifact_id=artifact_id,
                    chunk_index=chunk_index,
                    all_chunks=chunks
                )

                # Update result content
                result.result.content = expanded_content

            except Exception as e:
                logger.error(
                    f"Failed to expand neighbors for {artifact_id}: {e}"
                )

    # =========================================================================
    # V4: Graph Expansion Methods
    # =========================================================================

    async def hybrid_search_v4(
        self,
        query: str,
        limit: int = 5,
        include_memory: bool = False,
        expand_neighbors: bool = False,
        filters: Optional[Dict] = None,
        # V4 parameters
        graph_expand: bool = False,
        graph_depth: int = 1,
        graph_budget: int = 10,
        graph_seed_limit: int = 5,
        graph_filters: Optional[Dict] = None,
        include_entities: bool = False,
        # Optional: when provided, seed graph expansion from these Postgres event IDs
        # (higher precision for queries that match semantic_event directly).
        seed_event_ids: Optional[List[UUID]] = None
    ) -> V4SearchResult:
        """
        V4 hybrid search with optional graph expansion.

        When graph_expand=false, returns V3-compatible shape.
        When graph_expand=true, performs graph expansion from seed results.

        Args:
            query: Search query text
            limit: Maximum primary results to return
            include_memory: Include memory collection in search
            expand_neighbors: Include ±1 chunks for context (V3)
            filters: Optional metadata filters

            # V4 parameters
            graph_expand: Enable graph expansion from results
            graph_depth: Graph traversal depth (1-2)
            graph_budget: Maximum related context items
            graph_seed_limit: Maximum seed results for graph expansion
            graph_filters: Category filters for graph expansion
            include_entities: Include entity information in response

        Returns:
            V4SearchResult with primary_results, related_context, entities

        Raises:
            RetrievalError: If search fails
        """
        try:
            # Perform standard hybrid search
            primary_results = self.hybrid_search(
                query=query,
                limit=limit,
                include_memory=include_memory,
                expand_neighbors=expand_neighbors,
                filters=filters
            )

            # V3 fallback: just return primary results
            if not graph_expand or not self.graph_service:
                return V4SearchResult(
                    primary_results=primary_results,
                    related_context=[],
                    entities=[],
                    expand_options={
                        "graph_expand": False,
                        "reason": "graph_expand=false or graph_service unavailable"
                    }
                )

            # V4: Perform graph expansion
            related_context, entities = await self._perform_graph_expansion(
                primary_results=primary_results[:graph_seed_limit],
                depth=graph_depth,
                budget=graph_budget,
                category_filter=graph_filters.get("categories") if graph_filters else None,
                include_entities=include_entities,
                seed_event_ids=seed_event_ids[:graph_seed_limit] if seed_event_ids else None
            )

            return V4SearchResult(
                primary_results=primary_results,
                related_context=related_context,
                entities=entities,
                expand_options={
                    "graph_expand": True,
                    "graph_depth": graph_depth,
                    "graph_budget": graph_budget,
                    "graph_seed_limit": graph_seed_limit,
                    "seeds_used": len(primary_results[:graph_seed_limit])
                }
            )

        except Exception as e:
            logger.error(f"V4 hybrid search failed: {e}")
            raise RetrievalError(f"Failed to perform V4 hybrid search: {e}")

    async def _perform_graph_expansion(
        self,
        primary_results: List[MergedResult],
        depth: int = 1,
        budget: int = 10,
        category_filter: Optional[List[str]] = None,
        include_entities: bool = False,
        seed_event_ids: Optional[List[UUID]] = None
    ) -> Tuple[List[RelatedContextItem], List[EntityInfo]]:
        """
        Perform graph expansion from primary results.

        Algorithm:
        1. Get artifact_uid for each primary result
        2. Find events in those artifacts
        3. Use graph service to expand from those events
        4. Return related events as RelatedContextItem

        Args:
            primary_results: Seed results for expansion
            depth: Expansion depth (1-2 hops)
            budget: Maximum related items
            category_filter: Event categories to include
            include_entities: Whether to include entity information

        Returns:
            Tuple of (related_context, entities)
        """
        # V5: Only requires pg_client, not graph_service (uses SQL joins)
        if not self.pg_client:
            return [], []

        try:
            # Step 1: Get seed event IDs either from explicit seeds (preferred) or
            # from mapping primary results to events.
            if seed_event_ids is None:
                seed_event_ids = await self._get_seed_events(primary_results)

            if not seed_event_ids:
                logger.info("No seed events found for graph expansion")
                return [], []

            # Step 2: Perform graph expansion via SQL joins (V5 - no AGE required)
            related_events = await self._expand_from_events_sql(
                seed_event_ids=seed_event_ids,
                budget=budget,
                category_filter=category_filter
            )

            # Events are already deduplicated in the SQL query
            related_event_ids = [UUID(event["event_id"]) if isinstance(event["event_id"], str) else event["event_id"]
                                 for event in related_events]
            evidence_map = await self._fetch_evidence_for_events(related_event_ids)

            # Step 3: Convert to RelatedContextItem (with evidence)
            related_context = []
            for event in related_events:
                event_id = UUID(event["event_id"]) if isinstance(event["event_id"], str) else event["event_id"]
                related_context.append(RelatedContextItem(
                    type="event",
                    id=str(event_id),
                    category=event["category"],
                    reason=event["reason"],
                    summary=event["narrative"],
                    artifact_uid=event["artifact_uid"],
                    revision_id=event["revision_id"],
                    event_time=str(event["event_time"]) if event["event_time"] else None,
                    evidence=evidence_map.get(event_id, [])
                ))

            # Step 4: Get entities if requested (from Postgres, includes aliases + mention counts)
            entities = []
            if include_entities:
                # Get entities from both seed and related events
                all_event_ids = (seed_event_ids + related_event_ids)[:50]
                entities = await self._fetch_entities_for_events(all_event_ids)

            logger.info(
                f"Graph expansion: {len(seed_event_ids)} seeds -> "
                f"{len(related_context)} related, {len(entities)} entities"
            )

            return related_context, entities

        except Exception as e:
            logger.error(f"Graph expansion failed: {e}")
            return [], []

    # =========================================================================
    # V5: Simplified Search over V5 Collections
    # =========================================================================

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
    ) -> V4SearchResult:
        """
        V5 hybrid search over content and chunks collections.

        Searches the unified V5 content collection and optionally
        performs graph expansion via Postgres SQL joins.

        Args:
            query: Search query text
            limit: Maximum results
            expand: Enable graph expansion
            graph_budget: Max related items from graph
            graph_filters: Category filters for graph expansion
            include_entities: Include entity info
            context_filter: Filter by context type (meeting, email, note, etc.)
            min_importance: Filter by minimum importance

        Returns:
            V4SearchResult with primary_results, related_context, entities
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding_service.generate_embedding(query)

            # Search both V5 collections: content (small docs) and chunks (large docs)
            content_col = get_content_collection(self.chroma_client)
            chunks_col = get_chunks_collection(self.chroma_client)

            # Build where filter for content collection
            where_filter = {}
            if context_filter:
                where_filter["context"] = context_filter

            # Fetch from both collections and merge by distance
            fetch_limit = limit * 2 if min_importance else limit

            # Search content collection (small/unchunked documents)
            content_results = content_col.query(
                query_embeddings=[query_embedding],
                n_results=fetch_limit,
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"]
            )

            # Search chunks collection (chunks of large documents)
            # No context filter on chunks - they inherit from parent content
            chunk_results = chunks_col.query(
                query_embeddings=[query_embedding],
                n_results=fetch_limit,
                include=["documents", "metadatas", "distances"]
            )

            # Merge results from both collections by distance (lower = better)
            merged_candidates = []

            # Add content results
            content_ids = content_results.get("ids", [[]])[0]
            content_docs = content_results.get("documents", [[]])[0]
            content_metas = content_results.get("metadatas", [[]])[0]
            content_dists = content_results.get("distances", [[]])[0]

            for id, doc, metadata, distance in zip(
                content_ids, content_docs, content_metas, content_dists
            ):
                merged_candidates.append({
                    "id": id,
                    "doc": doc,
                    "metadata": metadata or {},
                    "distance": distance,
                    "collection": "content",
                    "is_chunk": False,
                    "artifact_id": id
                })

            # Add chunk results
            chunk_ids = chunk_results.get("ids", [[]])[0]
            chunk_docs = chunk_results.get("documents", [[]])[0]
            chunk_metas = chunk_results.get("metadatas", [[]])[0]
            chunk_dists = chunk_results.get("distances", [[]])[0]

            for id, doc, metadata, distance in zip(
                chunk_ids, chunk_docs, chunk_metas, chunk_dists
            ):
                # Extract parent content_id from chunk metadata
                content_id = (metadata or {}).get("content_id", id.split("::")[0])
                merged_candidates.append({
                    "id": id,
                    "doc": doc,
                    "metadata": metadata or {},
                    "distance": distance,
                    "collection": "chunks",
                    "is_chunk": True,
                    "artifact_id": content_id
                })

            # Sort by distance (ascending - lower is better)
            merged_candidates.sort(key=lambda x: x["distance"])

            # Deduplicate by artifact_id (keep best match per document)
            seen_artifacts = set()
            primary_results = []

            for rank, candidate in enumerate(merged_candidates):
                # Skip if we've already included this document
                artifact_id = candidate["artifact_id"]
                if artifact_id in seen_artifacts:
                    continue

                # Filter by importance if specified
                if min_importance is not None:
                    doc_importance = candidate["metadata"].get("importance", 0.5)
                    if doc_importance < min_importance:
                        continue

                seen_artifacts.add(artifact_id)

                primary_results.append(MergedResult(
                    result=SearchResult(
                        id=candidate["id"],
                        content=candidate["doc"],
                        metadata=candidate["metadata"],
                        collection=candidate["collection"],
                        rank=rank,
                        distance=candidate["distance"],
                        is_chunk=candidate["is_chunk"],
                        artifact_id=artifact_id
                    ),
                    rrf_score=1.0 / (rank + 1),
                    collections=[candidate["collection"]]
                ))

                if len(primary_results) >= limit:
                    break

            # Graph expansion if enabled
            related_context = []
            entities = []

            if expand and primary_results and self.pg_client:
                # Get seed event IDs from primary results
                seed_event_ids = await self._get_seed_events(primary_results[:1])

                if seed_event_ids:
                    category_filter = graph_filters.get("categories") if graph_filters else None
                    related_context, entities = await self._perform_graph_expansion(
                        primary_results=primary_results[:1],
                        depth=1,
                        budget=graph_budget,
                        category_filter=category_filter,
                        include_entities=include_entities,
                        seed_event_ids=seed_event_ids
                    )

            return V4SearchResult(
                primary_results=primary_results,
                related_context=related_context,
                entities=entities,
                expand_options={
                    "graph_expand": expand,
                    "v5_mode": True,
                    "collections": ["content", "chunks"]
                }
            )

        except Exception as e:
            logger.error(f"V5 hybrid search failed: {e}")
            raise RetrievalError(f"Failed to perform V5 hybrid search: {e}")

    async def _fetch_evidence_for_events(
        self,
        event_ids: List[UUID]
    ) -> Dict[UUID, List[Dict[str, Any]]]:
        """
        Fetch evidence quotes for the given events.

        Returns:
            Map of event_id -> list[{quote, artifact_uid, start_char, end_char, chunk_id}]
        """
        if not self.pg_client or not event_ids:
            return {}

        placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
        sql = f"""
        SELECT event_id, quote, artifact_uid, start_char, end_char, chunk_id
        FROM event_evidence
        WHERE event_id IN ({placeholders})
        ORDER BY event_id, start_char
        """

        rows = await self.pg_client.fetch_all(sql, *event_ids)
        out: Dict[UUID, List[Dict[str, Any]]] = {}
        for row in rows:
            eid = row["event_id"]
            out.setdefault(eid, []).append({
                "quote": row["quote"],
                "artifact_uid": row.get("artifact_uid"),
                "start_char": row.get("start_char"),
                "end_char": row.get("end_char"),
                "chunk_id": row.get("chunk_id")
            })
        return out

    async def _fetch_entities_for_events(
        self,
        event_ids: List[UUID]
    ) -> List[EntityInfo]:
        """
        Fetch entities involved in the given events, enriched with aliases and mention counts.
        """
        if not self.pg_client or not event_ids:
            return []

        placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
        sql = f"""
        WITH evs AS (
          SELECT event_id, artifact_uid, revision_id
          FROM semantic_event
          WHERE event_id IN ({placeholders})
        ),
        rel_entities AS (
          SELECT ea.entity_id, evs.artifact_uid, evs.revision_id
          FROM evs
          JOIN event_actor ea ON ea.event_id = evs.event_id
          UNION ALL
          SELECT es.entity_id, evs.artifact_uid, evs.revision_id
          FROM evs
          JOIN event_subject es ON es.event_id = evs.event_id
        ),
        mention_counts AS (
          SELECT re.entity_id, COUNT(*)::int AS mention_count
          FROM rel_entities re
          JOIN entity_mention em
            ON em.entity_id = re.entity_id
           AND em.artifact_uid = re.artifact_uid
           AND em.revision_id = re.revision_id
          GROUP BY re.entity_id
        ),
        base AS (
          SELECT DISTINCT re.entity_id
          FROM rel_entities re
        )
        SELECT e.entity_id,
               e.canonical_name,
               e.entity_type,
               e.role,
               e.organization,
               COALESCE(mc.mention_count, 0) AS mention_count,
               COALESCE(array_agg(DISTINCT ea.alias) FILTER (WHERE ea.alias IS NOT NULL), ARRAY[]::text[]) AS aliases
        FROM base b
        JOIN entity e ON e.entity_id = b.entity_id
        LEFT JOIN mention_counts mc ON mc.entity_id = b.entity_id
        LEFT JOIN entity_alias ea ON ea.entity_id = b.entity_id
        GROUP BY e.entity_id, e.canonical_name, e.entity_type, e.role, e.organization, mc.mention_count
        ORDER BY COALESCE(mc.mention_count, 0) DESC, e.canonical_name ASC
        """

        rows = await self.pg_client.fetch_all(sql, *event_ids)
        entities: List[EntityInfo] = []
        for row in rows:
            entities.append(EntityInfo(
                entity_id=str(row["entity_id"]),
                name=row["canonical_name"],
                type=row["entity_type"],
                role=row.get("role"),
                organization=row.get("organization"),
                mention_count=int(row.get("mention_count") or 0),
                aliases=list(row.get("aliases") or [])
            ))
        return entities

    async def _expand_from_events_sql(
        self,
        seed_event_ids: List[UUID],
        budget: int = 10,
        category_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Find related events via shared actors/subjects using pure SQL joins.

        V5 replacement for AGE-based graph expansion.

        Args:
            seed_event_ids: Event IDs to expand from
            budget: Maximum related events to return
            category_filter: Event categories to include (e.g., ["Decision", "Commitment"])

        Returns:
            List of related event dicts with reason for connection
        """
        if not self.pg_client or not seed_event_ids:
            return []

        # Build placeholders for seed event IDs
        seed_placeholders = ", ".join(f"${i+1}" for i in range(len(seed_event_ids)))

        # Base query to find connected events via shared entities
        # Use category filter if provided
        if category_filter:
            cat_placeholders = ", ".join(f"${len(seed_event_ids)+i+1}" for i in range(len(category_filter)))
            category_clause = f"AND se.category IN ({cat_placeholders})"
            params = list(seed_event_ids) + category_filter
        else:
            category_clause = ""
            params = list(seed_event_ids)

        sql = f"""
        WITH seed_entities AS (
            -- Get entities (actors and subjects) from seed events
            SELECT DISTINCT entity_id, 'actor' AS role
            FROM event_actor
            WHERE event_id IN ({seed_placeholders})
            UNION
            SELECT DISTINCT entity_id, 'subject' AS role
            FROM event_subject
            WHERE event_id IN ({seed_placeholders})
        ),
        connected_events AS (
            -- Find events that share these entities (excluding seeds)
            SELECT DISTINCT
                se.event_id,
                se.artifact_uid,
                se.revision_id,
                se.category,
                se.narrative,
                se.event_time,
                se.confidence,
                e.canonical_name AS connecting_entity,
                CASE
                    WHEN ea.event_id IS NOT NULL THEN 'same_actor'
                    WHEN es.event_id IS NOT NULL THEN 'same_subject'
                END AS connection_type
            FROM semantic_event se
            JOIN seed_entities s ON 1=1
            LEFT JOIN event_actor ea ON ea.event_id = se.event_id AND ea.entity_id = s.entity_id
            LEFT JOIN event_subject es ON es.event_id = se.event_id AND es.entity_id = s.entity_id
            JOIN entity e ON e.entity_id = s.entity_id
            WHERE (ea.event_id IS NOT NULL OR es.event_id IS NOT NULL)
              AND se.event_id NOT IN ({seed_placeholders})
              {category_clause}
        ),
        ranked AS (
            -- Deduplicate and rank by connection type (actor > subject)
            SELECT DISTINCT ON (event_id)
                event_id,
                artifact_uid,
                revision_id,
                category,
                narrative,
                event_time,
                confidence,
                connecting_entity,
                connection_type
            FROM connected_events
            ORDER BY event_id, connection_type DESC  -- actor first
        )
        SELECT * FROM ranked
        LIMIT {budget}
        """

        try:
            rows = await self.pg_client.fetch_all(sql, *params)
            return [
                {
                    "event_id": row["event_id"],
                    "artifact_uid": row["artifact_uid"],
                    "revision_id": row["revision_id"],
                    "category": row["category"],
                    "narrative": row["narrative"],
                    "event_time": row["event_time"],
                    "confidence": row["confidence"],
                    "reason": f"{row['connection_type']}:{row['connecting_entity']}"
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"SQL graph expansion failed: {e}")
            return []

    async def _get_seed_events(
        self,
        results: List[MergedResult]
    ) -> List[UUID]:
        """
        Get event IDs from search results for graph seeding.

        Maps chunk/artifact IDs to events via artifact_revision.

        Args:
            results: Primary search results

        Returns:
            List of event UUIDs
        """
        if not self.pg_client:
            return []

        seed_events = []

        for result in results:
            try:
                # Get artifact_id from result
                artifact_id = result.result.artifact_id or result.result.id
                if "::" in artifact_id:
                    artifact_id = artifact_id.split("::")[0]

                # Look up artifact_uid from artifact_revision
                revision = await self.pg_client.fetch_one(
                    """
                    SELECT artifact_uid, revision_id
                    FROM artifact_revision
                    WHERE artifact_id = $1 AND is_latest = true
                    LIMIT 1
                    """,
                    artifact_id
                )

                if not revision:
                    continue

                artifact_uid = revision["artifact_uid"]
                revision_id = revision["revision_id"]

                # Get events for this artifact revision
                events = await self.pg_client.fetch_all(
                    """
                    SELECT event_id FROM semantic_event
                    WHERE artifact_uid = $1 AND revision_id = $2
                    LIMIT 10
                    """,
                    artifact_uid,
                    revision_id
                )

                for event in events:
                    seed_events.append(event["event_id"])

            except Exception as e:
                logger.warning(f"Failed to get seed events for result: {e}")
                continue

        # Deduplicate
        return list(set(seed_events))

    async def get_artifact_uid_for_chunk(
        self,
        chunk_id: str
    ) -> Optional[str]:
        """
        Look up artifact_uid for a chunk ID.

        Args:
            chunk_id: Chunk ID (format: artifact_id::index)

        Returns:
            artifact_uid or None
        """
        if not self.pg_client:
            return None

        artifact_id = chunk_id.split("::")[0] if "::" in chunk_id else chunk_id

        try:
            revision = await self.pg_client.fetch_one(
                """
                SELECT artifact_uid FROM artifact_revision
                WHERE artifact_id = $1 AND is_latest = true
                LIMIT 1
                """,
                artifact_id
            )

            return revision["artifact_uid"] if revision else None

        except Exception as e:
            logger.error(f"Failed to get artifact_uid for {chunk_id}: {e}")
            return None
