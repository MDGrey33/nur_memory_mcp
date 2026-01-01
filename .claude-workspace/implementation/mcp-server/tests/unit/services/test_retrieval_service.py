"""Unit tests for RetrievalService - V6."""

import pytest
from unittest.mock import Mock, MagicMock

from services.retrieval_service import RetrievalService
from storage.models import SearchResult, MergedResult
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


# Legacy tests removed in V6.1:
# - Collection search tests (_search_collection deleted)
# - Hybrid search tests (hybrid_search deleted)
# - Neighbor expansion tests (_expand_neighbors deleted)
