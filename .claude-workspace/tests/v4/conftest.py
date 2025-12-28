"""
V4 Test Configuration and Shared Fixtures.

Provides fixtures for:
- Mock services (OpenAI, Postgres, ChromaDB)
- Sample entities and events
- Mock LLM responses for entity dedup
- Test database setup/teardown
"""

import pytest
import os
import sys
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

# Add src directory to Python path
SRC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    ".claude-workspace", "implementation", "mcp-server", "src"
)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "v4: V4-specific tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "requires_age: Tests requiring Apache AGE")
    config.addinivalue_line("markers", "requires_postgres: Tests requiring Postgres")


# =============================================================================
# Environment Setup
# =============================================================================

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key-v4")
    monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_EMBED_DIMS", "3072")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8001")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")


# =============================================================================
# Mock Postgres Client
# =============================================================================

@pytest.fixture
def mock_pg_client():
    """Mock async Postgres client for V4 tests."""
    mock = AsyncMock()

    # Default behaviors
    mock.fetch_one.return_value = None
    mock.fetch_all.return_value = []
    mock.fetch_val.return_value = None
    mock.execute.return_value = None

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
        # Use hash to generate reproducible but different embeddings
        hash_val = hash(text)
        # Create a 3072-dim vector with values based on hash
        base = (hash_val % 1000) / 1000.0
        embedding = [base + (i * 0.0001) for i in range(3072)]
        # Normalize
        magnitude = sum(x**2 for x in embedding) ** 0.5
        return [x / magnitude for x in embedding]

    mock.generate_embedding.side_effect = generate_embedding
    return mock


# =============================================================================
# Mock OpenAI Client for Entity Resolution
# =============================================================================

@pytest.fixture
def mock_openai_dedup_client():
    """Mock OpenAI client for entity deduplication tests."""
    mock = MagicMock()

    # Default response: different entities
    default_response = {
        "decision": "different",
        "canonical_name": "",
        "reason": "Insufficient context to determine if same entity"
    }

    def create_completion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"decision": "different", "canonical_name": "", "reason": "Test default"}'
        return response

    mock.chat.completions.create.side_effect = create_completion
    return mock


@pytest.fixture
def mock_openai_same_entity():
    """Mock OpenAI client that returns 'same' for entity dedup."""
    mock = MagicMock()

    def create_completion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"decision": "same", "canonical_name": "Alice Chen", "reason": "Same person based on context"}'
        return response

    mock.chat.completions.create.side_effect = create_completion
    return mock


@pytest.fixture
def mock_openai_uncertain_entity():
    """Mock OpenAI client that returns 'uncertain' for entity dedup."""
    mock = MagicMock()

    def create_completion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"decision": "uncertain", "canonical_name": "", "reason": "Not enough context to determine"}'
        return response

    mock.chat.completions.create.side_effect = create_completion
    return mock


# =============================================================================
# Sample Entity Data
# =============================================================================

@pytest.fixture
def sample_entity_alice():
    """Sample entity: Alice Chen, Engineering Manager at Acme."""
    return {
        "entity_id": uuid4(),
        "entity_type": "person",
        "canonical_name": "Alice Chen",
        "normalized_name": "alice chen",
        "role": "Engineering Manager",
        "organization": "Acme Corp",
        "email": "achen@acme.com",
        "first_seen_artifact_uid": "doc_001",
        "first_seen_revision_id": "rev_001",
        "needs_review": False
    }


@pytest.fixture
def sample_entity_bob():
    """Sample entity: Bob Smith, Designer at OtherCorp."""
    return {
        "entity_id": uuid4(),
        "entity_type": "person",
        "canonical_name": "Bob Smith",
        "normalized_name": "bob smith",
        "role": "Designer",
        "organization": "OtherCorp",
        "email": "bob@othercorp.com",
        "first_seen_artifact_uid": "doc_002",
        "first_seen_revision_id": "rev_001",
        "needs_review": False
    }


@pytest.fixture
def sample_extracted_entity_alice():
    """Sample extracted entity from LLM."""
    from services.entity_resolution_service import ExtractedEntity, ContextClues
    return ExtractedEntity(
        surface_form="Alice Chen",
        canonical_suggestion="Alice Chen",
        entity_type="person",
        context_clues=ContextClues(
            role="Engineering Manager",
            organization="Acme Corp",
            email="achen@acme.com"
        ),
        aliases_in_doc=["Alice", "A. Chen"],
        confidence=0.95,
        start_char=150,
        end_char=160
    )


@pytest.fixture
def sample_extracted_entity_minimal():
    """Sample extracted entity with minimal context."""
    from services.entity_resolution_service import ExtractedEntity, ContextClues
    return ExtractedEntity(
        surface_form="A. Chen",
        canonical_suggestion="A. Chen",
        entity_type="person",
        context_clues=ContextClues(),
        aliases_in_doc=[],
        confidence=0.7,
        start_char=50,
        end_char=57
    )


# =============================================================================
# Sample Event Data
# =============================================================================

@pytest.fixture
def sample_semantic_event():
    """Sample semantic event."""
    return {
        "event_id": uuid4(),
        "artifact_uid": "doc_001",
        "revision_id": "rev_001",
        "category": "Decision",
        "event_time": datetime.now(),
        "narrative": "Team decided to adopt freemium pricing model",
        "subject_json": {"type": "project", "ref": "pricing-model"},
        "actors_json": [{"ref": "Alice Chen", "role": "owner"}],
        "confidence": 0.95,
        "extraction_run_id": uuid4(),
        "created_at": datetime.now()
    }


@pytest.fixture
def sample_events_with_actors():
    """Sample events with actor entities."""
    alice_id = uuid4()
    bob_id = uuid4()
    event1_id = uuid4()
    event2_id = uuid4()

    return {
        "entities": [
            {"entity_id": alice_id, "canonical_name": "Alice Chen", "type": "person"},
            {"entity_id": bob_id, "canonical_name": "Bob Smith", "type": "person"}
        ],
        "events": [
            {
                "event_id": event1_id,
                "category": "Decision",
                "narrative": "Alice decided on pricing model",
                "artifact_uid": "doc_001",
                "revision_id": "rev_001"
            },
            {
                "event_id": event2_id,
                "category": "Commitment",
                "narrative": "Bob committed to design review",
                "artifact_uid": "doc_002",
                "revision_id": "rev_001"
            }
        ],
        "event_actors": [
            {"event_id": event1_id, "entity_id": alice_id, "role": "owner"},
            {"event_id": event2_id, "entity_id": bob_id, "role": "contributor"}
        ]
    }


# =============================================================================
# Mock Graph Service
# =============================================================================

@pytest.fixture
def mock_graph_service():
    """Mock GraphService for V4 tests."""
    mock = AsyncMock()

    # Default behaviors
    mock.check_age_available.return_value = True
    mock.upsert_entity_node.return_value = None
    mock.upsert_event_node.return_value = None
    mock.upsert_acted_in_edge.return_value = None
    mock.upsert_about_edge.return_value = None
    mock.upsert_possibly_same_edge.return_value = None
    mock.expand_from_events.return_value = []
    mock.get_entities_for_events.return_value = []

    # Default health stats
    mock.get_health.return_value = MagicMock(
        age_enabled=True,
        graph_exists=True,
        entity_node_count=0,
        event_node_count=0,
        acted_in_edge_count=0,
        about_edge_count=0,
        possibly_same_edge_count=0
    )

    return mock


@pytest.fixture
def mock_graph_service_unavailable():
    """Mock GraphService with AGE unavailable."""
    mock = AsyncMock()
    mock.check_age_available.return_value = False
    mock.expand_from_events.return_value = []
    return mock


# =============================================================================
# Sample Document Content
# =============================================================================

@pytest.fixture
def sample_document_with_entities():
    """Document with known entities for testing extraction."""
    return {
        "content": """
Meeting Notes - March 15, 2024

Attendees: Alice Chen (Engineering Manager), Bob Smith (Designer), Carol Davis (Product)

Alice Chen opened the meeting to discuss the Q2 roadmap. She mentioned that the pricing
decision needs to be finalized by end of week.

Bob presented the new design mockups. Carol noted that user feedback has been positive
so far.

ACTION ITEMS:
- Alice will finalize pricing model by Friday
- Bob to complete high-fidelity designs by March 20
- Carol to schedule user interviews

Email: achen@acme.com, bob@othercorp.com, carol@acme.com
""",
        "expected_entities": [
            {"surface_form": "Alice Chen", "type": "person", "role": "Engineering Manager"},
            {"surface_form": "Bob Smith", "type": "person", "role": "Designer"},
            {"surface_form": "Carol Davis", "type": "person", "role": "Product"}
        ],
        "expected_events_count": 3  # At least 3 commitments
    }


@pytest.fixture
def sample_document_same_person_different_forms():
    """Document where same person is mentioned in different forms."""
    return {
        "content": """
Project Update

Alice Chen reviewed the code changes. A. Chen approved the pull request.
Later, Alice mentioned she would handle the deployment.
""",
        "expected_entity_count": 1,  # Should merge to single entity
        "expected_aliases": ["Alice Chen", "A. Chen", "Alice"]
    }


@pytest.fixture
def sample_document_different_people_same_name():
    """Document where different people have similar names."""
    return {
        "content": """
Cross-team collaboration meeting:

Alice Chen (Engineer at Acme Corp) presented the backend architecture.
Alice Chen (Designer at OtherCorp) shared the UI mockups.

Both Alice's agreed to sync next week.
""",
        "expected_entity_count": 2  # Should NOT merge - different orgs
    }


# =============================================================================
# Entity Resolution Service Fixture
# =============================================================================

@pytest.fixture
def entity_resolution_service(mock_pg_client, mock_embedding_service, mock_openai_dedup_client):
    """Create EntityResolutionService with mocked dependencies."""
    from services.entity_resolution_service import EntityResolutionService

    service = EntityResolutionService(
        pg_client=mock_pg_client,
        embedding_service=mock_embedding_service,
        openai_client=mock_openai_dedup_client,
        similarity_threshold=0.85,
        max_candidates=5,
        model="gpt-4o-mini"
    )
    return service


# =============================================================================
# Graph Service Fixture
# =============================================================================

@pytest.fixture
def graph_service(mock_pg_client):
    """Create GraphService with mocked Postgres client."""
    from services.graph_service import GraphService

    service = GraphService(
        pg_client=mock_pg_client,
        graph_name="nur",
        query_timeout_ms=500
    )
    return service


# =============================================================================
# Retrieval Service V4 Fixture
# =============================================================================

@pytest.fixture
def mock_chroma_client():
    """Mock ChromaDB client for testing."""
    mock_client = MagicMock()
    mock_client.heartbeat.return_value = True

    mock_collection = MagicMock()
    mock_collection.name = "test_collection"
    mock_collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }

    mock_client.get_or_create_collection.return_value = mock_collection
    return mock_client


@pytest.fixture
def retrieval_service_v4(mock_embedding_service, mock_chroma_client, mock_pg_client, mock_graph_service):
    """Create RetrievalService with V4 capabilities."""
    from services.retrieval_service import RetrievalService
    from services.chunking_service import ChunkingService

    chunking_service = ChunkingService(
        single_piece_max=1200,
        chunk_target=900,
        chunk_overlap=100
    )

    service = RetrievalService(
        embedding_service=mock_embedding_service,
        chunking_service=chunking_service,
        chroma_client=mock_chroma_client,
        k=60,
        pg_client=mock_pg_client,
        graph_service=mock_graph_service
    )
    return service


# =============================================================================
# Test Data Helpers
# =============================================================================

@pytest.fixture
def create_mock_entity():
    """Factory fixture to create mock entities."""
    def _create(
        name: str = "Test Entity",
        entity_type: str = "person",
        role: Optional[str] = None,
        organization: Optional[str] = None,
        entity_id: Optional[UUID] = None
    ):
        return {
            "entity_id": entity_id or uuid4(),
            "entity_type": entity_type,
            "canonical_name": name,
            "normalized_name": name.lower(),
            "role": role,
            "organization": organization,
            "email": None,
            "first_seen_artifact_uid": "test_doc",
            "first_seen_revision_id": "rev_001",
            "needs_review": False
        }
    return _create


@pytest.fixture
def create_mock_event():
    """Factory fixture to create mock events."""
    def _create(
        category: str = "Decision",
        narrative: str = "Test event narrative",
        artifact_uid: str = "test_doc",
        event_id: Optional[UUID] = None
    ):
        return {
            "event_id": event_id or uuid4(),
            "artifact_uid": artifact_uid,
            "revision_id": "rev_001",
            "category": category,
            "event_time": datetime.now().isoformat(),
            "narrative": narrative,
            "subject_json": {"type": "project", "ref": "test-project"},
            "actors_json": [{"ref": "Test Actor", "role": "owner"}],
            "confidence": 0.9,
            "extraction_run_id": uuid4(),
            "created_at": datetime.now().isoformat()
        }
    return _create


# =============================================================================
# Async Test Support
# =============================================================================

@pytest.fixture
def event_loop_policy():
    """Use asyncio event loop for async tests."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()
