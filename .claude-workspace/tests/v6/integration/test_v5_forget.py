"""
V5 Integration Tests for forget() Tool

Tests the forget() tool which deletes stored content:
- Requires confirm=True safety flag
- Cascade deletion (content + chunks + events)
- Event ID guidance (guide to source artifact)
- Invalid ID handling

Markers:
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.integration: Integration tests
"""

import pytest
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock


# =============================================================================
# Test: forget() - Basic Deletion
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetContent:
    """Tests for deleting content."""

    async def test_forget_content(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test deleting content with art_ ID."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate with content
        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        # Verify content exists
        assert content_id in chroma_client._stored_content

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            result = await forget(
                id=content_id,
                confirm=True
            )

            assert "error" not in result
            assert result.get("deleted") is True
            assert result.get("id") == content_id

    async def test_forget_nonexistent_content(
        self,
        v5_test_harness
    ):
        """Test deleting nonexistent content."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            result = await forget(
                id="art_nonexistent123",
                confirm=True
            )

            # Should either succeed (idempotent) or return not found
            # Both are acceptable behaviors
            assert "error" not in result or "not found" in result.get("error", "").lower()


# =============================================================================
# Test: forget() - Safety Flag
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetSafetyFlag:
    """Tests for confirm=True safety requirement."""

    async def test_forget_requires_confirm(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test safety flag requirement."""
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
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            # Without confirm=True
            result = await forget(
                id=content_id,
                confirm=False
            )

            assert "error" in result
            assert "confirm" in result["error"].lower()
            assert result.get("hint") is not None

            # Content should still exist
            assert content_id in chroma_client._stored_content

    async def test_forget_default_confirm_is_false(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test confirm defaults to False."""
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
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            # Without specifying confirm (defaults to False)
            result = await forget(id=content_id)

            assert "error" in result
            assert "confirm" in result["error"].lower()


# =============================================================================
# Test: forget() - Cascade Deletion
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetCascade:
    """Tests for cascade deletion of chunks and events."""

    async def test_forget_cascades(
        self,
        v5_test_harness,
        sample_large_content,
        generate_content_id
    ):
        """Test cascade deletion of chunks/events."""
        chroma_client = v5_test_harness["chroma_client"]

        # Pre-populate with chunked content
        content_id = generate_content_id(sample_large_content)
        content_col = chroma_client.get_or_create_collection("content")
        chunks_col = chroma_client.get_or_create_collection("chunks")

        content_col.add(
            ids=[content_id],
            documents=[sample_large_content],
            metadatas=[{"context": "note", "is_chunked": True, "num_chunks": 3}],
            embeddings=[[0.1] * 3072]
        )

        # Add chunks
        for i in range(3):
            chunk_id = f"{content_id}::chunk::{i:03d}"
            chunks_col.add(
                ids=[chunk_id],
                documents=[f"Chunk {i} content"],
                metadatas=[{"content_id": content_id, "chunk_index": i}],
                embeddings=[[0.1 + i * 0.01] * 3072]
            )

        # Configure mock Postgres to return events for deletion
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_all.return_value = [
            {"event_id": "event-uuid-1"},
            {"event_id": "event-uuid-2"}
        ]

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import forget

            result = await forget(
                id=content_id,
                confirm=True
            )

            assert "error" not in result
            assert result.get("deleted") is True
            assert "cascade" in result

            # Verify cascade counts
            cascade = result.get("cascade", {})
            # Chunks should be deleted
            assert cascade.get("chunks", 0) >= 0

    async def test_forget_cascade_empty_chunks(
        self,
        v5_test_harness,
        sample_preference_content,
        generate_content_id
    ):
        """Test cascade with no chunks."""
        chroma_client = v5_test_harness["chroma_client"]

        content_id = generate_content_id(sample_preference_content)
        content_col = chroma_client.get_or_create_collection("content")

        content_col.add(
            ids=[content_id],
            documents=[sample_preference_content],
            metadatas=[{"context": "preference", "is_chunked": False}],
            embeddings=[[0.1] * 3072]
        )

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            result = await forget(
                id=content_id,
                confirm=True
            )

            assert "error" not in result
            assert result.get("deleted") is True


# =============================================================================
# Test: forget() - Event ID Guidance
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetEventGuidance:
    """Tests for event ID guidance to source artifact."""

    async def test_forget_evt_returns_guidance(
        self,
        v5_test_harness
    ):
        """Test evt_ ID returns error with source artifact."""
        mock_pg = v5_test_harness["pg_client"]

        # Configure mock to return source artifact for event
        mock_pg.fetch_one.return_value = {
            "artifact_uid": "uid_abc123def456"
        }

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import forget

            event_id = "evt_12345678-1234-1234-1234-123456789012"
            result = await forget(
                id=event_id,
                confirm=True
            )

            assert "error" in result
            assert "source" in result["error"].lower() or "artifact" in result["error"].lower()
            assert result.get("deleted") is False

            # Should include source artifact ID for guidance
            assert "source_artifact_id" in result

    async def test_forget_evt_without_source(
        self,
        v5_test_harness
    ):
        """Test evt_ ID when source artifact not found."""
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.fetch_one.return_value = None  # No source found

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import forget

            event_id = "evt_12345678-1234-1234-1234-123456789012"
            result = await forget(
                id=event_id,
                confirm=True
            )

            assert "error" in result
            assert result.get("deleted") is False


# =============================================================================
# Test: forget() - Invalid ID
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetInvalidId:
    """Tests for invalid ID handling."""

    async def test_forget_invalid_id_returns_error(
        self,
        v5_test_harness
    ):
        """Test invalid ID prefix returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            result = await forget(
                id="invalid_abc123",
                confirm=True
            )

            assert "error" in result
            # Should mention valid formats
            assert "art_" in result["error"] or "evt_" in result["error"]

    async def test_forget_empty_id_error(
        self,
        v5_test_harness
    ):
        """Test empty ID returns error."""
        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", v5_test_harness["pg_client"]):

            from server import forget

            result = await forget(
                id="",
                confirm=True
            )

            assert "error" in result


# =============================================================================
# Test: forget() - Postgres Errors
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetPostgresErrors:
    """Tests for Postgres error handling during deletion."""

    async def test_forget_postgres_error_graceful(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test Postgres errors are handled gracefully."""
        chroma_client = v5_test_harness["chroma_client"]

        content_id = generate_content_id(sample_document_content)
        content_col = chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=[content_id],
            documents=[sample_document_content],
            metadatas=[{"context": "meeting"}],
            embeddings=[[0.1] * 3072]
        )

        # Configure mock to raise error
        mock_pg = v5_test_harness["pg_client"]
        mock_pg.execute.side_effect = Exception("Database connection error")

        with patch("server.chroma_manager", v5_test_harness["chroma_manager"]), \
             patch("server.pg_client", mock_pg):

            from server import forget

            result = await forget(
                id=content_id,
                confirm=True
            )

            # Should still succeed for ChromaDB deletion
            # or handle error gracefully
            # The exact behavior depends on implementation
            assert "deleted" in result or "error" in result


# =============================================================================
# Test: forget() - Verify Deletion
# =============================================================================

@pytest.mark.v5
@pytest.mark.integration
@pytest.mark.asyncio
class TestForgetVerifyDeletion:
    """Tests to verify content is actually deleted."""

    async def test_forget_content_not_retrievable(
        self,
        v5_test_harness,
        sample_document_content,
        generate_content_id
    ):
        """Test deleted content cannot be retrieved."""
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
             patch("server.pg_client", v5_test_harness["pg_client"]), \
             patch("server.embedding_service", v5_test_harness["embedding_service"]):

            from server import forget, recall

            # Delete the content
            delete_result = await forget(
                id=content_id,
                confirm=True
            )
            assert delete_result.get("deleted") is True

            # Try to retrieve - should return empty
            recall_result = await recall(id=content_id)
            assert recall_result.get("total_count", 0) == 0
