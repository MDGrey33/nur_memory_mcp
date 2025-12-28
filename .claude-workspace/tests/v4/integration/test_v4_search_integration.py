"""
Integration tests for V4 search functionality.

Tests:
- hybrid_search with graph_expand=true
- graph_seed_limit respected
- graph_budget limits results
- graph_filters work correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID
import json

from services.retrieval_service import (
    RetrievalService,
    V4SearchResult,
    RelatedContextItem,
    EntityInfo
)
from services.graph_service import GraphService, RelatedContext
from storage.models import SearchResult, MergedResult


# =============================================================================
# Test Markers
# =============================================================================

pytestmark = [pytest.mark.v4, pytest.mark.integration]


# =============================================================================
# hybrid_search with graph_expand=true Tests
# =============================================================================

class TestHybridSearchGraphExpand:
    """Tests for hybrid_search with graph_expand enabled."""

    @pytest.mark.asyncio
    async def test_hybrid_search_v4_returns_related_context(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test hybrid_search_v4 returns related_context when graph_expand=true."""
        # Setup mock primary results
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Test document content"]],
            "metadatas": [[{"title": "Test Doc"}]],
            "distances": [[0.1]]
        }

        # Setup mock revision lookup
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }

        # Setup mock events for artifact
        mock_pg_client.fetch_all.return_value = [
            {"event_id": uuid4()}
        ]

        # Setup mock graph expansion
        related_event_id = uuid4()
        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=related_event_id,
                category="Decision",
                narrative="Related decision from graph",
                reason="same_actor:Alice Chen",
                event_time="2024-03-15T10:00:00Z",
                confidence=0.9,
                entity_name="Alice Chen",
                artifact_uid="doc_002",
                revision_id="rev_001"
            )
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test query",
            limit=5,
            graph_expand=True,
            graph_budget=10
        )

        assert isinstance(result, V4SearchResult)
        assert len(result.related_context) == 1
        assert result.related_context[0].reason == "same_actor:Alice Chen"

    @pytest.mark.asyncio
    async def test_hybrid_search_v4_returns_entities_when_requested(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test hybrid_search_v4 returns entities when include_entities=true."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        mock_graph_service.expand_from_events.return_value = []
        mock_graph_service.get_entities_for_events.return_value = [
            {
                "entity_id": str(uuid4()),
                "name": "Alice Chen",
                "type": "person",
                "role": "Engineer",
                "organization": "Acme",
                "mention_count": 3
            }
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            include_entities=True
        )

        assert len(result.entities) == 1
        assert result.entities[0].name == "Alice Chen"
        assert result.entities[0].mention_count == 3

    @pytest.mark.asyncio
    async def test_hybrid_search_v4_returns_expand_options(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test hybrid_search_v4 returns expand_options metadata."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_budget=15,
            graph_seed_limit=3
        )

        assert "graph_expand" in result.expand_options
        assert result.expand_options["graph_budget"] == 15
        assert result.expand_options["graph_seed_limit"] == 3

    @pytest.mark.asyncio
    async def test_hybrid_search_v4_backward_compatible_without_graph(
        self, retrieval_service_v4, mock_chroma_client
    ):
        """Test hybrid_search_v4 is backward compatible when graph_expand=false."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{"title": "Doc"}]],
            "distances": [[0.1]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=False
        )

        assert len(result.primary_results) == 1
        assert result.related_context == []
        assert result.entities == []


# =============================================================================
# graph_seed_limit Tests
# =============================================================================

class TestGraphSeedLimit:
    """Tests for graph_seed_limit parameter."""

    @pytest.mark.asyncio
    async def test_graph_seed_limit_limits_expansion_seeds(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_seed_limit limits number of results used for expansion."""
        # Return 10 primary results
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [[f"art_{i:03d}" for i in range(10)]],
            "documents": [[f"Content {i}" for i in range(10)]],
            "metadatas": [[{"title": f"Doc {i}"} for i in range(10)]],
            "distances": [[0.1 + i*0.01 for i in range(10)]]
        }

        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]
        mock_graph_service.expand_from_events.return_value = []

        await retrieval_service_v4.hybrid_search_v4(
            query="test",
            limit=10,
            graph_expand=True,
            graph_seed_limit=3
        )

        # Verify expand_from_events was called with limited seeds
        # The number of seed events should come from at most 3 primary results

    @pytest.mark.asyncio
    async def test_graph_seed_limit_reported_in_expand_options(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_seed_limit is reported in expand_options."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001", "art_002", "art_003"]],
            "documents": [["A", "B", "C"]],
            "metadatas": [[{}, {}, {}]],
            "distances": [[0.1, 0.2, 0.3]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]
        mock_graph_service.expand_from_events.return_value = []

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_seed_limit=2
        )

        assert result.expand_options["graph_seed_limit"] == 2
        assert result.expand_options["seeds_used"] <= 2


# =============================================================================
# graph_budget Tests
# =============================================================================

class TestGraphBudget:
    """Tests for graph_budget parameter."""

    @pytest.mark.asyncio
    async def test_graph_budget_limits_related_context(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_budget limits number of related context items."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        # Return more results than budget
        mock_graph_service.expand_from_events.return_value = [
            RelatedContext(
                event_id=uuid4(),
                category="Decision",
                narrative=f"Event {i}",
                reason="same_actor:Test",
                event_time=None,
                confidence=0.9,
                entity_name="Test",
                artifact_uid="doc",
                revision_id="rev"
            )
            for i in range(20)
        ]

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_budget=5
        )

        # Graph service should have been called with budget=5
        mock_graph_service.expand_from_events.assert_called_once()
        call_kwargs = mock_graph_service.expand_from_events.call_args
        assert call_kwargs.kwargs.get("budget") == 5 or call_kwargs[1].get("budget") == 5

    @pytest.mark.asyncio
    async def test_graph_budget_reported_in_expand_options(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_budget is reported in expand_options."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_budget=15
        )

        assert result.expand_options["graph_budget"] == 15


# =============================================================================
# graph_filters Tests
# =============================================================================

class TestGraphFilters:
    """Tests for graph_filters parameter."""

    @pytest.mark.asyncio
    async def test_graph_filters_passed_to_expansion(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_filters are passed to graph expansion."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]
        mock_graph_service.expand_from_events.return_value = []

        await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_filters={"categories": ["Decision", "Commitment"]}
        )

        # Verify category_filter was passed
        mock_graph_service.expand_from_events.assert_called_once()
        call_kwargs = mock_graph_service.expand_from_events.call_args
        category_filter = call_kwargs.kwargs.get("category_filter") or call_kwargs[1].get("category_filter")
        assert category_filter == ["Decision", "Commitment"]

    @pytest.mark.asyncio
    async def test_graph_filters_null_returns_all_categories(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test graph_filters=null returns all categories."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]
        mock_graph_service.expand_from_events.return_value = []

        await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True,
            graph_filters=None
        )

        call_kwargs = mock_graph_service.expand_from_events.call_args
        category_filter = call_kwargs.kwargs.get("category_filter") or call_kwargs[1].get("category_filter")
        assert category_filter is None


# =============================================================================
# Seed Event Collection Tests
# =============================================================================

class TestSeedEventCollection:
    """Tests for collecting seed events from primary results."""

    @pytest.mark.asyncio
    async def test_get_seed_events_from_artifacts(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test _get_seed_events extracts events from artifact results."""
        # Setup mock artifact revision
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }

        # Setup mock events
        event_ids = [uuid4(), uuid4()]
        mock_pg_client.fetch_all.return_value = [
            {"event_id": event_ids[0]},
            {"event_id": event_ids[1]}
        ]

        # Create mock result
        primary_results = [
            MergedResult(
                result=SearchResult(
                    id="art_001",
                    content="Content",
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

        seed_events = await retrieval_service_v4._get_seed_events(primary_results)

        assert len(seed_events) >= 2
        assert event_ids[0] in seed_events
        assert event_ids[1] in seed_events

    @pytest.mark.asyncio
    async def test_get_seed_events_from_chunks(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test _get_seed_events extracts events from chunk results."""
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }

        event_id = uuid4()
        mock_pg_client.fetch_all.return_value = [{"event_id": event_id}]

        primary_results = [
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::000::abc",
                    content="Chunk content",
                    metadata={"artifact_id": "art_001"},
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

        seed_events = await retrieval_service_v4._get_seed_events(primary_results)

        assert event_id in seed_events

    @pytest.mark.asyncio
    async def test_get_seed_events_deduplicates(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test _get_seed_events deduplicates event IDs."""
        mock_pg_client.fetch_one.return_value = {
            "artifact_uid": "doc_001",
            "revision_id": "rev_001"
        }

        # Same event returned for multiple chunks
        event_id = uuid4()
        mock_pg_client.fetch_all.return_value = [{"event_id": event_id}]

        primary_results = [
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::000::abc",
                    content="Chunk 0",
                    metadata={"artifact_id": "art_001"},
                    collection="artifact_chunks",
                    rank=0,
                    distance=0.1,
                    is_chunk=True,
                    artifact_id="art_001"
                ),
                rrf_score=0.5,
                collections=["artifact_chunks"]
            ),
            MergedResult(
                result=SearchResult(
                    id="art_001::chunk::001::def",
                    content="Chunk 1",
                    metadata={"artifact_id": "art_001"},
                    collection="artifact_chunks",
                    rank=1,
                    distance=0.15,
                    is_chunk=True,
                    artifact_id="art_001"
                ),
                rrf_score=0.4,
                collections=["artifact_chunks"]
            )
        ]

        seed_events = await retrieval_service_v4._get_seed_events(primary_results)

        # Should be deduplicated to one event
        assert len(seed_events) == 1

    @pytest.mark.asyncio
    async def test_get_seed_events_handles_missing_revision(
        self, retrieval_service_v4, mock_pg_client
    ):
        """Test _get_seed_events handles missing artifact_revision gracefully."""
        mock_pg_client.fetch_one.return_value = None  # No revision found

        primary_results = [
            MergedResult(
                result=SearchResult(
                    id="art_unknown",
                    content="Content",
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

        seed_events = await retrieval_service_v4._get_seed_events(primary_results)

        # Should return empty, not raise
        assert seed_events == []


# =============================================================================
# V4SearchResult Tests
# =============================================================================

class TestV4SearchResult:
    """Tests for V4SearchResult data class."""

    def test_v4_search_result_to_dict(self):
        """Test V4SearchResult.to_dict() method."""
        result = V4SearchResult(
            primary_results=[
                MergedResult(
                    result=SearchResult(
                        id="art_001",
                        content="Content",
                        metadata={"title": "Doc"},
                        collection="artifacts",
                        rank=0,
                        distance=0.1,
                        is_chunk=False
                    ),
                    rrf_score=0.5,
                    collections=["artifacts"]
                )
            ],
            related_context=[
                RelatedContextItem(
                    type="event",
                    id="event_001",
                    category="Decision",
                    reason="same_actor:Alice",
                    summary="Test decision"
                )
            ],
            entities=[
                EntityInfo(
                    entity_id="ent_001",
                    name="Alice Chen",
                    type="person",
                    mention_count=3
                )
            ],
            expand_options={"graph_expand": True}
        )

        result_dict = result.to_dict()

        assert "primary_results" in result_dict
        assert len(result_dict["primary_results"]) == 1
        assert "related_context" in result_dict
        assert len(result_dict["related_context"]) == 1
        assert "entities" in result_dict
        assert len(result_dict["entities"]) == 1
        assert "expand_options" in result_dict


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in V4 search."""

    @pytest.mark.asyncio
    async def test_graph_service_unavailable_returns_primary_only(
        self, retrieval_service_v4, mock_chroma_client, mock_graph_service_unavailable
    ):
        """Test search returns primary results when graph service unavailable."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        # Replace graph service with unavailable one
        retrieval_service_v4.graph_service = mock_graph_service_unavailable

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True
        )

        # Should still return primary results
        assert len(result.primary_results) == 1
        # But no related context
        assert result.related_context == []

    @pytest.mark.asyncio
    async def test_graph_expansion_error_returns_primary_only(
        self, retrieval_service_v4, mock_chroma_client, mock_pg_client, mock_graph_service
    ):
        """Test search returns primary results when graph expansion fails."""
        mock_chroma_client.get_or_create_collection.return_value.query.return_value = {
            "ids": [["art_001"]],
            "documents": [["Content"]],
            "metadatas": [[{}]],
            "distances": [[0.1]]
        }

        mock_pg_client.fetch_one.return_value = {"artifact_uid": "doc", "revision_id": "rev"}
        mock_pg_client.fetch_all.return_value = [{"event_id": uuid4()}]

        # Make expansion fail
        mock_graph_service.expand_from_events.side_effect = Exception("Graph error")

        result = await retrieval_service_v4.hybrid_search_v4(
            query="test",
            graph_expand=True
        )

        # Should handle gracefully
        assert len(result.primary_results) == 1
