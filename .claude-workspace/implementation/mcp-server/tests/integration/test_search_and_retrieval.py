"""Integration tests for search and retrieval operations."""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock


@pytest.fixture
def mock_search_services():
    """Mock services for search testing."""
    with patch("server.embedding_service") as mock_embed, \
         patch("server.retrieval_service") as mock_retrieval, \
         patch("server.chroma_manager") as mock_chroma, \
         patch("server.config") as mock_config:

        # Setup mock embedding service
        mock_embed.generate_embedding.return_value = [0.1] * 3072

        # Setup mock chroma
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        mock_config.openai_embed_model = "text-embedding-3-large"
        mock_config.openai_embed_dims = 3072

        # hybrid_search tool now calls retrieval_service.hybrid_search_v4 (async)
        mock_retrieval.hybrid_search_v4 = AsyncMock()

        yield {
            "embed": mock_embed,
            "retrieval": mock_retrieval,
            "chroma": mock_chroma,
            "config": mock_config,
            "client": mock_client,
            "collection": mock_collection
        }


@pytest.mark.integration
def test_search_unchunked_artifacts(mock_search_services):
    """Test searching returns unchunked artifacts."""
    from server import artifact_search
    from storage.models import SearchResult, MergedResult

    # Mock retrieval service to return unchunked artifact
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_001",
                content="This is an unchunked artifact.",
                metadata={
                    "title": "Test Doc",
                    "artifact_type": "doc",
                    "source_system": "manual",
                    "sensitivity": "normal"
                },
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            rrf_score=0.5,
            collections=["artifacts"]
        )
    ]

    mock_search_services["retrieval"].hybrid_search.return_value = mock_results

    result = artifact_search(query="test query", limit=5)

    assert "Error" not in result
    assert "Found 1 results" in result
    assert "art_001" in result
    assert "Test Doc" in result
    assert "unchunked artifact" in result


@pytest.mark.integration
def test_search_chunks(mock_search_services):
    """Test searching returns chunk results."""
    from server import artifact_search
    from storage.models import SearchResult, MergedResult

    # Mock retrieval service to return chunk
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_002::chunk::001::abc",
                content="This is a chunk of a larger document.",
                metadata={
                    "artifact_id": "art_002",
                    "chunk_index": 1,
                    "title": "Large Doc",
                    "artifact_type": "doc",
                    "source_system": "manual",
                    "sensitivity": "normal"
                },
                collection="artifact_chunks",
                rank=0,
                distance=0.12,
                is_chunk=True,
                artifact_id="art_002"
            ),
            rrf_score=0.48,
            collections=["artifact_chunks"]
        )
    ]

    mock_search_services["retrieval"].hybrid_search.return_value = mock_results

    result = artifact_search(query="test query", limit=5)

    assert "Error" not in result
    assert "Found 1 results" in result
    assert "chunk" in result.lower()
    assert "art_002::chunk::001" in result
    assert "Large Doc" in result


@pytest.mark.integration
def test_search_with_neighbor_expansion(mock_search_services):
    """Test searching with neighbor expansion enabled."""
    from server import artifact_search
    from storage.models import SearchResult, MergedResult

    # Mock retrieval service
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_003::chunk::001::abc",
                content="Chunk 0\n[CHUNK BOUNDARY]\nChunk 1\n[CHUNK BOUNDARY]\nChunk 2",
                metadata={
                    "artifact_id": "art_003",
                    "chunk_index": 1,
                    "title": "Doc with Context",
                    "artifact_type": "doc",
                    "source_system": "manual",
                    "sensitivity": "normal"
                },
                collection="artifact_chunks",
                rank=0,
                distance=0.1,
                is_chunk=True,
                artifact_id="art_003"
            ),
            rrf_score=0.5,
            collections=["artifact_chunks"]
        )
    ]

    mock_search_services["retrieval"].hybrid_search.return_value = mock_results

    result = artifact_search(query="test query", limit=5, expand_neighbors=True)

    assert "Error" not in result
    assert "[CHUNK BOUNDARY]" in result or "Chunk" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_with_memory(mock_search_services):
    """Test hybrid search including memory collection."""
    from server import hybrid_search
    from storage.models import SearchResult, MergedResult

    # Mock results from multiple collections
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_001",
                content="Artifact content",
                metadata={"title": "Doc", "artifact_type": "doc", "source_system": "manual"},
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            rrf_score=0.5,
            collections=["artifacts"]
        ),
        MergedResult(
            result=SearchResult(
                id="mem_001",
                content="User prefers dark mode",
                metadata={"type": "preference", "confidence": 0.9},
                collection="memory",
                rank=0,
                distance=0.15,
                is_chunk=False
            ),
            rrf_score=0.45,
            collections=["memory"]
        )
    ]

    # Provide a fake V4SearchResult object with to_dict() matching server expectations.
    mock_search_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {"primary_results": [
            {
                "id": r.result.id,
                "content": r.result.content,
                "metadata": r.result.metadata,
                "collection": r.result.collection,
                "rrf_score": r.rrf_score,
                "artifact_uid": None
            } for r in mock_results
        ], "related_context": [], "entities": [], "expand_options": {}}
    )

    result = await hybrid_search(query="test query", limit=5, include_memory=True)

    assert "error" not in result
    assert "primary_results" in result
    assert len(result["primary_results"]) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_without_memory(mock_search_services):
    """Test hybrid search excluding memory collection."""
    from server import hybrid_search
    from storage.models import SearchResult, MergedResult

    # Mock results only from artifacts
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_001",
                content="Artifact content",
                metadata={"title": "Doc", "artifact_type": "doc", "source_system": "manual"},
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            rrf_score=0.5,
            collections=["artifacts"]
        )
    ]

    mock_search_services["retrieval"].hybrid_search_v4.return_value = MagicMock(
        to_dict=lambda: {"primary_results": [
            {
                "id": r.result.id,
                "content": r.result.content,
                "metadata": r.result.metadata,
                "collection": r.result.collection,
                "rrf_score": r.rrf_score,
                "artifact_uid": None
            } for r in mock_results
        ], "related_context": [], "entities": [], "expand_options": {}}
    )

    result = await hybrid_search(query="test query", limit=5, include_memory=False)

    assert "error" not in result
    assert "primary_results" in result
    assert len(result["primary_results"]) == 1


@pytest.mark.integration
def test_search_with_filters(mock_search_services):
    """Test searching with metadata filters."""
    from server import artifact_search
    from storage.models import SearchResult, MergedResult

    # Mock filtered results
    mock_results = [
        MergedResult(
            result=SearchResult(
                id="art_email_001",
                content="Email content",
                metadata={
                    "title": "Test Email",
                    "artifact_type": "email",
                    "source_system": "gmail",
                    "sensitivity": "normal"
                },
                collection="artifacts",
                rank=0,
                distance=0.1,
                is_chunk=False
            ),
            rrf_score=0.5,
            collections=["artifacts"]
        )
    ]

    mock_search_services["retrieval"].hybrid_search.return_value = mock_results

    result = artifact_search(
        query="test query",
        limit=5,
        artifact_type="email",
        source_system="gmail"
    )

    # Verify filters were passed to retrieval service
    call_kwargs = mock_search_services["retrieval"].hybrid_search.call_args[1]
    assert "filters" in call_kwargs
    assert call_kwargs["filters"]["artifact_type"] == "email"
    assert call_kwargs["filters"]["source_system"] == "gmail"

    assert "Error" not in result
    assert "email" in result.lower()


@pytest.mark.integration
def test_search_empty_results(mock_search_services):
    """Test search with no results."""
    from server import artifact_search

    mock_search_services["retrieval"].hybrid_search.return_value = []

    result = artifact_search(query="nonexistent query", limit=5)

    assert "No results found" in result


@pytest.mark.integration
def test_search_invalid_query(mock_search_services):
    """Test search with invalid query."""
    from server import artifact_search

    result = artifact_search(query="", limit=5)

    assert "Error" in result
    assert "Query must be between" in result


@pytest.mark.integration
def test_search_invalid_limit(mock_search_services):
    """Test search with invalid limit."""
    from server import artifact_search

    result = artifact_search(query="test", limit=100)

    assert "Error" in result
    assert "Limit must be between" in result
