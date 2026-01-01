"""
V6 Retrieval Service - Hybrid search with graph expansion.

Features:
- Unified content/chunks collection search
- RRF merging for rank fusion
- Graph expansion via SQL joins (no AGE dependency)
- Entity resolution and linking
"""

import logging
import os
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from uuid import UUID

from chromadb import HttpClient

from storage.models import SearchResult, MergedResult
from storage.collections import (
    get_content_collection,
    get_chunks_collection,
    get_content_by_id,
    get_v5_chunks_by_content
)
from services.embedding_service import EmbeddingService
from services.chunking_service import ChunkingService
from utils.errors import RetrievalError


logger = logging.getLogger("mcp-memory.retrieval")


# ============================================================================
# V6 Data Structures
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
    """V6 search result with graph expansion."""
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
    """V6 retrieval service with RRF merging and SQL-based graph expansion."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunking_service: ChunkingService,
        chroma_client: HttpClient,
        k: int = 60,
        pg_client=None
    ):
        """
        Initialize retrieval service.

        Args:
            embedding_service: Embedding service for query embeddings
            chunking_service: Chunking service for neighbor expansion
            chroma_client: ChromaDB client
            k: RRF constant (standard value: 60)
            pg_client: Postgres client for graph expansion via SQL joins
        """
        self.embedding_service = embedding_service
        self.chunking_service = chunking_service
        self.chroma_client = chroma_client
        self.k = k
        self.pg_client = pg_client

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

    # =========================================================================
    # V6: Graph Expansion Methods
    # =========================================================================

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
        # V6: Only requires pg_client (uses SQL joins, no AGE/graph_service)
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
    # V6: Unified Search over Content/Chunks Collections
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
        V6 hybrid search over content and chunks collections.

        Searches the unified content collection and optionally
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

            # Search both V6 collections: content (small docs) and chunks (large docs)
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

        V6 graph expansion via SQL (no AGE dependency).

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
