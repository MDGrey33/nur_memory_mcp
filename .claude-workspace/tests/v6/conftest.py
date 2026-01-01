"""
V5 Test Configuration and Shared Fixtures.

Provides fixtures for:
- Mock services (ChromaDB, PostgreSQL, OpenAI embeddings)
- Sample content for testing remember/recall/forget
- Mock job queue service
- Test database setup/teardown
"""

import pytest
import os
import sys
import hashlib
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime

# Add src directory to Python path
SRC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "implementation", "mcp-server", "src"
)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "v5: V5-specific tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests (requires infrastructure)")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "run_e2e: Run E2E tests against real infrastructure")


def pytest_addoption(parser):
    """Add command-line options for E2E tests."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run E2E tests against real infrastructure"
    )


def pytest_collection_modifyitems(config, items):
    """Skip E2E tests unless --run-e2e is specified."""
    if config.getoption("--run-e2e"):
        return

    skip_e2e = pytest.mark.skip(reason="need --run-e2e option to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


# =============================================================================
# Environment Setup
# =============================================================================

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key-v5")
    monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_EMBED_DIMS", "3072")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8001")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("ENVIRONMENT", "test")


# =============================================================================
# Mock Postgres Client
# =============================================================================

@pytest.fixture
def mock_pg_client():
    """Mock async Postgres client for V5 tests."""
    mock = AsyncMock()

    # Default behaviors
    mock.fetch_one.return_value = None
    mock.fetch_all.return_value = []
    mock.fetch_val.return_value = None
    mock.execute.return_value = None
    mock.transaction.return_value = None

    # Connection pool context manager
    mock.acquire.return_value.__aenter__ = AsyncMock(return_value=mock)
    mock.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    return mock


# =============================================================================
# Mock Embedding Service
# =============================================================================

@pytest.fixture
def mock_embedding_service():
    """Mock embedding service that returns deterministic embeddings."""
    mock = MagicMock()

    def generate_embedding(text: str) -> List[float]:
        """Generate a deterministic embedding based on text hash."""
        hash_val = hash(text)
        base = (hash_val % 1000) / 1000.0
        embedding = [base + (i * 0.0001) for i in range(3072)]
        magnitude = sum(x**2 for x in embedding) ** 0.5
        return [x / magnitude for x in embedding]

    mock.generate_embedding.side_effect = generate_embedding
    return mock


# =============================================================================
# Mock ChromaDB Client
# =============================================================================

@pytest.fixture
def mock_chroma_client():
    """Mock ChromaDB client for testing."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True

    # Track stored data for verification
    stored_content = {}
    stored_chunks = {}

    # Create a MagicMock wrapper for get_or_create_collection
    original_mock = MagicMock()

    def mock_get_or_create_collection(name: str, **kwargs):
        """Return a mock collection that tracks data."""
        mock_collection = MagicMock()
        mock_collection.name = name

        if name == "content":
            data_store = stored_content
        elif name == "chunks":
            data_store = stored_chunks
        else:
            data_store = {}

        def mock_add(ids, documents, metadatas, embeddings=None):
            for i, id_ in enumerate(ids):
                data_store[id_] = {
                    "id": id_,
                    "document": documents[i] if documents else "",
                    "metadata": metadatas[i] if metadatas else {},
                    "embedding": embeddings[i] if embeddings else None
                }

        def mock_get(ids=None, where=None, include=None):
            results = {"ids": [], "documents": [], "metadatas": []}
            if ids:
                for id_ in ids:
                    if id_ in data_store:
                        results["ids"].append(id_)
                        results["documents"].append(data_store[id_]["document"])
                        results["metadatas"].append(data_store[id_]["metadata"])
            elif where:
                # Simple filter support for content_id
                content_id = where.get("content_id")
                if content_id:
                    for id_, data in data_store.items():
                        if data["metadata"].get("content_id") == content_id:
                            results["ids"].append(id_)
                            results["documents"].append(data["document"])
                            results["metadatas"].append(data["metadata"])
            return results

        def mock_delete(ids=None, where=None):
            if ids:
                for id_ in ids:
                    data_store.pop(id_, None)

        def mock_update(ids, metadatas=None, documents=None, embeddings=None):
            for i, id_ in enumerate(ids):
                if id_ in data_store:
                    if metadatas and i < len(metadatas):
                        data_store[id_]["metadata"] = metadatas[i]
                    if documents and i < len(documents):
                        data_store[id_]["document"] = documents[i]

        def mock_query(query_embeddings=None, n_results=10, where=None, include=None):
            # Return all items up to n_results
            items = list(data_store.values())[:n_results]
            return {
                "ids": [[item["id"] for item in items]],
                "documents": [[item["document"] for item in items]],
                "metadatas": [[item["metadata"] for item in items]],
                "distances": [[0.1 * i for i in range(len(items))]]
            }

        def mock_count():
            return len(data_store)

        mock_collection.add = mock_add
        mock_collection.get = mock_get
        mock_collection.delete = mock_delete
        mock_collection.update = mock_update
        mock_collection.query = mock_query
        mock_collection.count = mock_count

        # Track the call on original_mock for assertion
        original_mock(name, **kwargs)

        return mock_collection

    # Create a MagicMock that wraps our function
    wrapped_mock = MagicMock(side_effect=mock_get_or_create_collection)
    mock_client.get_or_create_collection = wrapped_mock
    mock_client._stored_content = stored_content
    mock_client._stored_chunks = stored_chunks

    return mock_client


# =============================================================================
# Mock ChromaDB Manager
# =============================================================================

@pytest.fixture
def mock_chroma_manager(mock_chroma_client):
    """Mock ChromaDB manager that uses the mock client."""
    manager = MagicMock()
    manager.get_client.return_value = mock_chroma_client
    manager.health_check.return_value = {
        "status": "healthy",
        "latency_ms": 5.0
    }
    return manager


# =============================================================================
# Mock Job Queue Service
# =============================================================================

@pytest.fixture
def mock_job_queue_service():
    """Mock job queue service for event extraction."""
    mock = AsyncMock()

    # Track queued jobs
    queued_jobs = []

    async def mock_enqueue_job(artifact_uid: str, revision_id: str):
        job_id = uuid4()
        queued_jobs.append({
            "job_id": job_id,
            "artifact_uid": artifact_uid,
            "revision_id": revision_id,
            "status": "PENDING"
        })
        return job_id

    mock.enqueue_job.side_effect = mock_enqueue_job
    mock._queued_jobs = queued_jobs

    return mock


# =============================================================================
# Mock Chunking Service
# =============================================================================

@pytest.fixture
def mock_chunking_service():
    """Mock chunking service for V5 tests."""
    mock = MagicMock()

    def count_tokens(text: str) -> int:
        # Approximate: 4 chars per token
        return len(text) // 4

    def should_chunk(text: str) -> tuple:
        """Return (should_chunk, token_count) tuple."""
        tokens = count_tokens(text)
        return (tokens > 1200, tokens)  # Use same threshold as real service

    def chunk_text(text: str, artifact_id: str):
        # Simple chunking for testing
        tokens = count_tokens(text)
        if tokens <= 1200:
            return []

        # Create mock chunks with all required properties
        chunk_size = 800
        chunks = []
        pos = 0
        chunk_index = 0
        while pos < len(text):
            chunk_text_part = text[pos:pos + chunk_size * 4]
            if not chunk_text_part:
                break

            chunk = MagicMock()
            chunk.content = chunk_text_part
            chunk.token_count = count_tokens(chunk_text_part)
            chunk.chunk_index = chunk_index
            chunk.start_char = pos
            chunk.end_char = pos + len(chunk_text_part)
            chunk.content_hash = hashlib.sha256(chunk_text_part.encode()).hexdigest()
            chunk.chunk_id = f"{artifact_id}::chunk::{chunk_index:03d}::{chunk.content_hash[:8]}"
            chunks.append(chunk)

            pos += chunk_size * 4 - 100  # Add overlap
            chunk_index += 1

        return chunks

    mock.count_tokens.side_effect = count_tokens
    mock.should_chunk.side_effect = should_chunk
    mock.chunk_text.side_effect = chunk_text

    return mock


# =============================================================================
# Sample Content Fixtures
# =============================================================================

@pytest.fixture
def sample_document_content() -> str:
    """Sample document content for testing."""
    return """
    Meeting Notes - Project Alpha Planning
    Date: March 15, 2024
    Attendees: Alice Chen (PM), Bob Smith (Engineering), Carol Davis (Design)

    DECISIONS MADE:
    1. Alice decided to launch the product on April 1st, 2024.
    2. The team agreed to use a freemium pricing model.

    COMMITMENTS:
    1. Bob committed to delivering the API integration by March 25th.
    2. Carol will complete the UI mockups by March 20th.

    ACTION ITEMS:
    - Bob: Implement OAuth2 authentication
    - Carol: Design the onboarding flow
    - Alice: Prepare marketing materials

    RISKS IDENTIFIED:
    - Timeline is aggressive, may need to cut scope
    - Third-party API has known reliability issues

    NEXT MEETING: March 22, 2024
    """


@pytest.fixture
def sample_preference_content() -> str:
    """Sample preference content for testing."""
    return "User prefers dark mode for all applications"


@pytest.fixture
def sample_conversation_turn() -> Dict[str, Any]:
    """Sample conversation turn for testing."""
    return {
        "content": "Hello, how can I help you today?",
        "conversation_id": "conv_test_123",
        "turn_index": 0,
        "role": "assistant"
    }


@pytest.fixture
def sample_large_content() -> str:
    """Sample large content that requires chunking (>900 tokens)."""
    base = """
    Software Engineering Best Practices Guide

    Chapter 1: Code Quality
    Writing clean, maintainable code is essential for long-term project success.
    This includes proper naming conventions, documentation, and testing.
    Every function should have a single responsibility and be well-named.

    Chapter 2: Testing Strategies
    Unit tests, integration tests, and end-to-end tests all play important roles.
    Code coverage should be maintained above 80% for critical paths.
    Test-driven development helps catch bugs early in the development cycle.

    Chapter 3: Code Review Process
    Every change should be reviewed by at least one other developer.
    Reviews should focus on correctness, maintainability, and performance.
    """
    # Repeat to exceed 900 tokens (approximately 3600 characters)
    return (base * 10).strip()


# =============================================================================
# Helper Functions
# =============================================================================

@pytest.fixture
def generate_content_id():
    """Factory fixture to generate V5 content IDs."""
    def _generate(content: str) -> str:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"art_{content_hash}"
    return _generate


@pytest.fixture
def create_mock_content():
    """Factory fixture to create mock V5 content entries."""
    def _create(
        content: str = "Test content",
        context: str = "note",
        importance: float = 0.5,
        title: Optional[str] = None,
        author: Optional[str] = None
    ) -> Dict[str, Any]:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        return {
            "id": f"art_{content_hash}",
            "content": content,
            "metadata": {
                "context": context,
                "importance": importance,
                "title": title,
                "author": author,
                "ingested_at": datetime.utcnow().isoformat() + "Z",
                "is_chunked": False,
                "num_chunks": 0,
                "token_count": len(content) // 4
            }
        }
    return _create


# =============================================================================
# Mock Config
# =============================================================================

@pytest.fixture
def mock_config():
    """Mock configuration object for V5 tests."""
    mock = MagicMock()
    mock.openai_embed_model = "text-embedding-3-large"
    mock.openai_embed_dims = 3072
    mock.environment = "test"
    mock.version = "5.0.0-test"
    return mock


# =============================================================================
# Mock Retrieval Service
# =============================================================================

@pytest.fixture
def mock_retrieval_service():
    """Mock retrieval service for V5 tests."""
    mock = MagicMock()

    class MockSearchResult:
        """Mock search result object with to_dict method."""
        def __init__(self, results=None, related=None, entities=None):
            self.primary_results = results or []
            self.related_context = related or []
            self.entities = entities or []

        def to_dict(self):
            return {
                "primary_results": self.primary_results,
                "related_context": self.related_context,
                "entities": self.entities
            }

    async def mock_hybrid_search_v4(
        query: str,
        limit: int = 10,
        include_memory: bool = False,
        expand_neighbors: bool = False,
        graph_expand: bool = True,
        graph_depth: int = 1,
        graph_budget: int = 10,
        graph_seed_limit: int = 1,
        graph_filters: Optional[Dict] = None,
        include_entities: bool = False,
        **kwargs
    ):
        """Return mock search results."""
        return MockSearchResult(
            results=[{
                "type": "artifact",
                "id": "art_test001",
                "content": "Mock content",
                "metadata": {"context": "note"}
            }],
            related=[{"id": "art_related001"}] if graph_expand else [],
            entities=[{"name": "Test Entity"}] if include_entities else []
        )

    async def mock_hybrid_search_v5(
        query: str,
        limit: int = 10,
        expand: bool = True,
        graph_budget: int = 10,
        graph_filters: Optional[Dict] = None,
        include_entities: bool = False,
        context_filter: Optional[str] = None,
        min_importance: Optional[float] = None,
        **kwargs
    ):
        """Return mock V5 search results."""
        return MockSearchResult(
            results=[{
                "type": "artifact",
                "id": "art_test001",
                "content": "Mock content",
                "metadata": {"context": context_filter or "note", "importance": 0.8}
            }],
            related=[{"id": "art_related001"}] if expand else [],
            entities=[{"name": "Test Entity"}] if include_entities else []
        )

    mock.hybrid_search_v4 = mock_hybrid_search_v4
    mock.hybrid_search_v5 = mock_hybrid_search_v5
    mock.MockSearchResult = MockSearchResult
    return mock


# =============================================================================
# Async Test Support
# =============================================================================

@pytest.fixture
def event_loop_policy():
    """Use asyncio event loop for async tests."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


# =============================================================================
# Integration Test Fixtures
# =============================================================================

@pytest.fixture
def v5_test_harness(
    mock_chroma_manager,
    mock_pg_client,
    mock_embedding_service,
    mock_chunking_service,
    mock_job_queue_service,
    mock_retrieval_service,
    mock_config
):
    """
    Complete V5 test harness with all mocked dependencies.

    Returns a dict with all mocked services for use in integration tests.
    """
    return {
        "chroma_manager": mock_chroma_manager,
        "chroma_client": mock_chroma_manager.get_client(),
        "pg_client": mock_pg_client,
        "embedding_service": mock_embedding_service,
        "chunking_service": mock_chunking_service,
        "job_queue_service": mock_job_queue_service,
        "retrieval_service": mock_retrieval_service,
        "config": mock_config
    }
