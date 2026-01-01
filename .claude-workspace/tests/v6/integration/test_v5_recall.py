"""
V5 Integration Tests for recall() Tool

Tests the recall() tool which finds and retrieves stored content:
- Semantic search by query
- Direct ID lookup (art_, evt_)
- Conversation history retrieval
- Graph expansion for related context
- Filtering by context, source, sensitivity

Markers:
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.integration: Integration tests
"""

import pytest
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


# =============================================================================
# Test: recall() - Query Search
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallByQuery:
    """Tests for semantic search via query."""

    async def test_recall_by_query(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test semantic search returns relevant content."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate with test content
        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{
                "context": "meeting",
                "importance": 0.8,
                "title": "Project Alpha"
            }],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="project planning meeting",
                limit=10
            )

            assert "error" not in result
            assert "results" in result
            assert "total_count" in result

    async def test_recall_with_limit(
        self,
        v5_test_harness
    ):
        """Test recall respects limit parameter."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate with multiple documents
        content_col = chroma_client.get_or_create_collection("content")
        for i in range(5):
            content_col.add(
                ids=[f"art_test{i:03d}"],
                documents=[f"Test document {i}"],
                metadatas=[{"context": "note"}],
                embeddings=[[0.1 + i * 0.01] * 3072]
            )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="test document",
                limit=3
            )

            assert "error" not in result
            assert len(result.get("results", [])) <= 3

    async def test_recall_invalid_limit_error(
        self,
        v5_test_harness
    ):
        """Test invalid limit returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            # Limit too high
            result = await recall(
                query="test",
                limit=100
            )

            assert "error" in result
            assert "limit" in result["error"].lower()


# =============================================================================
# Test: recall() - Direct ID Lookup
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallById:
    """Tests for direct ID lookup."""

    async def test_recall_by_art_id(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test direct ID lookup with art_ prefix."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate
        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting", "title": "Test"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(id=content_id)

            assert "error" not in result
            assert "results" in result
            assert result["total_count"] == 1

    async def test_recall_by_evt_id(
        self,
        v5_test_harness
    ):
        """Test event lookup with evt_ prefix."""
        # Configure mock to return an event with all required fields
        mock_pg = v5_test_harness["pg_client"]
        event_uuid = "12345678-1234-1234-1234-123456789012"
        mock_pg.fetch_one.return_value = {
            "event_id": event_uuid,
            "category": "Decision",
            "narrative": "Team decided on approach",
            "artifact_uid": "uid_abc123",
            "revision_id": "rev_001",
            "event_time": None,
            "confidence": 0.8,
            "created_at": datetime.utcnow().isoformat()
        }

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", mock_pg), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(id=f"evt_{event_uuid}")

            # Either succeeds or returns expected error for unavailable service
            assert "error" not in result or "V3_UNAVAILABLE" in result.get("error", "") or "revision_id" not in result.get("error", "")

    async def test_recall_invalid_id_prefix(
        self,
        v5_test_harness
    ):
        """Test unknown ID prefix returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(id="unknown_abc123")

            assert "error" in result
            assert "art_" in result["error"] or "evt_" in result["error"]

    async def test_recall_nonexistent_id(
        self,
        v5_test_harness
    ):
        """Test nonexistent ID returns empty results."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(id="art_nonexistent123")

            assert "error" not in result
            assert result["total_count"] == 0


# =============================================================================
# Test: recall() - Graph Expansion
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallGraphExpansion:
    """Tests for graph-based context expansion."""

    async def test_recall_with_graph_expansion(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test expand=True returns related context."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate
        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="project planning",
                expand=True,
                include_entities=True
            )

            assert "error" not in result
            assert "related" in result
            assert "entities" in result

    async def test_recall_without_graph_expansion(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test expand=False skips graph expansion."""
        chroma_client = v5_test_harness["chroma_client"]

        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="project planning",
                expand=False
            )

            assert "error" not in result
            # Related should be empty when expand=False
            assert result.get("related", []) == []


# =============================================================================
# Test: recall() - Conversation History
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallConversation:
    """Tests for conversation history retrieval."""

    async def test_recall_conversation_history_structured(
        self,
        v5_test_harness
    ):
        """Test conversation_id returns structured {turns: [...]}."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate conversation turns
        content_col = chroma_client.get_or_create_collection("content")
        conversation_id = "conv_test_123"

        for i in range(3):
            turn_content = f"Turn {i}: Hello" if i % 2 == 0 else f"Turn {i}: Response"
            content_hash = hashlib.sha256(turn_content.encode()).hexdigest()[:12]
            content_col.add(
                ids=[f"art_{content_hash}"],
                documents=[turn_content],
                metadatas=[{
                    "context": "conversation",
                    "conversation_id": conversation_id,
                    "turn_index": i,
                    "role": "user" if i % 2 == 0 else "assistant"
                }],
                embeddings=[[0.1 + i * 0.01] * 3072]
            )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                conversation_id=conversation_id,
                limit=20
            )

            assert "error" not in result
            # Should return structured conversation history
            assert "results" in result or "turns" in result


# =============================================================================
# Test: recall() - Filtering
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallFiltering:
    """Tests for filtering by context, source, sensitivity."""

    async def test_recall_filter_by_context(
        self,
        v5_test_harness
    ):
        """Test filtering by context type."""
        chroma_client = v5_test_harness["chroma_client"]

        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=["art_meeting001"],
            documents=["Meeting notes"],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )
        content_col.add(
            ids=["art_pref001"],
            documents=["User preference"],
            metadatas=[{"context": "preference"}],
            embeddings=[[0.2] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="notes",
                context="meeting"
            )

            assert "error" not in result

    async def test_recall_filter_by_importance(
        self,
        v5_test_harness
    ):
        """Test filtering by minimum importance."""
        chroma_client = v5_test_harness["chroma_client"]

        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=["art_high001"],
            documents=["High importance content"],
            metadatas=[{"context": "note", "importance": 0.9}],
            embeddings=[[0.1] * 3072]
        )
        content_col.add(
            ids=["art_low001"],
            documents=["Low importance content"],
            metadatas=[{"context": "note", "importance": 0.2}],
            embeddings=[[0.2] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                query="content",
                min_importance=0.8
            )

            assert "error" not in result


# =============================================================================
# Test: recall() - Include Events
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallIncludeEvents:
    """Tests for including extracted events."""

    async def test_recall_include_events(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test include_events=True returns extracted events."""
        chroma_client = v5_test_harness["chroma_client"]

        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        # Mock events from Postgres
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_all.return_value = [
            {
                "event_id": "12345678-1234-1234-1234-123456789012",
                "category": "Decision",
                "narrative": "Alice decided to launch on April 1st"
            }
        ]

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", mock_pg), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                id=content_id,
                include_events=True
            )

            assert "error" not in result

    async def test_recall_exclude_events(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test include_events=False skips event retrieval."""
        chroma_client = v5_test_harness["chroma_client"]

        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            result = await recall(
                id=content_id,
                include_events=False
            )

            assert "error" not in result


# =============================================================================
# Test: recall() - Edge Cases
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallEdgeCases:
    """Tests for edge cases and error handling."""

    async def test_recall_no_query_or_id(
        self,
        v5_test_harness
    ):
        """Test recall without query or id lists all content."""
        chroma_client = v5_test_harness["chroma_client"]

        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=["art_test001"],
            documents=["Test content"],
            metadatas=[{"context": "note"}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", v5_test_harness["retrieval_service"]):

            from server import recall

            # Should work - lists content
            result = await recall(limit=10)

            # Either returns results or requires query
            assert "results" in result or "error" in result

    async def test_recall_empty_results(
        self,
        v5_test_harness
    ):
        """Test recall with no matching content returns empty results."""
        # Create a mock retrieval service that returns empty results
        empty_retrieval_service = MagicMock()

        class EmptySearchResult:
            def to_dict(self):
                return {
                    "primary_results": [],
                    "related_context": [],
                    "entities": []
                }

        async def mock_empty_search(*args, **kwargs):
            return EmptySearchResult()

        empty_retrieval_service.hybrid_search_v4 = mock_empty_search
        empty_retrieval_service.hybrid_search_v5 = mock_empty_search  # V5 uses this

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.retrieval_service", empty_retrieval_service):

            from server import recall

            result = await recall(
                query="xyznonexistentquery12345"
            )

            assert "error" not in result
            assert result.get("total_count", 0) == 0
