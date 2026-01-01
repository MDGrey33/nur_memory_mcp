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


# =============================================================================
# V6 COLLECTIONS - Unified Content Storage
# =============================================================================

def get_content_collection(client: HttpClient) -> Collection:
    """
    Get or create the unified content collection (V5).

    All content types (documents, preferences, facts, conversations) are stored
    here with a 'context' metadata field to differentiate them.

    Args:
        client: ChromaDB client

    Returns:
        Content collection instance
    """
    return client.get_or_create_collection(
        name="content",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "hnsw:space": "cosine",
            "description": "V5 unified content storage",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_chunks_collection(client: HttpClient) -> Collection:
    """
    Get or create the chunks collection (V5).

    Stores chunks for large content that exceeds the token threshold.

    Args:
        client: ChromaDB client

    Returns:
        Chunks collection instance
    """
    return client.get_or_create_collection(
        name="chunks",
        embedding_function=None,  # We provide our own embeddings
        metadata={
            "hnsw:space": "cosine",
            "description": "V5 chunks for large content",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072
        }
    )


def get_content_by_id(client: HttpClient, content_id: str) -> Optional[Dict[str, Any]]:
    """
    Get content by ID from V5 content collection.

    Args:
        client: ChromaDB client
        content_id: Content ID (art_xxx format)

    Returns:
        Content data or None if not found
    """
    collection = get_content_collection(client)

    try:
        results = collection.get(ids=[content_id], include=["documents", "metadatas"])

        if not results or not results.get("ids"):
            return None

        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        if ids:
            return {
                "id": ids[0],
                "content": documents[0] if documents else "",
                "metadata": metadatas[0] if metadatas else {}
            }

        return None

    except Exception as e:
        logger.error(f"Failed to get content {content_id}: {e}")
        return None


def get_v5_chunks_by_content(client: HttpClient, content_id: str) -> List[Dict[str, Any]]:
    """
    Get all chunks for a specific content ID from V5 chunks collection.

    Args:
        client: ChromaDB client
        content_id: Content ID to fetch chunks for

    Returns:
        List of chunks sorted by chunk_index
    """
    collection = get_chunks_collection(client)

    try:
        results = collection.get(
            where={"content_id": content_id},
            include=["documents", "metadatas"]
        )

        if not results or not results.get("ids"):
            return []

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
        logger.error(f"Failed to get V5 chunks for content {content_id}: {e}")
        return []


def delete_v5_content_cascade(client: HttpClient, content_id: str) -> Dict[str, int]:
    """
    Delete content and all associated chunks from V5 collections.

    Args:
        client: ChromaDB client
        content_id: Content ID to delete (art_xxx format)

    Returns:
        Dict with counts of deleted items
    """
    deleted = {"content": 0, "chunks": 0}

    # Delete from content collection
    content_collection = get_content_collection(client)
    try:
        content_collection.delete(ids=[content_id])
        deleted["content"] = 1
    except Exception as e:
        logger.error(f"Failed to delete V5 content {content_id}: {e}")

    # Delete associated chunks
    chunks_collection = get_chunks_collection(client)
    try:
        results = chunks_collection.get(where={"content_id": content_id})
        chunk_ids = results.get("ids", [])
        if chunk_ids:
            chunks_collection.delete(ids=chunk_ids)
            deleted["chunks"] = len(chunk_ids)
    except Exception as e:
        logger.error(f"Failed to delete V5 chunks for content {content_id}: {e}")

    return deleted
