"""RRF-based hybrid retrieval service."""

import logging
from typing import List, Dict, Optional

from chromadb import HttpClient

from storage.models import SearchResult, MergedResult
from storage.collections import (
    get_memory_collection,
    get_artifacts_collection,
    get_artifact_chunks_collection,
    get_chunks_by_artifact
)
from services.embedding_service import EmbeddingService
from services.chunking_service import ChunkingService
from utils.errors import RetrievalError


logger = logging.getLogger("mcp-memory.retrieval")


class RetrievalService:
    """RRF merging and hybrid retrieval service."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunking_service: ChunkingService,
        chroma_client: HttpClient,
        k: int = 60
    ):
        """
        Initialize retrieval service.

        Args:
            embedding_service: Embedding service for query embeddings
            chunking_service: Chunking service for neighbor expansion
            chroma_client: ChromaDB client
            k: RRF constant (standard value: 60)
        """
        self.embedding_service = embedding_service
        self.chunking_service = chunking_service
        self.chroma_client = chroma_client
        self.k = k

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

            # Apply RRF merging
            merged_results = self.merge_results_rrf(results_by_collection, limit * 2)

            # Deduplicate by artifact_id
            deduplicated = self.deduplicate_by_artifact(merged_results)

            # Limit to requested count
            final_results = deduplicated[:limit]

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
