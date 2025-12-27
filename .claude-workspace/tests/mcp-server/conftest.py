"""
Pytest configuration and fixtures for MCP Server V3 tests.

Provides mock implementations for:
- Postgres client
- ChromaDB client
- OpenAI client
- Sample test data
"""

import pytest
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, Mock
import json

# Add src directory to Python path
src_path = Path(__file__).parent.parent.parent / "implementation" / "mcp-server" / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Sample Test Data
# ============================================================================

@pytest.fixture
def sample_artifact_uid() -> str:
    """Return a test artifact UID."""
    return "art_test_abc123"


@pytest.fixture
def sample_revision_id() -> str:
    """Return a test revision ID."""
    return "rev_test_def456"


@pytest.fixture
def sample_chunk_id() -> str:
    """Return a test chunk ID."""
    return "art_test_abc123::chunk::001::xyz789"


@pytest.fixture
def sample_job_id() -> UUID:
    """Return a test job ID."""
    return UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def sample_event_id() -> UUID:
    """Return a test event ID."""
    return UUID("87654321-4321-8765-4321-876543218765")


@pytest.fixture
def sample_extraction_run_id() -> UUID:
    """Return a test extraction run ID."""
    return UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def sample_timestamp() -> datetime:
    """Return a fixed timestamp for testing."""
    return datetime(2025, 12, 27, 12, 0, 0)


@pytest.fixture
def sample_artifact_text() -> str:
    """Return sample artifact text for extraction."""
    return """
    Meeting Notes - Q1 Planning Session
    Date: 2024-03-15
    Attendees: Alice Chen (PM), Bob Smith (Eng Lead), Carol White (Design)

    Decisions Made:
    1. We decided to adopt a freemium pricing model for the product launch.
       Alice will own the pricing page redesign.

    2. Bob committed to delivering the MVP by March 31st, including:
       - User authentication
       - Payment integration
       - Admin dashboard

    3. Carol raised concerns about the current UI being too complex.
       Users reported confusion during the beta testing phase.

    Action Items:
    - Alice: Create pricing tiers document by EOW
    - Bob: Set up staging environment by next Monday
    - Carol: Conduct usability testing with 5 users

    Next meeting: March 22nd
    """


@pytest.fixture
def sample_chunk_text() -> str:
    """Return sample chunk text for extraction."""
    return """
    Decisions Made:
    1. We decided to adopt a freemium pricing model for the product launch.
       Alice will own the pricing page redesign.
    """


@pytest.fixture
def sample_extracted_events() -> List[Dict[str, Any]]:
    """Return sample extracted events from Prompt A."""
    return [
        {
            "category": "Decision",
            "narrative": "Team decided to adopt freemium pricing model for product launch",
            "event_time": "2024-03-15T00:00:00Z",
            "subject": {"type": "project", "ref": "pricing-model"},
            "actors": [{"ref": "Alice Chen", "role": "owner"}],
            "confidence": 0.95,
            "evidence": [
                {
                    "quote": "decided to adopt a freemium pricing model",
                    "start_char": 150,
                    "end_char": 195,
                    "chunk_id": "art_test_abc123::chunk::001::xyz789"
                }
            ]
        },
        {
            "category": "Commitment",
            "narrative": "Bob committed to delivering MVP by March 31st",
            "event_time": "2024-03-31T00:00:00Z",
            "subject": {"type": "project", "ref": "MVP"},
            "actors": [{"ref": "Bob Smith", "role": "owner"}],
            "confidence": 0.92,
            "evidence": [
                {
                    "quote": "Bob committed to delivering the MVP by March 31st",
                    "start_char": 250,
                    "end_char": 302,
                    "chunk_id": "art_test_abc123::chunk::002::xyz789"
                }
            ]
        },
        {
            "category": "Feedback",
            "narrative": "Users reported UI confusion during beta testing",
            "event_time": None,
            "subject": {"type": "object", "ref": "UI"},
            "actors": [{"ref": "Carol White", "role": "contributor"}],
            "confidence": 0.88,
            "evidence": [
                {
                    "quote": "Users reported confusion during the beta testing phase",
                    "start_char": 400,
                    "end_char": 455,
                    "chunk_id": "art_test_abc123::chunk::003::xyz789"
                }
            ]
        }
    ]


@pytest.fixture
def sample_canonical_events() -> List[Dict[str, Any]]:
    """Return sample canonicalized events from Prompt B."""
    return [
        {
            "category": "Decision",
            "narrative": "Team decided to adopt freemium pricing model for product launch",
            "event_time": "2024-03-15T00:00:00Z",
            "subject": {"type": "project", "ref": "pricing-model"},
            "actors": [{"ref": "Alice Chen", "role": "owner"}],
            "confidence": 0.95,
            "evidence": [
                {
                    "quote": "decided to adopt a freemium pricing model",
                    "start_char": 150,
                    "end_char": 195,
                    "chunk_id": "art_test_abc123::chunk::001::xyz789"
                }
            ]
        },
        {
            "category": "Commitment",
            "narrative": "Bob Smith committed to delivering MVP with authentication, payment, and admin features by March 31st",
            "event_time": "2024-03-31T00:00:00Z",
            "subject": {"type": "project", "ref": "MVP"},
            "actors": [{"ref": "Bob Smith", "role": "owner"}],
            "confidence": 0.92,
            "evidence": [
                {
                    "quote": "Bob committed to delivering the MVP by March 31st",
                    "start_char": 250,
                    "end_char": 302,
                    "chunk_id": "art_test_abc123::chunk::002::xyz789"
                },
                {
                    "quote": "User authentication",
                    "start_char": 320,
                    "end_char": 339,
                    "chunk_id": "art_test_abc123::chunk::002::xyz789"
                }
            ]
        }
    ]


@pytest.fixture
def sample_artifact_revision_row(sample_artifact_uid, sample_revision_id, sample_timestamp) -> Dict[str, Any]:
    """Return sample artifact_revision database row."""
    return {
        "artifact_uid": sample_artifact_uid,
        "revision_id": sample_revision_id,
        "artifact_id": "chroma_art_123",
        "artifact_type": "doc",
        "source_system": "test",
        "source_id": "test_doc_1",
        "source_ts": sample_timestamp,
        "content_hash": "hash_abc123",
        "token_count": 500,
        "is_chunked": False,
        "chunk_count": 0,
        "sensitivity": "internal",
        "visibility_scope": "team",
        "retention_policy": "standard",
        "is_latest": True,
        "ingested_at": sample_timestamp
    }


@pytest.fixture
def sample_event_job_row(sample_job_id, sample_artifact_uid, sample_revision_id, sample_timestamp) -> Dict[str, Any]:
    """Return sample event_jobs database row."""
    return {
        "job_id": sample_job_id,
        "job_type": "extract_events",
        "artifact_uid": sample_artifact_uid,
        "revision_id": sample_revision_id,
        "status": "PENDING",
        "attempts": 0,
        "max_attempts": 5,
        "next_run_at": sample_timestamp,
        "locked_at": None,
        "locked_by": None,
        "last_error_code": None,
        "last_error_message": None,
        "created_at": sample_timestamp,
        "updated_at": sample_timestamp
    }


@pytest.fixture
def sample_semantic_event_row(
    sample_event_id,
    sample_artifact_uid,
    sample_revision_id,
    sample_extraction_run_id,
    sample_timestamp
) -> Dict[str, Any]:
    """Return sample semantic_event database row."""
    return {
        "event_id": sample_event_id,
        "artifact_uid": sample_artifact_uid,
        "revision_id": sample_revision_id,
        "category": "Decision",
        "event_time": datetime(2024, 3, 15, 14, 30, 0),
        "narrative": "Team decided to adopt freemium pricing model",
        "subject_json": {"type": "project", "ref": "pricing-model"},
        "actors_json": [{"ref": "Alice Chen", "role": "owner"}],
        "confidence": 0.95,
        "extraction_run_id": sample_extraction_run_id,
        "created_at": sample_timestamp
    }


@pytest.fixture
def sample_event_evidence_rows(sample_event_id, sample_artifact_uid, sample_revision_id) -> List[Dict[str, Any]]:
    """Return sample event_evidence database rows."""
    return [
        {
            "evidence_id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            "event_id": sample_event_id,
            "artifact_uid": sample_artifact_uid,
            "revision_id": sample_revision_id,
            "chunk_id": "art_test_abc123::chunk::001::xyz789",
            "start_char": 150,
            "end_char": 195,
            "quote": "decided to adopt a freemium pricing model",
            "created_at": datetime(2025, 12, 27, 12, 0, 0)
        },
        {
            "evidence_id": UUID("ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb"),
            "event_id": sample_event_id,
            "artifact_uid": sample_artifact_uid,
            "revision_id": sample_revision_id,
            "chunk_id": "art_test_abc123::chunk::001::xyz789",
            "start_char": 200,
            "end_char": 240,
            "quote": "Alice will own the pricing page redesign",
            "created_at": datetime(2025, 12, 27, 12, 0, 0)
        }
    ]


# ============================================================================
# Mock Postgres Client
# ============================================================================

@pytest.fixture
def mock_pg_pool():
    """Mock asyncpg connection pool."""
    pool = AsyncMock()
    pool.get_size.return_value = 10
    pool.get_idle_size.return_value = 8
    return pool


@pytest.fixture
def mock_pg_connection():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.transaction = AsyncMock()
    return conn


@pytest.fixture
def mock_postgres_client(mock_pg_pool, mock_pg_connection):
    """Mock PostgresClient instance."""
    from storage.postgres_client import PostgresClient

    client = PostgresClient(dsn="postgresql://test:test@localhost:5432/test")
    client._pool = mock_pg_pool

    # Mock acquire context manager
    async def mock_acquire():
        yield mock_pg_connection

    client.acquire = mock_acquire

    return client


# ============================================================================
# Mock ChromaDB Client
# ============================================================================

@pytest.fixture
def mock_chroma_collection():
    """Mock ChromaDB collection."""
    collection = MagicMock()
    collection.name = "artifacts"
    collection.count.return_value = 0
    collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
        "embeddings": None
    }
    collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
        "embeddings": None
    }
    collection.add.return_value = None
    collection.delete.return_value = None
    return collection


@pytest.fixture
def mock_chroma_client(mock_chroma_collection):
    """Mock ChromaDB HttpClient."""
    client = MagicMock()
    client.heartbeat.return_value = None
    client.get_collection.return_value = mock_chroma_collection
    client.get_or_create_collection.return_value = mock_chroma_collection
    client.list_collections.return_value = []
    return client


@pytest.fixture
def mock_chroma_manager(mock_chroma_client):
    """Mock ChromaClientManager instance."""
    from storage.chroma_client import ChromaClientManager

    manager = ChromaClientManager(host="localhost", port=8001)
    manager._client = mock_chroma_client
    return manager


# ============================================================================
# Mock OpenAI Client
# ============================================================================

@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({
                    "events": [
                        {
                            "category": "Decision",
                            "narrative": "Test event",
                            "event_time": None,
                            "subject": {"type": "project", "ref": "test"},
                            "actors": [{"ref": "Alice", "role": "owner"}],
                            "confidence": 0.9,
                            "evidence": [
                                {
                                    "quote": "test quote",
                                    "start_char": 0,
                                    "end_char": 10
                                }
                            ]
                        }
                    ]
                })
            )
        )
    ]
    return response


@pytest.fixture
def mock_openai_client(mock_openai_response):
    """Mock OpenAI client."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock(return_value=mock_openai_response)
    return client


# ============================================================================
# Service Fixtures
# ============================================================================

@pytest.fixture
def mock_event_extraction_service(mock_openai_client):
    """Mock EventExtractionService instance."""
    from services.event_extraction_service import EventExtractionService

    service = EventExtractionService(
        api_key="test_key",
        model="gpt-4o-mini",
        temperature=0.0,
        timeout=60
    )
    service.client = mock_openai_client
    return service


@pytest.fixture
def mock_job_queue_service(mock_postgres_client):
    """Mock JobQueueService instance."""
    from services.job_queue_service import JobQueueService

    service = JobQueueService(
        pg_client=mock_postgres_client,
        max_attempts=5
    )
    return service


# ============================================================================
# Worker Fixtures
# ============================================================================

@pytest.fixture
def mock_event_worker_config():
    """Mock Config for EventWorker."""
    from config import Config

    return Config(
        openai_api_key="test_key",
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
        events_db_dsn="postgresql://test:test@localhost:5432/test",
        postgres_pool_min=2,
        postgres_pool_max=10,
        worker_id="test-worker",
        poll_interval_ms=1000,
        event_max_attempts=5,
        mcp_port=3000,
        log_level="INFO",
        rrf_constant=60
    )


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def clean_test_db():
    """
    Fixture to clean test database before/after tests.
    NOTE: This requires a real Postgres instance for integration tests.
    """
    # This is a placeholder - actual implementation would use a test database
    yield
    # Cleanup code here


@pytest.fixture
def mock_uuid4():
    """Mock uuid4 to return predictable UUIDs."""
    import uuid
    original_uuid4 = uuid.uuid4
    test_uuid = UUID("99999999-9999-9999-9999-999999999999")
    uuid.uuid4 = lambda: test_uuid
    yield test_uuid
    uuid.uuid4 = original_uuid4
