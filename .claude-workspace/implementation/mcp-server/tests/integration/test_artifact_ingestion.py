"""Integration tests for artifact ingestion."""

import pytest
import hashlib
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


@pytest.fixture
def mock_services():
    """Mock all services for integration testing."""
    with patch("server.embedding_service") as mock_embed, \
         patch("server.chunking_service") as mock_chunk, \
         patch("server.chroma_manager") as mock_chroma, \
         patch("server.config") as mock_config:

        # Setup mock embedding service
        mock_embed.generate_embedding.return_value = [0.1] * 3072
        mock_embed.generate_embeddings_batch.return_value = [[0.1] * 3072] * 10

        # Setup mock chunking service
        mock_chunk.should_chunk.return_value = (False, 500)
        mock_chunk.count_tokens.return_value = 500

        # Setup mock chroma client
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.add.return_value = None
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_client.return_value = mock_client

        # Setup mock config
        mock_config.openai_embed_model = "text-embedding-3-large"
        mock_config.openai_embed_dims = 3072

        yield {
            "embed": mock_embed,
            "chunk": mock_chunk,
            "chroma": mock_chroma,
            "config": mock_config,
            "client": mock_client,
            "collection": mock_collection
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_small_artifact(mock_services):
    """Test ingesting small artifact that doesn't need chunking."""
    from server import artifact_ingest

    # Small artifact
    content = "This is a small test document."
    mock_services["chunk"].should_chunk.return_value = (False, 50)
    mock_services["chunk"].count_tokens.return_value = 50

    result = await artifact_ingest(
        artifact_type="doc",
        source_system="manual",
        content=content,
        title="Test Doc"
    )

    assert "error" not in result
    assert result["is_chunked"] is False
    assert result["num_chunks"] == 0
    assert "artifact_id" in result
    assert len(result["stored_ids"]) == 1

    # Verify embedding was generated
    mock_services["embed"].generate_embedding.assert_called_once()

    # Verify artifact was stored
    mock_services["collection"].add.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_large_artifact(mock_services):
    """Test ingesting large artifact that needs chunking."""
    from server import artifact_ingest
    from storage.models import Chunk

    # Large artifact
    content = "This is a test document. " * 200
    mock_services["chunk"].should_chunk.return_value = (True, 2000)
    mock_services["chunk"].count_tokens.return_value = 2000

    # Mock chunks
    mock_chunks = [
        Chunk(
            chunk_id="art_test::chunk::000::abc",
            artifact_id="art_test",
            chunk_index=0,
            content="Chunk 0",
            start_char=0,
            end_char=7,
            token_count=900,
            content_hash="abc"
        ),
        Chunk(
            chunk_id="art_test::chunk::001::def",
            artifact_id="art_test",
            chunk_index=1,
            content="Chunk 1",
            start_char=7,
            end_char=14,
            token_count=900,
            content_hash="def"
        )
    ]
    mock_services["chunk"].chunk_text.return_value = mock_chunks

    # Mock batch embeddings
    mock_services["embed"].generate_embeddings_batch.return_value = [[0.1] * 3072] * 2

    result = await artifact_ingest(
        artifact_type="doc",
        source_system="manual",
        content=content,
        title="Large Doc"
    )

    assert "error" not in result
    assert result["is_chunked"] is True
    assert result["num_chunks"] == 2
    assert len(result["stored_ids"]) == 3  # artifact + 2 chunks

    # Verify batch embedding was used
    mock_services["embed"].generate_embeddings_batch.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_idempotency(mock_services):
    """Test ingesting same artifact twice (idempotent)."""
    from server import artifact_ingest

    content = "Test document content"
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # First ingestion - no existing artifact
    mock_services["chunk"].should_chunk.return_value = (False, 50)
    mock_services["chunk"].count_tokens.return_value = 50

    with patch("server.get_artifact_by_source", return_value=None):
        result1 = await artifact_ingest(
            artifact_type="doc",
            source_system="manual",
            source_id="doc123",
            content=content
        )

    assert "error" not in result1
    assert "artifact_id" in result1

    # Second ingestion - same content (should skip)
    mock_existing = {
        "artifact_id": result1["artifact_id"],
        "metadata": {
            "content_hash": content_hash,
            "is_chunked": False,
            "num_chunks": 0
        }
    }

    with patch("server.get_artifact_by_source", return_value=mock_existing):
        result2 = await artifact_ingest(
            artifact_type="doc",
            source_system="manual",
            source_id="doc123",
            content=content
        )

    assert result2["status"] == "unchanged"
    assert result2["artifact_id"] == result1["artifact_id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_content_change(mock_services):
    """Test ingesting updated content for existing artifact."""
    from server import artifact_ingest

    old_content = "Old content"
    new_content = "New updated content"

    old_hash = hashlib.sha256(old_content.encode()).hexdigest()
    new_hash = hashlib.sha256(new_content.encode()).hexdigest()

    # The artifact_id is generated from sha256(source_system:source_id)[:8]
    expected_artifact_id = "art_" + hashlib.sha256("manual:doc123".encode()).hexdigest()[:8]

    # Mock existing artifact with old hash
    mock_existing = {
        "artifact_id": expected_artifact_id,
        "metadata": {
            "content_hash": old_hash,
            "is_chunked": False
        }
    }

    mock_services["chunk"].should_chunk.return_value = (False, 50)
    mock_services["chunk"].count_tokens.return_value = 50

    with patch("server.get_artifact_by_source", return_value=mock_existing), \
         patch("server.delete_artifact_cascade") as mock_delete:

        result = await artifact_ingest(
            artifact_type="doc",
            source_system="manual",
            source_id="doc123",
            content=new_content
        )

    # Should delete old version
    mock_delete.assert_called_once_with(mock_services["client"], expected_artifact_id)

    # Should ingest new version
    assert "error" not in result
    assert result["is_chunked"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_two_phase_atomic_failure(mock_services):
    """Test two-phase atomic write fails if embedding generation fails."""
    from server import artifact_ingest
    from storage.models import Chunk
    from utils.errors import EmbeddingError

    # Large artifact requiring chunking
    content = "Test document. " * 200
    mock_services["chunk"].should_chunk.return_value = (True, 2000)
    mock_services["chunk"].count_tokens.return_value = 2000

    # Mock chunks
    mock_chunks = [
        Chunk(
            chunk_id="art_test::chunk::000::abc",
            artifact_id="art_test",
            chunk_index=0,
            content="Chunk 0",
            start_char=0,
            end_char=7,
            token_count=900,
            content_hash="abc"
        )
    ]
    mock_services["chunk"].chunk_text.return_value = mock_chunks

    # Make batch embedding fail (Phase 1 failure)
    mock_services["embed"].generate_embeddings_batch.side_effect = EmbeddingError("API error")

    result = await artifact_ingest(
        artifact_type="doc",
        source_system="manual",
        content=content
    )

    # Should return error (no partial writes)
    assert "error" in result
    assert "Failed to generate embeddings" in result["error"]

    # Should NOT have written anything to database
    # (In real implementation, verify no add() calls were made after embedding failure)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_invalid_artifact_type(mock_services):
    """Test ingestion with invalid artifact type."""
    from server import artifact_ingest

    result = await artifact_ingest(
        artifact_type="invalid_type",
        source_system="manual",
        content="Test"
    )

    assert "error" in result
    assert "Invalid artifact_type" in result["error"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_empty_content(mock_services):
    """Test ingestion with empty content."""
    from server import artifact_ingest

    result = await artifact_ingest(
        artifact_type="doc",
        source_system="manual",
        content=""
    )

    assert "error" in result
    assert "Content must be between" in result["error"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_with_metadata(mock_services):
    """Test ingestion with full metadata."""
    from server import artifact_ingest

    mock_services["chunk"].should_chunk.return_value = (False, 100)
    mock_services["chunk"].count_tokens.return_value = 100

    result = await artifact_ingest(
        artifact_type="email",
        source_system="gmail",
        content="Email content",
        source_id="msg123",
        source_url="https://mail.google.com/...",
        title="Important Email",
        author="sender@example.com",
        participants=["user1@example.com", "user2@example.com"],
        ts="2025-01-01T00:00:00Z",
        sensitivity="sensitive",
        visibility_scope="team",
        retention_policy="1y"
    )

    assert "error" not in result
    assert "artifact_id" in result

    # Verify metadata was included in add() call
    call_args = mock_services["collection"].add.call_args
    metadata = call_args[1]["metadatas"][0]

    assert metadata["artifact_type"] == "email"
    assert metadata["source_system"] == "gmail"
    assert metadata["title"] == "Important Email"
    assert metadata["author"] == "sender@example.com"
    assert metadata["sensitivity"] == "sensitive"
    assert metadata["visibility_scope"] == "team"
