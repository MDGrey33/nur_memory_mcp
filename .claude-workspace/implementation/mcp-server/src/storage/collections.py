"""ChromaDB collection management and schemas."""

import logging
from typing import Optional, List, Dict, Any
from chromadb import HttpClient, Collection
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction


logger = logging.getLogger("mcp-memory.storage")


# We manage our own embeddings via OpenAI - tell ChromaDB not to use its default
# By setting embedding_function to a dummy that won't be called (we always pass embeddings)
class NoOpEmbeddingFunction:
    """Dummy embedding function - we always provide our own embeddings."""
    def __call__(self, input):
        # This should never be called since we always pass embeddings
        raise RuntimeError("Embeddings must be provided explicitly")


def get_memory_collection(client: HttpClient) -> Collection:
    """
    Get or create the memory collection.

    Args:
        client: ChromaDB client

    Returns:
        Memory collection instance
    """
    return client.get_or_create_collection(
        name="memory",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "description": "Durable semantic memories (preferences, facts, decisions, projects)",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_history_collection(client: HttpClient) -> Collection:
    """
    Get or create the history collection.

    Args:
        client: ChromaDB client

    Returns:
        History collection instance
    """
    return client.get_or_create_collection(
        name="history",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "description": "Conversation history keyed by conversation_id",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_artifacts_collection(client: HttpClient) -> Collection:
    """
    Get or create the artifacts collection.

    Args:
        client: ChromaDB client

    Returns:
        Artifacts collection instance
    """
    return client.get_or_create_collection(
        name="artifacts",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "description": "Full artifact storage or metadata for chunked documents",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_artifact_chunks_collection(client: HttpClient) -> Collection:
    """
    Get or create the artifact_chunks collection.

    Args:
        client: ChromaDB client

    Returns:
        Artifact chunks collection instance
    """
    return client.get_or_create_collection(
        name="artifact_chunks",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "description": "Chunk vectors for documents exceeding token threshold",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_chunks_by_artifact(
    client: HttpClient,
    artifact_id: str
) -> List[Dict[str, Any]]:
    """
    Get all chunks for a specific artifact.

    Args:
        client: ChromaDB client
        artifact_id: Artifact ID to fetch chunks for

    Returns:
        List of chunks sorted by chunk_index
    """
    collection = get_artifact_chunks_collection(client)

    try:
        results = collection.get(
            where={"artifact_id": artifact_id}
        )

        if not results or not results.get("ids"):
            return []

        # Combine results into structured format
        chunks = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for chunk_id, content, metadata in zip(ids, documents, metadatas):
            chunks.append({
                "chunk_id": chunk_id,
                "content": content,
                "metadata": metadata
            })

        # Sort by chunk_index
        chunks.sort(key=lambda x: x["metadata"].get("chunk_index", 0))

        return chunks

    except Exception as e:
        logger.error(f"Failed to get chunks for artifact {artifact_id}: {e}")
        return []


def get_artifact_by_source(
    client: HttpClient,
    source_system: str,
    source_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get artifact by source system and source ID.

    Args:
        client: ChromaDB client
        source_system: Source system identifier
        source_id: Source ID within that system

    Returns:
        Artifact data or None if not found
    """
    collection = get_artifacts_collection(client)

    try:
        results = collection.get(
            where={
                "$and": [
                    {"source_system": source_system},
                    {"source_id": source_id}
                ]
            }
        )

        if not results or not results.get("ids"):
            return None

        # Return first match
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        if ids:
            return {
                "artifact_id": ids[0],
                "content": documents[0] if documents else "",
                "metadata": metadatas[0] if metadatas else {}
            }

        return None

    except Exception as e:
        logger.error(
            f"Failed to get artifact by source {source_system}:{source_id}: {e}"
        )
        return None


def delete_artifact_cascade(
    client: HttpClient,
    artifact_id: str
) -> int:
    """
    Delete artifact and all associated chunks.

    Args:
        client: ChromaDB client
        artifact_id: Artifact ID to delete

    Returns:
        Number of items deleted (artifact + chunks)
    """
    deleted_count = 0

    # Delete artifact
    artifacts_collection = get_artifacts_collection(client)
    try:
        artifacts_collection.delete(ids=[artifact_id])
        deleted_count += 1
    except Exception as e:
        logger.error(f"Failed to delete artifact {artifact_id}: {e}")

    # Delete associated chunks
    chunks_collection = get_artifact_chunks_collection(client)
    try:
        results = chunks_collection.get(
            where={"artifact_id": artifact_id}
        )

        chunk_ids = results.get("ids", [])
        if chunk_ids:
            chunks_collection.delete(ids=chunk_ids)
            deleted_count += len(chunk_ids)

    except Exception as e:
        logger.error(f"Failed to delete chunks for artifact {artifact_id}: {e}")

    return deleted_count
