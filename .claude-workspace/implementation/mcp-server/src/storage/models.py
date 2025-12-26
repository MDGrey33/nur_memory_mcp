"""Data models for MCP Memory Server."""

from dataclasses import dataclass
from typing import Optional, List, Any, Dict


@dataclass
class Chunk:
    """Represents a single chunk of an artifact."""
    chunk_id: str
    artifact_id: str
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    token_count: int
    content_hash: str


@dataclass
class SearchResult:
    """Single search result from ChromaDB."""
    id: str
    content: str
    metadata: Dict[str, Any]
    collection: str
    rank: int
    distance: float
    is_chunk: bool = False
    artifact_id: Optional[str] = None


@dataclass
class MergedResult:
    """RRF-merged search result."""
    result: SearchResult
    rrf_score: float
    collections: List[str]


@dataclass
class ArtifactMetadata:
    """Artifact metadata."""
    artifact_id: str
    artifact_type: str
    source_system: str
    source_id: Optional[str]
    source_url: Optional[str]
    ts: str
    title: Optional[str]
    author: Optional[str]
    participants: Optional[List[str]]
    content_hash: str
    token_count: int
    is_chunked: bool
    num_chunks: int
    sensitivity: str
    visibility_scope: str
    retention_policy: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    ingested_at: str
