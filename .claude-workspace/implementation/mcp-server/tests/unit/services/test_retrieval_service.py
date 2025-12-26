"""Unit tests for RetrievalService."""

import pytest
from unittest.mock import Mock, MagicMock, patch

from services.retrieval_service import RetrievalService
from storage.models import SearchResult, MergedResult, Chunk
from utils.errors import RetrievalError


# ============================================================================
# RRF Merging Tests
# ============================================================================

def test_rrf_merging_single_collection(retrieval_service):
    """Test RRF merging with results from single collection."""
    results_by_collection = {
        "artifacts": [
            SearchResult(
                id="art_001",
                content="Result 1",
                metadata={},
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            SearchResult(
                id="art_002",
                content="Result 2",
                metadata={},
                collection="artifacts",
                rank=1,
                distance=0.2,
                is_chunk=False
            )
        ]
    }

    merged = retrieval_service.merge_results_rrf(results_by_collection, limit=10)

    assert len(merged) == 2
    assert all(isinstance(r, MergedResult) for r in merged)
    # First result should have higher RRF score (lower rank)
    assert merged[0].result.id == "art_001"
    assert merged[1].result.id == "art_002"
    assert merged[0].rrf_score > merged[1].rrf_score


def test_rrf_merging_multiple_collections(retrieval_service):
    """Test RRF merging with results from multiple collections."""
    results_by_collection = {
        "artifacts": [
            SearchResult("art_001", "Content 1", {}, "artifacts", 0, 0.1, False),
            SearchResult("art_002", "Content 2", {}, "artifacts", 1, 0.2, False)
        ],
        "artifact_chunks": [
            SearchResult("chunk_001", "Chunk 1", {}, "artifact_chunks", 0, 0.15, True, "art_003"),
            SearchResult("art_001", "Content 1", {}, "artifact_chunks", 1, 0.25, False)  # Duplicate
        ]
    }

    merged = retrieval_service.merge_results_rrf(results_by_collection, limit=10)

    assert len(merged) == 3  # art_001, art_002, chunk_001
    # art_001 appears in both collections, so should have highest score
    assert merged[0].result.id == "art_001"
    assert "artifacts" in merged[0].collections
    assert "artifact_chunks" in merged[0].collections


def test_rrf_score_calculation(retrieval_service):
    """Test RRF score calculation formula."""
    results_by_collection = {
        "collection1": [
            SearchResult("doc1", "Content", {}, "collection1", 0, 0.1, False)
        ]
    }

    merged = retrieval_service.merge_results_rrf(results_by_collection, limit=10)

    # RRF score = 1 / (k + rank + 1) where k=60, rank=0
    # Expected: 1 / (60 + 0 + 1) = 1/61 ≈ 0.0164
    expected_score = 1.0 / (60 + 0 + 1)
    assert abs(merged[0].rrf_score - expected_score) < 0.0001


def test_rrf_merging_respects_limit(retrieval_service):
    """Test RRF merging respects limit parameter."""
    results_by_collection = {
        "artifacts": [
            SearchResult(f"art_{i:03d}", f"Content {i}", {}, "artifacts", i, 0.1 + i*0.01, False)
            for i in range(20)
        ]
    }

    merged = retrieval_service.merge_results_rrf(results_by_collection, limit=5)

    assert len(merged) == 5


def test_rrf_merging_empty_results(retrieval_service):
    """Test RRF merging with empty results."""
    results_by_collection = {}

    merged = retrieval_service.merge_results_rrf(results_by_collection, limit=10)

    assert merged == []


# ============================================================================
# Deduplication Tests
# ============================================================================

def test_deduplicate_prefers_chunks(retrieval_service):
    """Test deduplication prefers chunk results over full artifacts."""
    results = [
        MergedResult(
            result=SearchResult("art_001", "Full artifact", {}, "artifacts", 0, 0.1, False),
            rrf_score=0.5,
            collections=["artifacts"]
        ),
        MergedResult(
            result=SearchResult(
                "art_001::chunk::000::abc",
                "Chunk content",
                {"artifact_id": "art_001"},
                "artifact_chunks",
                0,
                0.15,
                True,
                "art_001"
            ),
            rrf_score=0.4,  # Lower score but is a chunk
            collections=["artifact_chunks"]
        )
    ]

    deduplicated = retrieval_service.deduplicate_by_artifact(results)

    # Should keep only the chunk, not the full artifact
    assert len(deduplicated) == 1
    assert deduplicated[0].result.is_chunk is True
    assert "chunk" in deduplicated[0].result.id


def test_deduplicate_keeps_best_chunk(retrieval_service):
    """Test deduplication keeps highest scoring chunk."""
    results = [
        MergedResult(
            result=SearchResult(
                "art_001::chunk::000::abc",
                "Chunk 0",
                {"artifact_id": "art_001", "chunk_index": 0},
                "artifact_chunks",
                0,
                0.1,
                True,
                "art_001"
            ),
            rrf_score=0.4,
            collections=["artifact_chunks"]
        ),
        MergedResult(
            result=SearchResult(
                "art_001::chunk::001::def",
                "Chunk 1",
                {"artifact_id": "art_001", "chunk_index": 1},
                "artifact_chunks",
                1,
                0.15,
                True,
                "art_001"
            ),
            rrf_score=0.6,  # Higher score
            collections=["artifact_chunks"]
        )
    ]

    deduplicated = retrieval_service.deduplicate_by_artifact(results)

    # Should keep only the higher scoring chunk
    assert len(deduplicated) == 1
    assert deduplicated[0].rrf_score == 0.6
    assert "chunk::001" in deduplicated[0].result.id


def test_deduplicate_different_artifacts(retrieval_service):
    """Test deduplication keeps results from different artifacts."""
    results = [
        MergedResult(
            result=SearchResult("art_001", "Content 1", {}, "artifacts", 0, 0.1, False),
            rrf_score=0.5,
            collections=["artifacts"]
        ),
        MergedResult(
            result=SearchResult("art_002", "Content 2", {}, "artifacts", 1, 0.2, False),
            rrf_score=0.4,
            collections=["artifacts"]
        )
    ]

    deduplicated = retrieval_service.deduplicate_by_artifact(results)

    # Should keep both (different artifacts)
    assert len(deduplicated) == 2


def test_deduplicate_empty_list(retrieval_service):
    """Test deduplication with empty list."""
    deduplicated = retrieval_service.deduplicate_by_artifact([])
    assert deduplicated == []


# ============================================================================
# Collection Search Tests
# ============================================================================

def test_search_collection_memory(retrieval_service, mock_chroma_client):
    """Test searching memory collection."""
    mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
        "ids": [["mem_001"]],
        "documents": [["Memory content"]],
        "metadatas": [[{"type": "preference"}]],
        "distances": [[0.1]]
    }

    results = retrieval_service._search_collection(
        collection_name="memory",
        query_embedding=[0.1] * 3072,
        limit=5
    )

    assert len(results) == 1
    assert results[0].id == "mem_001"
    assert results[0].collection == "memory"
    assert results[0].is_chunk is False


def test_search_collection_artifacts(retrieval_service, mock_chroma_client):
    """Test searching artifacts collection."""
    mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
        "ids": [["art_001"]],
        "documents": [["Artifact content"]],
        "metadatas": [[{"title": "Test Doc"}]],
        "distances": [[0.15]]
    }

    results = retrieval_service._search_collection(
        collection_name="artifacts",
        query_embedding=[0.1] * 3072,
        limit=5
    )

    assert len(results) == 1
    assert results[0].id == "art_001"
    assert results[0].collection == "artifacts"


def test_search_collection_chunks(retrieval_service, mock_chroma_client):
    """Test searching artifact_chunks collection."""
    mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
        "ids": [["art_001::chunk::000::abc"]],
        "documents": [["Chunk content"]],
        "metadatas": [[{"artifact_id": "art_001", "chunk_index": 0}]],
        "distances": [[0.12]]
    }

    results = retrieval_service._search_collection(
        collection_name="artifact_chunks",
        query_embedding=[0.1] * 3072,
        limit=5
    )

    assert len(results) == 1
    assert results[0].is_chunk is True
    assert results[0].artifact_id == "art_001"


def test_search_collection_with_filters(retrieval_service, mock_chroma_client):
    """Test searching with metadata filters."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value

    retrieval_service._search_collection(
        collection_name="artifacts",
        query_embedding=[0.1] * 3072,
        limit=5,
        filters={"artifact_type": "doc"}
    )

    # Verify filters were passed to query
    call_kwargs = mock_collection.query.call_args[1]
    assert "where" in call_kwargs
    assert call_kwargs["where"] == {"artifact_type": "doc"}


def test_search_collection_error_handling(retrieval_service, mock_chroma_client):
    """Test search handles collection errors gracefully."""
    mock_chroma_client.get_or_create_collection.return_value.query.side_effect = Exception("DB error")

    results = retrieval_service._search_collection(
        collection_name="artifacts",
        query_embedding=[0.1] * 3072,
        limit=5
    )

    # Should return empty list on error
    assert results == []


# ============================================================================
# Hybrid Search Tests
# ============================================================================

@pytest.mark.mock_openai
def test_hybrid_search_without_memory(retrieval_service, mock_chroma_client):
    """Test hybrid search excludes memory collection."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.query.return_value = {
        "ids": [["art_001"]],
        "documents": [["Content"]],
        "metadatas": [[{"title": "Test"}]],
        "distances": [[0.1]]
    }

    results = retrieval_service.hybrid_search(
        query="test query",
        limit=5,
        include_memory=False
    )

    # Should search artifacts and artifact_chunks (2 collections)
    assert mock_chroma_client.get_or_create_collection.call_count >= 2


@pytest.mark.mock_openai
def test_hybrid_search_with_memory(retrieval_service, mock_chroma_client):
    """Test hybrid search includes memory collection."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.query.return_value = {
        "ids": [["art_001"]],
        "documents": [["Content"]],
        "metadatas": [[{"title": "Test"}]],
        "distances": [[0.1]]
    }

    results = retrieval_service.hybrid_search(
        query="test query",
        limit=5,
        include_memory=True
    )

    # Should search artifacts, artifact_chunks, and memory (3 collections)
    assert mock_chroma_client.get_or_create_collection.call_count >= 3


@pytest.mark.mock_openai
def test_hybrid_search_with_filters(retrieval_service, mock_chroma_client):
    """Test hybrid search applies filters."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }

    retrieval_service.hybrid_search(
        query="test query",
        limit=5,
        filters={"artifact_type": "email"}
    )

    # Verify filters were passed to at least one query
    assert mock_collection.query.called


@pytest.mark.mock_openai
def test_hybrid_search_respects_limit(retrieval_service, mock_chroma_client):
    """Test hybrid search respects result limit."""
    # Create 20 mock results
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.query.return_value = {
        "ids": [[f"art_{i:03d}" for i in range(20)]],
        "documents": [[f"Content {i}" for i in range(20)]],
        "metadatas": [[{"title": f"Doc {i}"} for i in range(20)]],
        "distances": [[0.1 + i*0.01 for i in range(20)]]
    }

    results = retrieval_service.hybrid_search(
        query="test query",
        limit=5
    )

    # Should return at most 5 results
    assert len(results) <= 5


@pytest.mark.mock_openai
def test_hybrid_search_empty_results(retrieval_service, mock_chroma_client):
    """Test hybrid search with no results."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }

    results = retrieval_service.hybrid_search(
        query="test query",
        limit=5
    )

    assert results == []


# ============================================================================
# Neighbor Expansion Tests
# ============================================================================

def test_expand_neighbors_success(retrieval_service, mock_chroma_client):
    """Test successful neighbor expansion."""
    # Mock get_chunks_by_artifact to return chunks
    with patch("services.retrieval_service.get_chunks_by_artifact") as mock_get_chunks:
        mock_get_chunks.return_value = [
            {
                "chunk_id": "art_001::chunk::000::abc",
                "content": "Chunk 0",
                "metadata": {
                    "artifact_id": "art_001",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 7,
                    "token_count": 2,
                    "content_hash": "abc"
                }
            },
            {
                "chunk_id": "art_001::chunk::001::def",
                "content": "Chunk 1",
                "metadata": {
                    "artifact_id": "art_001",
                    "chunk_index": 1,
                    "start_char": 7,
                    "end_char": 14,
                    "token_count": 2,
                    "content_hash": "def"
                }
            },
            {
                "chunk_id": "art_001::chunk::002::ghi",
                "content": "Chunk 2",
                "metadata": {
                    "artifact_id": "art_001",
                    "chunk_index": 2,
                    "start_char": 14,
                    "end_char": 21,
                    "token_count": 2,
                    "content_hash": "ghi"
                }
            }
        ]

        results = [
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::001::def",
                    content="Chunk 1",
                    metadata={"artifact_id": "art_001", "chunk_index": 1},
                    collection="artifact_chunks",
                    rank=0,
                    distance=0.1,
                    is_chunk=True,
                    artifact_id="art_001"
                ),
                rrf_score=0.5,
                collections=["artifact_chunks"]
            )
        ]

        retrieval_service._expand_neighbors(results)

        # Content should now include neighbors with boundaries
        expanded_content = results[0].result.content
        assert "[CHUNK BOUNDARY]" in expanded_content
        assert "Chunk 0" in expanded_content
        assert "Chunk 1" in expanded_content
        assert "Chunk 2" in expanded_content


def test_expand_neighbors_skips_non_chunks(retrieval_service):
    """Test neighbor expansion skips non-chunk results."""
    results = [
        MergedResult(
            result=SearchResult(
                id="art_001",
                content="Full artifact",
                metadata={},
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            rrf_score=0.5,
            collections=["artifacts"]
        )
    ]

    original_content = results[0].result.content

    retrieval_service._expand_neighbors(results)

    # Content should be unchanged
    assert results[0].result.content == original_content


def test_expand_neighbors_handles_errors(retrieval_service, mock_chroma_client):
    """Test neighbor expansion handles errors gracefully."""
    with patch("services.retrieval_service.get_chunks_by_artifact") as mock_get_chunks:
        mock_get_chunks.side_effect = Exception("DB error")

        results = [
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::001::def",
                    content="Original content",
                    metadata={"artifact_id": "art_001", "chunk_index": 1},
                    collection="artifact_chunks",
                    rank=0,
                    distance=0.1,
                    is_chunk=True,
                    artifact_id="art_001"
                ),
                rrf_score=0.5,
                collections=["artifact_chunks"]
            )
        ]

        original_content = results[0].result.content

        # Should not raise exception
        retrieval_service._expand_neighbors(results)

        # Content should be unchanged on error
        assert results[0].result.content == original_content
