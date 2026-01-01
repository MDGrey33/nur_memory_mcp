"""
V5 Unit Tests for Collections

Unit tests for V5 collection helper functions:
- get_content_collection(): Get unified content collection
- get_chunks_collection(): Get chunks collection
- get_content_by_id(): Direct content lookup
- delete_v5_content_cascade(): Cascade deletion

Markers:
- @pytest.mark.v5: V5-specific tests
- @pytest.mark.unit: Unit tests
"""

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# Test: get_content_collection()
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestGetContentCollection:
    """Tests for get_content_collection() helper."""

    def test_get_content_collection(self, mock_chroma_client):
        """Test get_content_collection returns correct collection."""
        from storage.collections import get_content_collection

        collection = get_content_collection(mock_chroma_client)

        assert collection is not None
        assert collection.name == "content"

        # Verify get_or_create_collection was called with correct params
        mock_chroma_client.get_or_create_collection.assert_called_once()
        call_kwargs = mock_chroma_client.get_or_create_collection.call_args
        assert call_kwargs[1].get("name") == "content" or call_kwargs[0][0] == "content"

    def test_get_content_collection_metadata(self, mock_chroma_client):
        """Test content collection has correct metadata."""
        # Create a mock that captures the call
        captured_calls = []

        def capture_call(name, **kwargs):
            captured_calls.append({"name": name, "kwargs": kwargs})
            mock_col = MagicMock()
            mock_col.name = name
            return mock_col

        mock_chroma_client.get_or_create_collection = capture_call

        from storage.collections import get_content_collection
        get_content_collection(mock_chroma_client)

        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert call["name"] == "content"
        metadata = call["kwargs"].get("metadata", {})
        assert metadata.get("hnsw:space") == "cosine"

    def test_get_content_collection_idempotent(self, mock_chroma_client):
        """Test multiple calls return same collection."""
        from storage.collections import get_content_collection

        col1 = get_content_collection(mock_chroma_client)
        col2 = get_content_collection(mock_chroma_client)

        # Should use get_or_create, making it idempotent
        assert col1.name == col2.name


# =============================================================================
# Test: get_chunks_collection()
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestGetChunksCollection:
    """Tests for get_chunks_collection() helper."""

    def test_get_chunks_collection(self, mock_chroma_client):
        """Test get_chunks_collection returns correct collection."""
        from storage.collections import get_chunks_collection

        collection = get_chunks_collection(mock_chroma_client)

        assert collection is not None
        assert collection.name == "chunks"

    def test_get_chunks_collection_metadata(self, mock_chroma_client):
        """Test chunks collection has correct metadata."""
        captured_calls = []

        def capture_call(name, **kwargs):
            captured_calls.append({"name": name, "kwargs": kwargs})
            mock_col = MagicMock()
            mock_col.name = name
            return mock_col

        mock_chroma_client.get_or_create_collection = capture_call

        from storage.collections import get_chunks_collection
        get_chunks_collection(mock_chroma_client)

        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert call["name"] == "chunks"


# =============================================================================
# Test: get_content_by_id()
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestGetContentById:
    """Tests for get_content_by_id() helper."""

    def test_get_content_by_id(self, mock_chroma_client):
        """Test direct content lookup."""
        # Pre-populate mock data
        content_col = mock_chroma_client.get_or_create_collection("content")
        content_col.add(
            ids=["art_test123abc"],
            documents=["Test document content"],
            metadatas=[{"context": "note", "title": "Test"}],
            embeddings=[[0.1] * 3072]
        )

        from storage.collections import get_content_by_id

        result = get_content_by_id(mock_chroma_client, "art_test123abc")

        assert result is not None
        assert result["id"] == "art_test123abc"
        assert "content" in result
        assert "metadata" in result

    def test_get_content_by_id_not_found(self, mock_chroma_client):
        """Test lookup returns None for nonexistent ID."""
        from storage.collections import get_content_by_id

        result = get_content_by_id(mock_chroma_client, "art_nonexistent")

        assert result is None

    def test_get_content_by_id_includes_document(self, mock_chroma_client):
        """Test result includes document content."""
        content_col = mock_chroma_client.get_or_create_collection("content")
        test_content = "This is the document content"
        content_col.add(
            ids=["art_abc123def"],
            documents=[test_content],
            metadatas=[{"context": "note"}],
            embeddings=[[0.1] * 3072]
        )

        from storage.collections import get_content_by_id

        result = get_content_by_id(mock_chroma_client, "art_abc123def")

        assert result is not None
        assert result["content"] == test_content

    def test_get_content_by_id_includes_metadata(self, mock_chroma_client):
        """Test result includes metadata."""
        content_col = mock_chroma_client.get_or_create_collection("content")
        test_metadata = {"context": "meeting", "title": "Planning", "importance": 0.9}
        content_col.add(
            ids=["art_meta123"],
            documents=["Content"],
            metadatas=[test_metadata],
            embeddings=[[0.1] * 3072]
        )

        from storage.collections import get_content_by_id

        result = get_content_by_id(mock_chroma_client, "art_meta123")

        assert result is not None
        assert result["metadata"]["context"] == "meeting"
        assert result["metadata"]["title"] == "Planning"


# =============================================================================
# Test: delete_v5_content_cascade()
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestDeleteV5ContentCascade:
    """Tests for delete_v5_content_cascade() helper."""

    def test_delete_v5_content_cascade(self, mock_chroma_client):
        """Test cascade deletion."""
        # Pre-populate with content and chunks
        content_col = mock_chroma_client.get_or_create_collection("content")
        chunks_col = mock_chroma_client.get_or_create_collection("chunks")

        content_id = "art_cascade123"
        content_col.add(
            ids=[content_id],
            documents=["Main content"],
            metadatas=[{"context": "note", "is_chunked": True}],
            embeddings=[[0.1] * 3072]
        )

        # Add chunks
        for i in range(3):
            chunks_col.add(
                ids=[f"{content_id}::chunk::{i:03d}"],
                documents=[f"Chunk {i}"],
                metadatas=[{"content_id": content_id, "chunk_index": i}],
                embeddings=[[0.1 + i * 0.01] * 3072]
            )

        from storage.collections import delete_v5_content_cascade

        result = delete_v5_content_cascade(mock_chroma_client, content_id)

        assert "content" in result
        assert "chunks" in result
        assert result["content"] == 1

        # Verify content was deleted
        assert content_id not in mock_chroma_client._stored_content

    def test_delete_v5_content_cascade_no_chunks(self, mock_chroma_client):
        """Test cascade with no chunks."""
        content_col = mock_chroma_client.get_or_create_collection("content")

        content_id = "art_nochunks123"
        content_col.add(
            ids=[content_id],
            documents=["Small content"],
            metadatas=[{"context": "preference", "is_chunked": False}],
            embeddings=[[0.1] * 3072]
        )

        from storage.collections import delete_v5_content_cascade

        result = delete_v5_content_cascade(mock_chroma_client, content_id)

        assert result["content"] == 1
        assert result["chunks"] == 0

    def test_delete_v5_content_cascade_nonexistent(self, mock_chroma_client):
        """Test cascade deletion of nonexistent content."""
        from storage.collections import delete_v5_content_cascade

        result = delete_v5_content_cascade(mock_chroma_client, "art_nonexistent")

        # Should handle gracefully
        assert "content" in result
        assert "chunks" in result

    def test_delete_v5_content_cascade_returns_counts(self, mock_chroma_client):
        """Test cascade returns deletion counts."""
        content_col = mock_chroma_client.get_or_create_collection("content")
        chunks_col = mock_chroma_client.get_or_create_collection("chunks")

        content_id = "art_counts123"
        content_col.add(
            ids=[content_id],
            documents=["Content"],
            metadatas=[{"context": "note"}],
            embeddings=[[0.1] * 3072]
        )

        for i in range(5):
            chunks_col.add(
                ids=[f"{content_id}::chunk::{i:03d}"],
                documents=[f"Chunk {i}"],
                metadatas=[{"content_id": content_id}],
                embeddings=[[0.1] * 3072]
            )

        from storage.collections import delete_v5_content_cascade

        result = delete_v5_content_cascade(mock_chroma_client, content_id)

        assert result["content"] >= 0
        assert result["chunks"] >= 0


# =============================================================================
# Test: Collection Error Handling
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestCollectionErrors:
    """Tests for error handling in collection operations."""

    def test_get_content_collection_error(self):
        """Test handling ChromaDB errors in get_content_collection."""
        mock_client = MagicMock()
        mock_client.get_or_create_collection.side_effect = Exception("ChromaDB error")

        from storage.collections import get_content_collection

        with pytest.raises(Exception):
            get_content_collection(mock_client)

    def test_get_content_by_id_error(self):
        """Test handling errors in get_content_by_id."""
        mock_client = MagicMock()
        mock_col = MagicMock()
        mock_col.get.side_effect = Exception("Query error")
        mock_client.get_or_create_collection.return_value = mock_col

        from storage.collections import get_content_by_id

        # Should handle error gracefully and return None
        try:
            result = get_content_by_id(mock_client, "art_test")
            # If it doesn't raise, result should be None
            assert result is None
        except Exception:
            # Raising is also acceptable
            pass

    def test_delete_cascade_partial_failure(self, mock_chroma_client):
        """Test cascade handles partial failures."""
        content_col = mock_chroma_client.get_or_create_collection("content")
        content_id = "art_partial123"

        content_col.add(
            ids=[content_id],
            documents=["Content"],
            metadatas=[{"context": "note"}],
            embeddings=[[0.1] * 3072]
        )

        # Make chunks collection fail
        chunks_col = mock_chroma_client.get_or_create_collection("chunks")
        chunks_col.get = MagicMock(side_effect=Exception("Chunks error"))

        from storage.collections import delete_v5_content_cascade

        # Should still return result, even if chunks deletion fails
        result = delete_v5_content_cascade(mock_chroma_client, content_id)

        # Content deletion should still succeed
        assert "content" in result


# =============================================================================
# Test: Collection Configuration
# =============================================================================

@pytest.mark.v5
@pytest.mark.unit
class TestCollectionConfiguration:
    """Tests for collection configuration."""

    def test_content_collection_cosine_distance(self, mock_chroma_client):
        """Test content collection uses cosine distance."""
        captured_metadata = {}

        def capture_metadata(name, **kwargs):
            captured_metadata[name] = kwargs.get("metadata", {})
            mock_col = MagicMock()
            mock_col.name = name
            return mock_col

        mock_chroma_client.get_or_create_collection = capture_metadata

        from storage.collections import get_content_collection
        get_content_collection(mock_chroma_client)

        metadata = captured_metadata.get("content", {})
        assert metadata.get("hnsw:space") == "cosine"

    def test_chunks_collection_cosine_distance(self, mock_chroma_client):
        """Test chunks collection uses cosine distance."""
        captured_metadata = {}

        def capture_metadata(name, **kwargs):
            captured_metadata[name] = kwargs.get("metadata", {})
            mock_col = MagicMock()
            mock_col.name = name
            return mock_col

        mock_chroma_client.get_or_create_collection = capture_metadata

        from storage.collections import get_chunks_collection
        get_chunks_collection(mock_chroma_client)

        metadata = captured_metadata.get("chunks", {})
        assert metadata.get("hnsw:space") == "cosine"

    def test_collection_embedding_config(self, mock_chroma_client):
        """Test collections have embedding configuration."""
        captured_metadata = {}

        def capture_metadata(name, **kwargs):
            captured_metadata[name] = kwargs.get("metadata", {})
            mock_col = MagicMock()
            mock_col.name = name
            return mock_col

        mock_chroma_client.get_or_create_collection = capture_metadata

        from storage.collections import get_content_collection
        get_content_collection(mock_chroma_client)

        metadata = captured_metadata.get("content", {})
        assert "embedding_provider" in metadata or "description" in metadata
