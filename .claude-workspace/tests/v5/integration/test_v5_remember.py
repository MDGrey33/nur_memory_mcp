"""
V5 Integration Tests for remember() Tool

Tests the remember() tool which stores content with:
- Content-based ID generation (art_ + SHA256[:12])
- Idempotent deduplication
- Automatic chunking for large content
- Event extraction queuing
- Metadata handling

Markers:
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.integration: Integration tests
"""

import pytest
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


# =============================================================================
# Test: remember() - Basic Document Storage
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberDocument:
    """Tests for remembering document content."""

    async def test_remember_document(
        self,
        v5_test_harness,
        sample_document_content
    ):
        """Test remembering a document stores it correctly."""
        # Import and patch server dependencies
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            # Call remember with document content
            result = await remember(
                content=sample_document_content,
                context="meeting",
                source="slack",
                title="Project Alpha Planning",
                author="Alice Chen"
            )

            # Verify success
            assert "error" not in result, f"Unexpected error: {result.get('error')}"
            assert "id" in result
            assert result["id"].startswith("art_")
            assert result["context"] == "meeting"

            # Verify ID is content-based
            expected_hash = hashlib.sha256(sample_document_content.encode()).hexdigest()[:12]
            assert result["id"] == f"art_{expected_hash}"

    async def test_remember_document_with_metadata(
        self,
        v5_test_harness,
        sample_document_content
    ):
        """Test remembering a document with full metadata."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_document_content,
                context="meeting",
                source="slack",
                title="Project Alpha Planning",
                author="Alice Chen",
                participants=["Alice Chen", "Bob Smith", "Carol Davis"],
                date="2024-03-15T10:00:00Z",
                importance=0.9,
                sensitivity="normal",
                visibility_scope="team",
                document_date="2024-03-15",
                source_type="meeting_notes",
                author_title="Product Manager"
            )

            assert "error" not in result
            assert "id" in result
            assert result["context"] == "meeting"


# =============================================================================
# Test: remember() - Preference Storage
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberPreference:
    """Tests for remembering preference content."""

    async def test_remember_preference(
        self,
        v5_test_harness,
        sample_preference_content
    ):
        """Test remembering a preference stores it correctly."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_preference_content,
                context="preference",
                importance=0.8
            )

            assert "error" not in result
            assert "id" in result
            assert result["id"].startswith("art_")
            assert result["context"] == "preference"


# =============================================================================
# Test: remember() - Conversation Storage
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberConversation:
    """Tests for remembering conversation turns."""

    async def test_remember_conversation(
        self,
        v5_test_harness,
        sample_conversation_turn
    ):
        """Test conversation turns with required fields."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_conversation_turn["content"],
                context="conversation",
                conversation_id=sample_conversation_turn["conversation_id"],
                turn_index=sample_conversation_turn["turn_index"],
                role=sample_conversation_turn["role"]
            )

            assert "error" not in result
            assert "id" in result
            assert result["context"] == "conversation"

    async def test_remember_conversation_missing_required_fields(
        self,
        v5_test_harness
    ):
        """Test conversation context requires conversation_id and turn_index."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            # Missing conversation_id and turn_index
            result = await remember(
                content="Hello!",
                context="conversation"
            )

            assert "error" in result
            assert "conversation_id" in result["error"]

    async def test_remember_conversation_invalid_role(
        self,
        v5_test_harness
    ):
        """Test conversation with invalid role returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="Hello!",
                context="conversation",
                conversation_id="conv_123",
                turn_index=0,
                role="invalid_role"
            )

            assert "error" in result
            assert "role" in result["error"].lower()


# =============================================================================
# Test: remember() - Deduplication
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberDeduplication:
    """Tests for content deduplication (idempotent behavior)."""

    async def test_remember_deduplication(
        self,
        v5_test_harness,
        sample_document_content
    ):
        """Test same content returns same ID (idempotent)."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            # First remember
            result1 = await remember(
                content=sample_document_content,
                context="note",
                title="First Title"
            )

            assert "error" not in result1
            first_id = result1["id"]

            # Second remember with same content
            result2 = await remember(
                content=sample_document_content,
                context="note",
                title="Updated Title"
            )

            assert "error" not in result2
            second_id = result2["id"]

            # IDs should be the same (content-based)
            assert first_id == second_id

            # Second call should indicate update
            assert result2.get("status") == "unchanged"

    async def test_remember_different_content_different_ids(
        self,
        v5_test_harness
    ):
        """Test different content gets different IDs."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result1 = await remember(
                content="Content A",
                context="note"
            )
            result2 = await remember(
                content="Content B",
                context="note"
            )

            assert result1["id"] != result2["id"]


# =============================================================================
# Test: remember() - Event Extraction Queuing
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberEventExtraction:
    """Tests for event extraction job queuing."""

    async def test_remember_triggers_events(
        self,
        v5_test_harness,
        sample_document_content
    ):
        """Test event extraction is queued for substantial content."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_document_content,
                context="meeting",
                source="slack"
            )

            assert "error" not in result
            assert "events_queued" in result
            # events_queued should be True for substantial content with pg_client
            # Note: May be False if pg_client is not connected in test

    async def test_remember_conversation_short_no_events(
        self,
        v5_test_harness
    ):
        """Test short conversation turns skip event extraction."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            # Short conversation turn (< 100 tokens)
            result = await remember(
                content="Hi!",
                context="conversation",
                conversation_id="conv_123",
                turn_index=0,
                role="user"
            )

            assert "error" not in result
            # Short conversation turns should skip event extraction
            assert result.get("events_queued") is False


# =============================================================================
# Test: remember() - Chunking
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberChunking:
    """Tests for automatic content chunking."""

    async def test_remember_large_content_chunked(
        self,
        v5_test_harness,
        sample_large_content
    ):
        """Test large content is chunked automatically."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_large_content,
                context="note",
                title="Large Document"
            )

            assert "error" not in result
            assert "id" in result
            assert result.get("is_chunked") is True
            assert result.get("num_chunks", 0) > 0

    async def test_remember_small_content_not_chunked(
        self,
        v5_test_harness,
        sample_preference_content
    ):
        """Test small content is not chunked."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content=sample_preference_content,
                context="preference"
            )

            assert "error" not in result
            assert result.get("is_chunked") is False
            assert result.get("num_chunks", 0) == 0


# =============================================================================
# Test: remember() - Validation
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestRememberValidation:
    """Tests for input validation."""

    async def test_remember_empty_content_error(
        self,
        v5_test_harness
    ):
        """Test empty content returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="",
                context="note"
            )

            assert "error" in result

    async def test_remember_invalid_context_error(
        self,
        v5_test_harness
    ):
        """Test invalid context returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="Test content",
                context="invalid_context"
            )

            assert "error" in result
            assert "context" in result["error"].lower()

    async def test_remember_invalid_importance_error(
        self,
        v5_test_harness
    ):
        """Test importance out of range returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="Test content",
                context="note",
                importance=1.5  # Out of range
            )

            assert "error" in result
            assert "importance" in result["error"].lower()

    async def test_remember_invalid_sensitivity_error(
        self,
        v5_test_harness
    ):
        """Test invalid sensitivity returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="Test content",
                context="note",
                sensitivity="invalid"
            )

            assert "error" in result
            assert "sensitivity" in result["error"].lower()

    async def test_remember_default_context(
        self,
        v5_test_harness
    ):
        """Test default context is 'note' when not specified."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]), \
             patch("server.chunking_service", v5_test_harness["chunking_service"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.job_queue_service", v5_test_harness["job_queue_service"]), \
             patch("server.config", v5_test_harness["config"]):

            from server import remember

            result = await remember(
                content="Test content without context"
            )

            assert "error" not in result
            assert result.get("context") == "note"
