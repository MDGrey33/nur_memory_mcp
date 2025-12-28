"""Pytest configuration and shared fixtures."""

import pytest
import os
import sys
from unittest.mock import Mock, MagicMock, patch
from typing import List

# Add src directory to Python path for imports
SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)


# ============================================================================
# Environment Setup
# ============================================================================

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_EMBED_DIMS", "3072")
    monkeypatch.setenv("OPENAI_EVENT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8001")
    monkeypatch.setenv("MCP_PORT", "3000")
    monkeypatch.setenv("EVENTS_DB_DSN", "postgresql://events:events@localhost:5432/events")
    monkeypatch.setenv("POSTGRES_POOL_MIN", "2")
    monkeypatch.setenv("POSTGRES_POOL_MAX", "10")
    monkeypatch.setenv("POLL_INTERVAL_MS", "1000")
    monkeypatch.setenv("EVENT_MAX_ATTEMPTS", "5")


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def test_config():
    """Create a test configuration object."""
    from config import Config
    return Config(
        openai_api_key="test-api-key-12345",
        openai_embed_model="text-embedding-3-large",
        openai_embed_dims=3072,
        openai_timeout=30,
        openai_max_retries=3,
        openai_batch_size=100,
        openai_event_model="gpt-4o-mini",
        single_piece_max_tokens=1200,
        chunk_target_tokens=900,
        chunk_overlap_tokens=100,
        chroma_host="localhost",
        chroma_port=8001,
        events_db_dsn="postgresql://events:events@localhost:5432/events",
        postgres_pool_min=2,
        postgres_pool_max=10,
        worker_id=None,
        poll_interval_ms=1000,
        event_max_attempts=5,
        mcp_port=3000,
        log_level="INFO",
        rrf_constant=60
    )


# ============================================================================
# OpenAI Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    mock_client = MagicMock()

    # Mock embedding response
    mock_embedding_data = Mock()
    mock_embedding_data.embedding = [0.1] * 3072

    mock_response = Mock()
    mock_response.data = [mock_embedding_data]

    mock_client.embeddings.create.return_value = mock_response

    return mock_client


@pytest.fixture
def mock_openai_batch_client():
    """Mock OpenAI client for batch operations."""
    mock_client = MagicMock()

    # Mock batch embedding response
    def create_batch_response(input, **kwargs):
        num_items = len(input)
        mock_data = [Mock(embedding=[0.1] * 3072) for _ in range(num_items)]
        mock_response = Mock()
        mock_response.data = mock_data
        return mock_response

    mock_client.embeddings.create.side_effect = create_batch_response

    return mock_client


# ============================================================================
# ChromaDB Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_chroma_client():
    """Mock ChromaDB client for testing."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True

    # Mock collection
    mock_collection = MagicMock()
    mock_collection.name = "test_collection"
    mock_collection.add.return_value = None
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }
    mock_collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": []
    }
    mock_collection.delete.return_value = None

    mock_client.get_or_create_collection.return_value = mock_collection

    return mock_client


@pytest.fixture
def mock_chroma_collection():
    """Mock ChromaDB collection for testing."""
    mock_collection = MagicMock()
    mock_collection.name = "test_collection"
    mock_collection.add.return_value = None
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }
    mock_collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": []
    }
    mock_collection.delete.return_value = None

    return mock_collection


# ============================================================================
# Service Fixtures
# ============================================================================

@pytest.fixture
def embedding_service(mock_openai_client):
    """Create EmbeddingService with mocked OpenAI client."""
    from services.embedding_service import EmbeddingService
    service = EmbeddingService(
        api_key="test-api-key-12345",
        model="text-embedding-3-large",
        dimensions=3072,
        timeout=30,
        max_retries=3,
        batch_size=100
    )
    service.client = mock_openai_client
    return service


@pytest.fixture
def chunking_service():
    """Create ChunkingService for testing."""
    from services.chunking_service import ChunkingService
    return ChunkingService(
        single_piece_max=1200,
        chunk_target=900,
        chunk_overlap=100
    )


@pytest.fixture
def retrieval_service(embedding_service, chunking_service, mock_chroma_client):
    """Create RetrievalService with mocked dependencies."""
    from services.retrieval_service import RetrievalService
    return RetrievalService(
        embedding_service=embedding_service,
        chunking_service=chunking_service,
        chroma_client=mock_chroma_client,
        k=60
    )


@pytest.fixture
def privacy_service():
    """Create PrivacyFilterService for testing."""
    from services.privacy_service import PrivacyFilterService
    return PrivacyFilterService()


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_text_short():
    """Short text that should NOT be chunked."""
    return "This is a short piece of text that fits within token limits."


@pytest.fixture
def sample_text_long():
    """Long text that SHOULD be chunked."""
    # Generate text > 1200 tokens (roughly 4800 characters)
    paragraph = "This is a sample paragraph that will be repeated many times to create a long document. " * 20
    return paragraph * 15  # ~27000 characters = ~6750 tokens


@pytest.fixture
def sample_chunks():
    """Sample chunk objects for testing."""
    from storage.models import Chunk
    return [
        Chunk(
            chunk_id="art_test123::chunk::000::abc12345",
            artifact_id="art_test123",
            chunk_index=0,
            content="First chunk content with some text.",
            start_char=0,
            end_char=36,
            token_count=8,
            content_hash="abc12345"
        ),
        Chunk(
            chunk_id="art_test123::chunk::001::def67890",
            artifact_id="art_test123",
            chunk_index=1,
            content="Second chunk content with more text.",
            start_char=36,
            end_char=73,
            token_count=9,
            content_hash="def67890"
        ),
        Chunk(
            chunk_id="art_test123::chunk::002::ghi24680",
            artifact_id="art_test123",
            chunk_index=2,
            content="Third chunk content with additional text.",
            start_char=73,
            end_char=115,
            token_count=9,
            content_hash="ghi24680"
        )
    ]


@pytest.fixture
def sample_search_results():
    """Sample search results for RRF testing."""
    from storage.models import SearchResult
    return [
        SearchResult(
            id="art_001",
            content="Result from artifacts collection",
            metadata={"title": "Doc 1", "type": "doc"},
            collection="artifacts",
            rank=0,
            distance=0.1,
            is_chunk=False
        ),
        SearchResult(
            id="art_002::chunk::000::xyz",
            content="Result from chunks collection",
            metadata={"artifact_id": "art_002", "chunk_index": 0},
            collection="artifact_chunks",
            rank=0,
            distance=0.15,
            is_chunk=True,
            artifact_id="art_002"
        ),
        SearchResult(
            id="mem_123",
            content="Result from memory collection",
            metadata={"type": "preference", "confidence": 0.9},
            collection="memory",
            rank=0,
            distance=0.2,
            is_chunk=False
        )
    ]
