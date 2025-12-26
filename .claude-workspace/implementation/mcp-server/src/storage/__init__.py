"""Storage module for MCP Memory Server."""

from storage.chroma_client import ChromaClientManager
from storage.models import Chunk, SearchResult, MergedResult, ArtifactMetadata
from storage.collections import (
    get_memory_collection,
    get_history_collection,
    get_artifacts_collection,
    get_artifact_chunks_collection,
    get_chunks_by_artifact,
    get_artifact_by_source,
    delete_artifact_cascade
)

__all__ = [
    "ChromaClientManager",
    "Chunk",
    "SearchResult",
    "MergedResult",
    "ArtifactMetadata",
    "get_memory_collection",
    "get_history_collection",
    "get_artifacts_collection",
    "get_artifact_chunks_collection",
    "get_chunks_by_artifact",
    "get_artifact_by_source",
    "delete_artifact_cascade",
]
