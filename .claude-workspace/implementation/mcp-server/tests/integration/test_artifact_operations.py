"""Integration tests for artifact get and delete operations."""

import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.fixture
def mock_artifact_services():
    """Mock services for artifact operations."""
    with patch("server.chroma_manager") as mock_chroma:
        mock_client = MagicMock()
        mock_artifacts_collection = MagicMock()
        mock_chunks_collection = MagicMock()

        def get_collection(name, metadata=None):
            if name == "artifacts":
                return mock_artifacts_collection
            elif name == "artifact_chunks":
                return mock_chunks_collection
            return MagicMock()

        mock_client.get_or_create_collection.side_effect = get_collection
        mock_chroma.get_client.return_value = mock_client

        yield {
            "chroma": mock_chroma,
            "client": mock_client,
            "artifacts": mock_artifacts_collection,
            "chunks": mock_chunks_collection
        }


@pytest.mark.integration
def test_artifact_get_unchunked(mock_artifact_services):
    """Test retrieving unchunked artifact."""
    from server import artifact_get

    # Mock unchunked artifact
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": ["art_001"],
        "documents": ["This is the full artifact content."],
        "metadatas": [{
            "artifact_type": "doc",
            "title": "Test Doc",
            "is_chunked": False,
            "num_chunks": 0
        }]
    }

    result = artifact_get(artifact_id="art_001", include_content=True)

    assert "error" not in result
    assert result["artifact_id"] == "art_001"
    assert result["content"] == "This is the full artifact content."
    assert result["metadata"]["is_chunked"] is False


@pytest.mark.integration
def test_artifact_get_chunked_reconstructed(mock_artifact_services):
    """Test retrieving chunked artifact with content reconstruction."""
    from server import artifact_get

    # Mock chunked artifact metadata
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": ["art_002"],
        "documents": [""],
        "metadatas": [{
            "artifact_type": "doc",
            "title": "Large Doc",
            "is_chunked": True,
            "num_chunks": 3
        }]
    }

    # Mock chunks
    with patch("server.get_chunks_by_artifact") as mock_get_chunks:
        mock_get_chunks.return_value = [
            {
                "chunk_id": "art_002::chunk::000::abc",
                "content": "First chunk content. ",
                "metadata": {"chunk_index": 0}
            },
            {
                "chunk_id": "art_002::chunk::001::def",
                "content": "Second chunk content. ",
                "metadata": {"chunk_index": 1}
            },
            {
                "chunk_id": "art_002::chunk::002::ghi",
                "content": "Third chunk content.",
                "metadata": {"chunk_index": 2}
            }
        ]

        result = artifact_get(artifact_id="art_002", include_content=True)

    assert "error" not in result
    assert result["artifact_id"] == "art_002"
    assert result["metadata"]["is_chunked"] is True
    # Content should be reconstructed from chunks
    assert "First chunk" in result["content"]
    assert "Second chunk" in result["content"]
    assert "Third chunk" in result["content"]


@pytest.mark.integration
def test_artifact_get_with_chunk_list(mock_artifact_services):
    """Test retrieving artifact with chunk list."""
    from server import artifact_get

    # Mock chunked artifact
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": ["art_003"],
        "documents": [""],
        "metadatas": [{
            "artifact_type": "doc",
            "title": "Chunked Doc",
            "is_chunked": True,
            "num_chunks": 2
        }]
    }

    # Mock chunks
    with patch("server.get_chunks_by_artifact") as mock_get_chunks:
        mock_get_chunks.return_value = [
            {
                "chunk_id": "art_003::chunk::000::abc",
                "content": "Chunk 0",
                "metadata": {
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 7,
                    "token_count": 2
                }
            },
            {
                "chunk_id": "art_003::chunk::001::def",
                "content": "Chunk 1",
                "metadata": {
                    "chunk_index": 1,
                    "start_char": 7,
                    "end_char": 14,
                    "token_count": 2
                }
            }
        ]

        result = artifact_get(artifact_id="art_003", include_chunks=True)

    assert "error" not in result
    assert "chunks" in result
    assert len(result["chunks"]) == 2
    assert result["chunks"][0]["chunk_index"] == 0
    assert result["chunks"][1]["chunk_index"] == 1


@pytest.mark.integration
def test_artifact_get_not_found(mock_artifact_services):
    """Test retrieving non-existent artifact."""
    from server import artifact_get

    # Mock no results
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": []
    }

    result = artifact_get(artifact_id="art_999")

    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.integration
def test_artifact_get_invalid_id(mock_artifact_services):
    """Test retrieving with invalid artifact ID."""
    from server import artifact_get

    result = artifact_get(artifact_id="invalid_id")

    assert "error" in result
    assert "Invalid artifact_id format" in result["error"]


@pytest.mark.integration
def test_artifact_delete_unchunked(mock_artifact_services):
    """Test deleting unchunked artifact."""
    from server import artifact_delete

    # Mock artifact exists
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": ["art_001"],
        "documents": ["Content"],
        "metadatas": [{"is_chunked": False}]
    }

    # Mock delete cascade
    with patch("server.delete_artifact_cascade") as mock_delete:
        mock_delete.return_value = 1  # 1 item deleted (artifact only)

        result = artifact_delete(artifact_id="art_001")

    assert "Error" not in result
    assert "Deleted artifact art_001" in result
    assert "0 chunks" in result


@pytest.mark.integration
def test_artifact_delete_with_cascade(mock_artifact_services):
    """Test deleting chunked artifact cascades to chunks."""
    from server import artifact_delete

    # Mock artifact exists
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": ["art_002"],
        "documents": [""],
        "metadatas": [{"is_chunked": True, "num_chunks": 5}]
    }

    # Mock delete cascade
    with patch("server.delete_artifact_cascade") as mock_delete:
        mock_delete.return_value = 6  # 1 artifact + 5 chunks

        result = artifact_delete(artifact_id="art_002")

    assert "Error" not in result
    assert "Deleted artifact art_002" in result
    assert "5 chunks" in result


@pytest.mark.integration
def test_artifact_delete_not_found(mock_artifact_services):
    """Test deleting non-existent artifact."""
    from server import artifact_delete

    # Mock no results
    mock_artifact_services["artifacts"].get.return_value = {
        "ids": []
    }

    result = artifact_delete(artifact_id="art_999")

    assert "Error" in result
    assert "not found" in result


@pytest.mark.integration
def test_artifact_delete_invalid_id(mock_artifact_services):
    """Test deleting with invalid artifact ID."""
    from server import artifact_delete

    result = artifact_delete(artifact_id="invalid_id")

    assert "Error" in result
    assert "Invalid artifact_id format" in result
