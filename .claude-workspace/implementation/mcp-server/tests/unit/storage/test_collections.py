"""Unit tests for ChromaDB collection operations."""

import pytest
from unittest.mock import MagicMock, Mock
from storage.collections import (
    get_memory_collection,
    get_history_collection,
    get_artifacts_collection,
    get_artifact_chunks_collection,
    get_chunks_by_artifact,
    get_artifact_by_source,
    delete_artifact_cascade
)


# ============================================================================
# Collection Getter Tests
# ============================================================================

def test_get_memory_collection(mock_chroma_client):
    """Test get_memory_collection returns correct collection."""
    collection = get_memory_collection(mock_chroma_client)

    assert collection is not None
    mock_chroma_client.get_or_create_collection.assert_called_once()
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "memory"


def test_get_history_collection(mock_chroma_client):
    """Test get_history_collection returns correct collection."""
    collection = get_history_collection(mock_chroma_client)

    assert collection is not None
    mock_chroma_client.get_or_create_collection.assert_called_once()
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "history"


def test_get_artifacts_collection(mock_chroma_client):
    """Test get_artifacts_collection returns correct collection."""
    collection = get_artifacts_collection(mock_chroma_client)

    assert collection is not None
    mock_chroma_client.get_or_create_collection.assert_called_once()
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "artifacts"


def test_get_artifact_chunks_collection(mock_chroma_client):
    """Test get_artifact_chunks_collection returns correct collection."""
    collection = get_artifact_chunks_collection(mock_chroma_client)

    assert collection is not None
    mock_chroma_client.get_or_create_collection.assert_called_once()
    call_args = mock_chroma_client.get_or_create_collection.call_args
    assert call_args[1]["name"] == "artifact_chunks"


# ============================================================================
# Get Chunks by Artifact Tests
# ============================================================================

def test_get_chunks_by_artifact_success(mock_chroma_client):
    """Test get_chunks_by_artifact returns sorted chunks."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.return_value = {
        "ids": [
            "art_001::chunk::002::ghi",
            "art_001::chunk::000::abc",
            "art_001::chunk::001::def"
        ],
        "documents": ["Chunk 2", "Chunk 0", "Chunk 1"],
        "metadatas": [
            {"chunk_index": 2, "artifact_id": "art_001"},
            {"chunk_index": 0, "artifact_id": "art_001"},
            {"chunk_index": 1, "artifact_id": "art_001"}
        ]
    }

    chunks = get_chunks_by_artifact(mock_chroma_client, "art_001")

    assert len(chunks) == 3
    # Should be sorted by chunk_index
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[1]["metadata"]["chunk_index"] == 1
    assert chunks[2]["metadata"]["chunk_index"] == 2

    # Verify query was made with correct filter
    mock_collection.get.assert_called_once()
    call_kwargs = mock_collection.get.call_args[1]
    assert call_kwargs["where"] == {"artifact_id": "art_001"}


def test_get_chunks_by_artifact_not_found(mock_chroma_client):
    """Test get_chunks_by_artifact returns empty list if not found."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.return_value = {
        "ids": []
    }

    chunks = get_chunks_by_artifact(mock_chroma_client, "art_999")

    assert chunks == []


def test_get_chunks_by_artifact_error(mock_chroma_client):
    """Test get_chunks_by_artifact handles errors gracefully."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.side_effect = Exception("DB error")

    chunks = get_chunks_by_artifact(mock_chroma_client, "art_001")

    # Should return empty list on error
    assert chunks == []


# ============================================================================
# Get Artifact by Source Tests
# ============================================================================

def test_get_artifact_by_source_found(mock_chroma_client):
    """Test get_artifact_by_source returns artifact when found."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.return_value = {
        "ids": ["art_abc123"],
        "documents": ["Artifact content"],
        "metadatas": [{"source_system": "gmail", "source_id": "msg123"}]
    }

    artifact = get_artifact_by_source(mock_chroma_client, "gmail", "msg123")

    assert artifact is not None
    assert artifact["artifact_id"] == "art_abc123"
    assert artifact["content"] == "Artifact content"
    assert artifact["metadata"]["source_system"] == "gmail"

    # Verify query with correct filters
    mock_collection.get.assert_called_once()
    call_kwargs = mock_collection.get.call_args[1]
    assert call_kwargs["where"]["$and"][0] == {"source_system": "gmail"}
    assert call_kwargs["where"]["$and"][1] == {"source_id": "msg123"}


def test_get_artifact_by_source_not_found(mock_chroma_client):
    """Test get_artifact_by_source returns None if not found."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.return_value = {
        "ids": []
    }

    artifact = get_artifact_by_source(mock_chroma_client, "gmail", "msg999")

    assert artifact is None


def test_get_artifact_by_source_error(mock_chroma_client):
    """Test get_artifact_by_source handles errors gracefully."""
    mock_collection = mock_chroma_client.get_or_create_collection.return_value
    mock_collection.get.side_effect = Exception("DB error")

    artifact = get_artifact_by_source(mock_chroma_client, "gmail", "msg123")

    # Should return None on error
    assert artifact is None


# ============================================================================
# Delete Artifact Cascade Tests
# ============================================================================

def test_delete_artifact_cascade_unchunked(mock_chroma_client):
    """Test delete_artifact_cascade for unchunked artifact."""
    mock_artifacts_collection = MagicMock()
    mock_chunks_collection = MagicMock()

    mock_chunks_collection.get.return_value = {"ids": []}  # No chunks

    def get_collection(name, metadata=None, **kwargs):
        if name == "artifacts":
            return mock_artifacts_collection
        elif name == "artifact_chunks":
            return mock_chunks_collection
        return MagicMock()

    mock_chroma_client.get_or_create_collection.side_effect = get_collection

    deleted_count = delete_artifact_cascade(mock_chroma_client, "art_001")

    # Should delete only artifact (no chunks)
    assert deleted_count == 1
    mock_artifacts_collection.delete.assert_called_once_with(ids=["art_001"])
    mock_chunks_collection.get.assert_called_once()


def test_delete_artifact_cascade_with_chunks(mock_chroma_client):
    """Test delete_artifact_cascade for chunked artifact."""
    mock_artifacts_collection = MagicMock()
    mock_chunks_collection = MagicMock()

    mock_chunks_collection.get.return_value = {
        "ids": [
            "art_001::chunk::000::abc",
            "art_001::chunk::001::def",
            "art_001::chunk::002::ghi"
        ]
    }

    def get_collection(name, metadata=None, **kwargs):
        if name == "artifacts":
            return mock_artifacts_collection
        elif name == "artifact_chunks":
            return mock_chunks_collection
        return MagicMock()

    mock_chroma_client.get_or_create_collection.side_effect = get_collection

    deleted_count = delete_artifact_cascade(mock_chroma_client, "art_001")

    # Should delete artifact + 3 chunks = 4 total
    assert deleted_count == 4
    mock_artifacts_collection.delete.assert_called_once_with(ids=["art_001"])
    mock_chunks_collection.delete.assert_called_once()


def test_delete_artifact_cascade_artifact_error(mock_chroma_client):
    """Test delete_artifact_cascade handles artifact deletion error."""
    mock_artifacts_collection = MagicMock()
    mock_artifacts_collection.delete.side_effect = Exception("Delete failed")

    mock_chunks_collection = MagicMock()
    mock_chunks_collection.get.return_value = {"ids": []}

    def get_collection(name, metadata=None, **kwargs):
        if name == "artifacts":
            return mock_artifacts_collection
        elif name == "artifact_chunks":
            return mock_chunks_collection
        return MagicMock()

    mock_chroma_client.get_or_create_collection.side_effect = get_collection

    deleted_count = delete_artifact_cascade(mock_chroma_client, "art_001")

    # Should return 0 if artifact deletion fails
    assert deleted_count == 0


def test_delete_artifact_cascade_chunks_error(mock_chroma_client):
    """Test delete_artifact_cascade handles chunk deletion error."""
    mock_artifacts_collection = MagicMock()

    mock_chunks_collection = MagicMock()
    mock_chunks_collection.get.side_effect = Exception("Query failed")

    def get_collection(name, metadata=None, **kwargs):
        if name == "artifacts":
            return mock_artifacts_collection
        elif name == "artifact_chunks":
            return mock_chunks_collection
        return MagicMock()

    mock_chroma_client.get_or_create_collection.side_effect = get_collection

    deleted_count = delete_artifact_cascade(mock_chroma_client, "art_001")

    # Should still delete artifact even if chunk deletion fails
    assert deleted_count == 1
    mock_artifacts_collection.delete.assert_called_once()
