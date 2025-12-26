"""Unit tests for data models."""

import pytest
from storage.models import Chunk, SearchResult, MergedResult, ArtifactMetadata


def test_chunk_creation():
    """Test Chunk dataclass creation."""
    chunk = Chunk(
        chunk_id="art_001::chunk::000::abc123",
        artifact_id="art_001",
        chunk_index=0,
        content="Test content",
        start_char=0,
        end_char=12,
        token_count=3,
        content_hash="abc123"
    )

    assert chunk.chunk_id == "art_001::chunk::000::abc123"
    assert chunk.artifact_id == "art_001"
    assert chunk.chunk_index == 0
    assert chunk.content == "Test content"
    assert chunk.start_char == 0
    assert chunk.end_char == 12
    assert chunk.token_count == 3
    assert chunk.content_hash == "abc123"


def test_search_result_creation():
    """Test SearchResult dataclass creation."""
    result = SearchResult(
        id="art_001",
        content="Test content",
        metadata={"title": "Test"},
        collection="artifacts",
        rank=0,
        distance=0.1,
        is_chunk=False,
        artifact_id=None
    )

    assert result.id == "art_001"
    assert result.content == "Test content"
    assert result.metadata == {"title": "Test"}
    assert result.collection == "artifacts"
    assert result.rank == 0
    assert result.distance == 0.1
    assert result.is_chunk is False
    assert result.artifact_id is None


def test_search_result_default_values():
    """Test SearchResult with default values."""
    result = SearchResult(
        id="art_001",
        content="Test",
        metadata={},
        collection="artifacts",
        rank=0,
        distance=0.1
    )

    assert result.is_chunk is False
    assert result.artifact_id is None


def test_merged_result_creation():
    """Test MergedResult dataclass creation."""
    search_result = SearchResult(
        id="art_001",
        content="Test",
        metadata={},
        collection="artifacts",
        rank=0,
        distance=0.1
    )

    merged = MergedResult(
        result=search_result,
        rrf_score=0.5,
        collections=["artifacts", "memory"]
    )

    assert merged.result == search_result
    assert merged.rrf_score == 0.5
    assert merged.collections == ["artifacts", "memory"]


def test_artifact_metadata_creation():
    """Test ArtifactMetadata dataclass creation."""
    metadata = ArtifactMetadata(
        artifact_id="art_001",
        artifact_type="email",
        source_system="gmail",
        source_id="msg123",
        source_url="https://mail.google.com/...",
        ts="2025-01-01T00:00:00Z",
        title="Test Email",
        author="test@example.com",
        participants=["user1@example.com", "user2@example.com"],
        content_hash="abc123",
        token_count=500,
        is_chunked=False,
        num_chunks=0,
        sensitivity="normal",
        visibility_scope="me",
        retention_policy="forever",
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimensions=3072,
        ingested_at="2025-01-01T00:01:00Z"
    )

    assert metadata.artifact_id == "art_001"
    assert metadata.artifact_type == "email"
    assert metadata.source_system == "gmail"
    assert metadata.is_chunked is False
    assert metadata.num_chunks == 0
    assert metadata.token_count == 500
